#ifndef __GCODE_PARSER_H
#define __GCODE_PARSER_H

struct gcode_parse_result {
    unsigned char has_T;
    unsigned char has_S;
    unsigned char is_comment;
    unsigned char is_M106;
    unsigned char is_M104;
    unsigned char is_M109;
    unsigned char is_G0;
    unsigned char is_G1;
    unsigned char is_SET_VELOCITY;
    unsigned char is_SET_PA;
    unsigned char is_EXCLUDE_START;
    unsigned char is_EXCLUDE_END;
    unsigned char is_WIPE_START;
    unsigned char is_WIPE_END;
    unsigned char has_P2;
    unsigned char has_T_in_line;
    unsigned char has_X;
    unsigned char has_Y;
    unsigned char has_Z;
    int T_value;
    int S_value;
};

struct gcode_g1_params {
    unsigned char has_X;
    unsigned char has_Y;
    unsigned char has_Z;
    unsigned char has_E;
    unsigned char has_F;
    double X;
    double Y;
    double Z;
    double E;
    double F;
};

struct gcode_parse_result gcode_parse(const char *line, int len);
int gcode_find_comment(const char *line, int len);
int gcode_extract_coord(const char *line, int len, char axis,
                        char *buf, int buf_len);
int gcode_parse_g1(const char *line, int len,
                   struct gcode_g1_params *out);

#endif // __GCODE_PARSER_H
