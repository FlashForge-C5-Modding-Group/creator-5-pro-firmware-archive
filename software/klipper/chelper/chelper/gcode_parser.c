#include <string.h>
#include "compiler.h"
#include "gcode_parser.h"

static inline int skip_spaces(const char *line, int len, int i)
{
    while (i < len && (line[i] == ' ' || line[i] == '\t'))
        i++;
    return i;
}

static inline int is_digit(char c)
{
    return c >= '0' && c <= '9';
}

static inline int parse_digits(const char *line, int len, int i, int *value)
{
    *value = 0;
    while (i < len && is_digit(line[i])) {
        *value = *value * 10 + (line[i] - '0');
        i++;
    }
    return i;
}

static inline int cmp_nocase(const char *s1, const char *s2, int len)
{
    for (int i = 0; i < len; i++) {
        char c1 = s1[i], c2 = s2[i];
        if (c1 >= 'A' && c1 <= 'Z')
            c1 += 32;
        if (c2 >= 'A' && c2 <= 'Z')
            c2 += 32;
        if (c1 != c2)
            return 0;
    }
    return 1;
}

__visible struct gcode_parse_result
gcode_parse(const char *line, int len)
{
    struct gcode_parse_result res;
    memset(&res, 0, sizeof(res));
    int i = 0;

    i = skip_spaces(line, len, i);
    if (i >= len)
        return res;

    if (line[i] == ';') {
        res.is_comment = 1;
        return res;
    }

    char first_char = line[i];
    if (first_char == 'T') {
        i++;
        if (i < len && is_digit(line[i])) {
            res.has_T = 1;
            i = parse_digits(line, len, i, &res.T_value);
        }
    } else if (first_char == 'M') {
        i++;
        if (len - i >= 3) {
            if (line[i] == '1' && line[i+1] == '0') {
                if (line[i+2] == '6')
                    res.is_M106 = 1;
                else if (line[i+2] == '4')
                    res.is_M104 = 1;
                else if (line[i+2] == '9')
                    res.is_M109 = 1;
            }
        }
    } else if (first_char == 'G') {
        i++;
        if (i < len) {
            if (line[i] == '0')
                res.is_G0 = 1;
            else if (line[i] == '1')
                res.is_G1 = 1;
        }
    } else if (first_char == 'S') {
        if (len - i >= 18 && cmp_nocase(&line[i], "SET_VELOCITY_LIMIT", 18)) {
            res.is_SET_VELOCITY = 1;
        } else if (len - i >= 20
                   && cmp_nocase(&line[i], "SET_PRESSURE_ADVANCE", 20)) {
            res.is_SET_PA = 1;
        }
    } else if (len - i >= 20
               && cmp_nocase(&line[i], "EXCLUDE_OBJECT_START", 20)) {
        res.is_EXCLUDE_START = 1;
    } else if (len - i >= 18
               && cmp_nocase(&line[i], "EXCLUDE_OBJECT_END", 18)) {
        res.is_EXCLUDE_END = 1;
    } else if (len - i >= 16
               && cmp_nocase(&line[i], "WIPE_TOWER_START", 16)) {
        res.is_WIPE_START = 1;
    } else if (len - i >= 14
               && cmp_nocase(&line[i], "WIPE_TOWER_END", 14)) {
        res.is_WIPE_END = 1;
    }

    for (i = 0; i < len; i++) {
        char c = line[i];
        if (c == 'T') {
            res.has_T_in_line = 1;
        } else if (c == 'P' && i + 1 < len && line[i+1] == '2') {
            res.has_P2 = 1;
            i++;
        } else if (c == 'X') {
            res.has_X = 1;
        } else if (c == 'Y') {
            res.has_Y = 1;
        } else if (c == 'Z') {
            res.has_Z = 1;
        } else if (c == 'S' && i + 1 < len && is_digit(line[i+1])) {
            res.has_S = 1;
            i = parse_digits(line, len, i + 1, &res.S_value);
        }
    }

    return res;
}

__visible int
gcode_find_comment(const char *line, int len)
{
    for (int i = 0; i < len; i++) {
        if (line[i] == ';')
            return i;
    }
    return -1;
}

__visible int
gcode_extract_coord(const char *line, int len, char axis, char *buf, int buf_len)
{
    for (int i = 0; i < len; i++) {
        if (line[i] == axis) {
            i++;
            int j = 0;
            while (i < len && j < buf_len - 1) {
                char c = line[i];
                if (c == ' ' || c == '\t' || c == ';')
                    break;
                buf[j++] = c;
                i++;
            }
            buf[j] = '\0';
            return 0;
        }
    }
    buf[0] = '0';
    buf[1] = '\0';
    return -1;
}

static int
parse_float(const char *line, int len, int i, double *value)
{
    int start = i;
    double sign = 1.0;
    if (i < len && (line[i] == '-' || line[i] == '+')) {
        if (line[i] == '-')
            sign = -1.0;
        i++;
    }
    double v = 0.0;
    int ndigits = 0;
    while (i < len && is_digit(line[i])) {
        v = v * 10.0 + (line[i] - '0');
        i++;
        ndigits++;
    }
    if (i < len && line[i] == '.') {
        i++;
        double frac = 0.0, scale = 1.0;
        while (i < len && is_digit(line[i])) {
            frac = frac * 10.0 + (line[i] - '0');
            scale *= 10.0;
            i++;
            ndigits++;
        }
        v += frac / scale;
    }
    if (ndigits == 0)
        return start;
    if (i < len && (line[i] == 'e' || line[i] == 'E')) {
        int j = i + 1;
        double esign = 1.0;
        if (j < len && (line[j] == '-' || line[j] == '+')) {
            if (line[j] == '-')
                esign = -1.0;
            j++;
        }
        int exp = 0, nexp = 0;
        while (j < len && is_digit(line[j])) {
            exp = exp * 10 + (line[j] - '0');
            j++;
            nexp++;
        }
        if (nexp > 0) {
            double mult = 1.0;
            for (int k = 0; k < exp && k < 40; k++)
                mult *= 10.0;
            if (esign < 0.0)
                v /= mult;
            else
                v *= mult;
            i = j;
        }
    }
    *value = sign * v;
    return i;
}

__visible int
gcode_parse_g1(const char *line, int len, struct gcode_g1_params *out)
{
    memset(out, 0, sizeof(*out));
    int i = skip_spaces(line, len, 0);
    if (i >= len)
        return -1;
    if (line[i] != 'G')
        return -1;
    i++;
    if (i >= len || (line[i] != '1' && line[i] != '0'))
        return -1;
    i++;
    if (i < len && line[i] != ' ' && line[i] != '\t' && line[i] != ';')
        return -1;
    while (i < len) {
        i = skip_spaces(line, len, i);
        if (i >= len)
            break;
        char c = line[i];
        if (c == ';')
            break;
        double *target = NULL;
        unsigned char *flag = NULL;
        if (c == 'X') {
            target = &out->X; flag = &out->has_X;
        } else if (c == 'Y') {
            target = &out->Y; flag = &out->has_Y;
        } else if (c == 'Z') {
            target = &out->Z; flag = &out->has_Z;
        } else if (c == 'E') {
            target = &out->E; flag = &out->has_E;
        } else if (c == 'F') {
            target = &out->F; flag = &out->has_F;
        } else {
            return -2;
        }
        i++;
        int ni = parse_float(line, len, i, target);
        if (ni == i)
            return -3;
        i = ni;
        *flag = 1;
    }
    return 0;
}
