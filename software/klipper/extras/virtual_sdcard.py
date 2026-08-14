# Virtual sdcard support (print files directly from a host g-code file)
#
# Copyright (C) 2018-2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, sys, logging, io, re

VALID_GCODE_EXTS = {'gcode', 'g', 'gco', 'gx'}
VALID_GCODE_T = frozenset(['T0', 'T1', 'T2', 'T3', 'T4', 'T5'])
VALID_M104_T = frozenset(['M104', 'M109'])
EXTRUDER_COUNT = 4

_REGEX_T_VALUE = re.compile(r'T(\d+)')
_REGEX_S_VALUE = re.compile(r'S(\d+)')
_REGEX_SET_VELOCITY = re.compile(r'SET_VELOCITY_LIMIT')
_REGEX_SET_PA = re.compile(r'SET_PRESSURE_ADVANCE')

DEFAULT_ERROR_GCODE = """
{% if 'heaters' in printer %}
   TURN_OFF_HEATERS
{% endif %}
"""

class VirtualSD:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:shutdown",
                                            self.handle_shutdown)
        # sdcard state
        sd = config.get('path')
        self.sdcard_dirname = os.path.normpath(os.path.expanduser(sd))
        self.current_file = None
        self.file_position = self.file_size = 0
        # Print Stat Tracking
        self.print_stats = self.printer.load_object(config, 'print_stats')
        # Work timer
        self.reactor = self.printer.get_reactor()
        self.must_pause_work = self.cmd_from_sd = False
        self.next_file_position = 0
        self.work_timer = None
        self.load_channel = 0
        self.print_channel = 0
        self.speed_factor = 100
        self.speed_factor_enable = 0
        self.change_filament = False
        self.enable_ffm = False
        self.channel_x = 0.0;
        self.channel_y = 0.0;
        self.channel_z = 0.0;
        self.channel_e = 0.0;
        self.channel_speed = 0;
        self.pa_enable = 0
        self.adjust_M106P2 = 0
        self.adjust_M106 = 0
        self.factor_M106P2 = 0
        self.factor_M106 = 0
        self.pa_value_t0 = 99.0
        self.pa_value_t1 = 99.0
        self.pa_value_t2 = 99.0
        self.pa_value_t3 = 99.0
        self.m104 = "M104"
        self.m109 = "M109"
        self.set_velocity_limit = ""
        self.channel_pause_z = "0.0";
        self.channel_pause_x = "0.0";
        self.channel_pause_y = "0.0";
        self.channel_pause_is_z = False;
        self.channel_pause_is_x = False;
        self.channel_pause_is_y = False;
        self.after_channel_g1 = False;
        self.doingChangeEx = False;
        self.g1_lines = []
        self.need_check_ex = False
        self.no_filament_check_ex = False
        self.gcode_ex_used = ['T99', 'T99', 'T99', 'T99', 'T99', 'T99']
        self.gcode_ex_used_changed = ['T99', 'T99', 'T99', 'T99', 'T99', 'T99']
        # Error handling
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        self.on_error_gcode = gcode_macro.load_template(
            config, 'on_error_gcode', DEFAULT_ERROR_GCODE)
        # Register commands
        self.gcode = self.printer.lookup_object('gcode')
        for cmd in ['M20', 'M21', 'M23', 'M24', 'M25', 'M26', 'M27']:
            self.gcode.register_command(cmd, getattr(self, 'cmd_' + cmd))
        for cmd in ['M28', 'M29', 'M30']:
            self.gcode.register_command(cmd, self.cmd_error)
        self.gcode.register_command(
            "SDCARD_RESET_FILE", self.cmd_SDCARD_RESET_FILE,
            desc=self.cmd_SDCARD_RESET_FILE_help)
        self.gcode.register_command(
            "SDCARD_PRINT_FILE", self.cmd_SDCARD_PRINT_FILE,
            desc=self.cmd_SDCARD_PRINT_FILE_help)
        self.gcode.register_command(
            "SDCARD_CLEAR_REFUELLING", self.cmd_SDCARD_CLEAR_REFUELLING,
            desc=self.cmd_SDCARD_CLEAR_REFUELLING_help)
        self.gcode.register_command(
            "SDCARD_SET_CHANNEL", self.cmd_SDCARD_SET_CHANNEL,
            desc=self.cmd_SDCARD_SET_CHANNEL_help)
        self.gcode.register_command(
            "SDCARD_SET_PAUSE_STATE", self.cmd_SDCARD_SET_PAUSE_STATE,
            desc=self.cmd_SDCARD_SET_PAUSE_STATE_help)    
        self.gcode.register_command(
            "SDCARD_ENABLE_FFM", self.cmd_SDCARD_ENABLE_FFM,
            desc=self.cmd_SDCARD_ENABLE_FFM_help)  
        self.gcode.register_command(
            "SDCARD_SET_GCODE_EX_USED_BASE", self.cmd_SDCARD_SET_GCODE_EX_USED_BASE,
            desc=self.cmd_SDCARD_SET_GCODE_EX_USED_BASE_help)
        self.gcode.register_command(
            "SDCARD_SET_GCODE_EX_USED_CHANGED", self.cmd_SDCARD_SET_GCODE_EX_USED_CHANGED,
            desc=self.cmd_SDCARD_SET_GCODE_EX_USED_CHANGED_help)
        self.gcode.register_command(
            "SDCARD_SET_NEED_CHECK_EX", self.cmd_SDCARD_SET_NEED_CHECK_EX,
            desc=self.cmd_SDCARD_SET_NEED_CHECK_EX_help)
        self.gcode.register_command(
            "SDCARD_NO_FILAMENT_CHECK_EX", self.cmd_SDCARD_NO_FILAMENT_CHECK_EX,
            desc=self.cmd_SDCARD_NO_FILAMENT_CHECK_EX_help)
        self.gcode.register_command(
            "SET_PA_ADVANCE", self.cmd_SET_PA_ADVANCE,
            desc=self.cmd_SET_PA_ADVANCE_help)
        self.gcode.register_command(
            "SET_FAN_M106P2", self.cmd_SET_FAN_M106P2,
            desc=self.cmd_SET_FAN_M106P2_help)
        self.gcode.register_command(
            "SET_FAN_M106", self.cmd_SET_FAN_M106,
            desc=self.cmd_SET_FAN_M106_help)
        self.gcode.register_command(
            "SET_SPEED_PERCENT", self.cmd_SET_SPEED_PERCENT,
            desc=self.cmd_SET_SPEED_PERCENT_help)    
    def handle_shutdown(self):
        if self.work_timer is not None:
            self.must_pause_work = True
            try:
                readpos = max(self.file_position - 1024, 0)
                readcount = self.file_position - readpos
                self.current_file.seek(readpos)
                data = self.current_file.read(readcount + 128)
            except:
                logging.exception("virtual_sdcard shutdown read")
                return
            logging.info("Virtual sdcard (%d): %s\nUpcoming (%d): %s",
                         readpos, repr(data[:readcount]),
                         self.file_position, repr(data[readcount:]))
    def stats(self, eventtime):
        if self.work_timer is None:
            return False, ""
        return True, "sd_pos=%d" % (self.file_position,)
    def get_file_list(self, check_subdirs=False):
        if check_subdirs:
            flist = []
            prefix_len = len(self.sdcard_dirname) + 1
            for root, dirs, files in os.walk(self.sdcard_dirname, followlinks=True):
                for name in files:
                    dot_pos = name.rfind('.')
                    if dot_pos == -1:
                        continue
                    ext = name[dot_pos + 1:]
                    if ext not in VALID_GCODE_EXTS:
                        continue
                    full_path = os.path.join(root, name)
                    r_path = full_path[prefix_len:]
                    size = os.path.getsize(full_path)
                    flist.append((r_path, size))
            flist.sort(key=lambda f: f[0].lower())
            return flist
        else:
            dname = self.sdcard_dirname
            try:
                filenames = os.listdir(dname)
                result = []
                for fname in sorted(filenames, key=str.lower):
                    if fname.startswith('.'):
                        continue
                    full_path = os.path.join(dname, fname)
                    if os.path.isfile(full_path):
                        result.append((fname, os.path.getsize(full_path)))
                return result
            except:
                logging.exception("virtual_sdcard get_file_list")
                raise self.gcode.error("Unable to get file list")
    def get_status(self, eventtime):
        return {
            'file_path': self.file_path(),
            'progress': self.progress(),
            'is_active': self.is_active(),
            'file_position': self.file_position,
            'file_size': self.file_size,
            'channel': self.print_channel,
            'refuelling': self.change_filament,
            'after_channel_g1': self.after_channel_g1,
            'velocity_limit': self.set_velocity_limit,
            'doingChangeEx': self.doingChangeEx,
        }
    def file_path(self):
        if self.current_file:
            return self.current_file.name
        return None
    def progress(self):
        if self.file_size:
            return float(self.file_position) / self.file_size
        else:
            return 0.
    def is_active(self):
        return self.work_timer is not None
    def do_pause(self):
        if self.work_timer is not None:
            self.must_pause_work = True
            while self.work_timer is not None and not self.cmd_from_sd:
                self.reactor.pause(self.reactor.monotonic() + .001)
    def do_resume(self):
        if self.work_timer is not None:
            raise self.gcode.error("SD busy")
        self.must_pause_work = False
        self.g1_lines = []
        self.work_timer = self.reactor.register_timer(
            self.work_handler, self.reactor.NOW)
    def do_cancel(self):
        if self.current_file is not None:
            self.do_pause()
            self.current_file.close()
            self.current_file = None
            self.change_filament = False
            self.print_stats.note_cancel()
        self.file_position = self.file_size = 0
    # G-Code commands
    def cmd_error(self, gcmd):
        raise gcmd.error("SD write not supported")
    def _reset_file(self):
        if self.current_file is not None:
            self.do_pause()
            self.current_file.close()
            self.current_file = None
        self.file_position = self.file_size = 0
        self.print_stats.reset()
        self.printer.send_event("virtual_sdcard:reset_file")
    cmd_SDCARD_RESET_FILE_help = "Clears a loaded SD File. Stops the print "\
        "if necessary"
    def cmd_SDCARD_RESET_FILE(self, gcmd):
        if self.cmd_from_sd:
            raise gcmd.error(
                "SDCARD_RESET_FILE cannot be run from the sdcard")
        self._reset_file()
    cmd_SDCARD_PRINT_FILE_help = "Loads a SD file and starts the print.  May "\
        "include files in subdirectories."
    def cmd_SDCARD_PRINT_FILE(self, gcmd):
        if self.work_timer is not None:
            raise gcmd.error("SD busy")
        self._reset_file()
        filename = gcmd.get("FILENAME")
        if filename[0] == '/':
            filename = filename[1:]
        self._load_file(gcmd, filename, check_subdirs=True)
        self.do_resume()
    cmd_SDCARD_CLEAR_REFUELLING_help = "get printing pause line gcode "
    def cmd_SDCARD_CLEAR_REFUELLING(self, gcmd):
        self.change_filament = False
    cmd_SDCARD_SET_CHANNEL_help = "set load channel "
    def cmd_SDCARD_SET_CHANNEL(self, gcmd):
        channel = gcmd.get_int('CHANNEL')
        self.set_velocity_limit = ""
        self.load_channel = channel
        self.print_channel = channel
        logging.info("Set channel , start print: %d ", channel)
    cmd_SDCARD_SET_PAUSE_STATE_help = "set SDCARD_SET_PAUSE_STATE "
    def cmd_SDCARD_SET_PAUSE_STATE(self, gcmd):
        x = gcmd.get_float('X')
        y = gcmd.get_float('Y')
        z = gcmd.get_float('Z')
        e = gcmd.get_float('E')
        speed = gcmd.get_int('SPEED')
        self.channel_x = x
        self.channel_y = y
        self.channel_z = z
        self.channel_e = e
        self.channel_speed = speed
        self.after_channel_g1 = False;
    cmd_SDCARD_SET_GCODE_EX_USED_BASE_help = "print gcode file used extruder"
    def cmd_SDCARD_SET_GCODE_EX_USED_BASE(self, gcmd):
        index = gcmd.get_int('INDEX')
        ex = gcmd.get("EXTRUDER")
        self.gcode_ex_used[index] = ex
    cmd_SDCARD_SET_GCODE_EX_USED_CHANGED_help = "print gcode file changed extruder"
    def cmd_SDCARD_SET_GCODE_EX_USED_CHANGED(self, gcmd):
        index = gcmd.get_int('INDEX')
        ex = gcmd.get("EXTRUDER")
        self.gcode_ex_used_changed[index] = ex
    cmd_SDCARD_SET_NEED_CHECK_EX_help = "enable check extrude when print"
    def cmd_SDCARD_SET_NEED_CHECK_EX(self, gcmd):
        enable = gcmd.get_int('CHECK')
        self.need_check_ex = False
        if enable == 1:
            self.need_check_ex = True
    cmd_SDCARD_NO_FILAMENT_CHECK_EX_help = "no filament enable check other extrude when print"
    def cmd_SDCARD_NO_FILAMENT_CHECK_EX(self, gcmd):
        enable = gcmd.get_int('CHECK')
        self.no_filament_check_ex = False
        if enable == 1:
            self.no_filament_check_ex = True
    cmd_SDCARD_ENABLE_FFM_help = "enable ffm "
    def cmd_SDCARD_ENABLE_FFM(self, gcmd):
        enable = gcmd.get_int('ENABLE')
        self.enable_ffm = False
        if enable == 1:
            self.enable_ffm = True
    def cmd_SET_PA_ADVANCE(self, gcmd):
        self.pa_value_t0 = gcmd.get_float('T0')
        self.pa_value_t1 = gcmd.get_float('T1')
        self.pa_value_t2 = gcmd.get_float('T2')
        self.pa_value_t3 = gcmd.get_float('T3')
        self.pa_enable = gcmd.get_int('ENABLE')
        logging.info("set advance pa_value: (%f), (%f), (%f), (%f)",self.pa_value_t0,self.pa_value_t1,self.pa_value_t2,self.pa_value_t3)
    cmd_SET_PA_ADVANCE_help = "print change pa value"
    def cmd_SET_FAN_M106P2(self, gcmd):
        self.adjust_M106P2 = gcmd.get_int('ADJUSTED')
        self.factor_M106P2 = gcmd.get_int('FACTOR')
    cmd_SET_FAN_M106P2_help = "print change M106 P2"
    def cmd_SET_FAN_M106(self, gcmd):
        self.adjust_M106 = gcmd.get_int('ADJUSTED')
        self.factor_M106 = gcmd.get_int('FACTOR')
    cmd_SET_FAN_M106_help = "print change M106"
    def cmd_SET_SPEED_PERCENT(self, gcmd):
        self.speed_factor = gcmd.get_int('PERCENT')
        self.speed_factor_enable = gcmd.get_int('ENABLE')
    cmd_SET_SPEED_PERCENT_help = "print change speed M220 Sxx"
    def cmd_M20(self, gcmd):
        # List SD card
        files = self.get_file_list()
        gcmd.respond_raw("Begin file list")
        for fname, fsize in files:
            gcmd.respond_raw("%s %d" % (fname, fsize))
        gcmd.respond_raw("End file list")
    def cmd_M21(self, gcmd):
        # Initialize SD card
        gcmd.respond_raw("SD card ok")
    def cmd_M23(self, gcmd):
        # Select SD file
        if self.work_timer is not None:
            raise gcmd.error("SD busy")
        self._reset_file()
        #self.print_channel = 0
        self.change_filament = False
        self.enable_ffm = False
        self.set_velocity_limit = ""
        filename = gcmd.get_raw_command_parameters().strip()
        if filename.startswith('/'):
            filename = filename[1:]
        self._load_file(gcmd, filename)
    def _load_file(self, gcmd, filename, check_subdirs=False):
        files = self.get_file_list(check_subdirs)
        flist = [f[0] for f in files]
        files_by_lower = { fname.lower(): fname for fname, fsize in files }
        fname = filename
        try:
            #if fname not in flist:
                #fname = files_by_lower[fname.lower()]
            fname = os.path.join(self.sdcard_dirname, fname)
            f = io.open(fname, 'r', newline='')
            f.seek(0, os.SEEK_END)
            fsize = f.tell()
            f.seek(0)
        except:
            logging.exception("virtual_sdcard file open")
            raise gcmd.error("Unable to open file")
        gcmd.respond_raw("File opened:%s Size:%d" % (filename, fsize))
        gcmd.respond_raw("File selected")
        self.current_file = f
        self.file_position = 0
        self.file_size = fsize
        self.print_stats.set_current_file(filename)
    def cmd_M24(self, gcmd):
        # Start/resume SD print
        self.do_resume()
    def cmd_M25(self, gcmd):
        # Pause SD print
        self.do_pause()
    def cmd_M26(self, gcmd):
        # Set SD position
        if self.work_timer is not None:
            raise gcmd.error("SD busy")
        pos = gcmd.get_int('S', minval=0)
        self.file_position = pos
    def cmd_M27(self, gcmd):
        # Report SD print status
        if self.current_file is None:
            gcmd.respond_raw("Not SD printing.")
            return
        gcmd.respond_raw("SD printing byte %d/%d"
                         % (self.file_position, self.file_size))
    def get_file_position(self):
        return self.next_file_position
    def set_file_position(self, pos):
        self.next_file_position = pos
    def is_cmd_from_sd(self):
        return self.cmd_from_sd
    _REGEX_COORD_X = re.compile(r'X([\d.]+)')
    _REGEX_COORD_Y = re.compile(r'Y([\d.]+)')
    _REGEX_COORD_Z = re.compile(r'Z([\d.]+)')

    def extract_coord(self, line, coord_char):
        if coord_char == 'X':
            match = self._REGEX_COORD_X.search(line)
        elif coord_char == 'Y':
            match = self._REGEX_COORD_Y.search(line)
        elif coord_char == 'Z':
            match = self._REGEX_COORD_Z.search(line)
        else:
            return '0'
        return match.group(1) if match else '0'
    # Background work timer
    def work_handler(self, eventtime):
        logging.info("Starting SD card print (position %d)", self.file_position)
        self.reactor.unregister_timer(self.work_timer)
        try:
            self.current_file.seek(self.file_position)
        except:
            logging.exception("virtual_sdcard seek")
            self.work_timer = None
            return self.reactor.NEVER
        self.print_stats.note_start()
        gcode_mutex = self.gcode.get_mutex()
        partial_input = ""
        lines = []
        exclude_line = ""
        exclude_flag = False
        error_message = None
        while not self.must_pause_work:
            if not lines:
                try:
                    data = self.current_file.read(32768)
                except:
                    logging.exception("virtual_sdcard read")
                    break
                if not data:
                    self.current_file.close()
                    self.current_file = None
                    logging.info("Finished SD card print")
                    self.gcode.respond_raw("Done printing file")
                    break
                raw_lines = data.split('\n')
                raw_lines[0] = partial_input + raw_lines[0]
                partial_input = raw_lines.pop()
                lines.extend(reversed(raw_lines))
                self.reactor.pause(self.reactor.NOW)
                continue
            # Pause if any other request is pending in the gcode class
            if gcode_mutex.test():
                self.reactor.pause(self.reactor.monotonic() + 0.100)
                continue
            # Dispatch command
            self.cmd_from_sd = True
            line = lines.pop()
            if sys.version_info.major >= 3:
                next_file_position = self.file_position + len(line.encode()) + 1
            else:
                next_file_position = self.file_position + len(line) + 1
            self.next_file_position = next_file_position
            
            if not line.startswith(";"):
                t_match = _REGEX_T_VALUE.search(line)
                if t_match:
                    ex_index = t_match.group(1)
                    if self.need_check_ex or self.no_filament_check_ex:
                        str_base = "T" + ex_index
                        try:
                            i_base = self.gcode_ex_used.index(str_base)
                        except ValueError:
                            i_base = -1
                        if i_base >= 0:
                            changed_ex = self.gcode_ex_used_changed[i_base]
                            line = line.replace(str_base, changed_ex, 1)
                        else:
                            line = line.replace(str_base, f'T{int(ex_index) % EXTRUDER_COUNT}', 1)
                    else:
                        line = line.replace(f'T{ex_index}', f'T{int(ex_index) % EXTRUDER_COUNT}', 1)

                raw = line.lstrip()
                if raw.startswith("S"):
                    if _REGEX_SET_VELOCITY.search(line):
                        self.set_velocity_limit = line.rstrip()
                    elif _REGEX_SET_PA.search(line) and self.pa_enable == 1:
                        pa_values = [self.pa_value_t0, self.pa_value_t1, 
                                     self.pa_value_t2, self.pa_value_t3]
                        pa_value = pa_values[self.load_channel] if self.load_channel < 4 else self.pa_value_t0
                        if pa_value > 10.0:
                            self.gcode.run_script(line)
                        else:
                            self.gcode.run_script(f"SET_PRESSURE_ADVANCE ADVANCE={pa_value}")
                        self.file_position = self.next_file_position
                        continue

                if 'M106' in line:
                    comment_pos = line.find(';')
                    if comment_pos != -1:
                        line = line[:comment_pos]
                    line = line.strip()
                    s_match = _REGEX_S_VALUE.search(line)
                    if s_match:
                        speed = int(s_match.group(1))
                        if 'P2' in line and self.adjust_M106P2 == 1:
                            target_speed = speed + int(self.factor_M106P2 * 255 / 100)
                            self.gcode.run_script(f"M106 P2 S{target_speed}")
                            self.file_position = self.next_file_position
                            continue
                        elif 'P' not in line and self.adjust_M106 == 1:
                            target_speed = speed + int(self.factor_M106 * 255 / 100)
                            self.gcode.run_script(f"M106 S{target_speed}")
                            self.file_position = self.next_file_position
                            continue
                            
                #if self.speed_factor_enable == 1 and 'M220' in line:
                #    line = (f"M220 S{self.speed_factor}")
                    
                if self.after_channel_g1 and ('G1' in line or 'G0' in line):
                    comment_pos = line.find(';')
                    if comment_pos != -1:
                        line = line[:comment_pos]
                    line = line.strip()
                    
                    self.channel_pause_is_z = 'Z' in line
                    self.channel_pause_is_x = 'X' in line
                    self.channel_pause_is_y = 'Y' in line
                    
                    if self.channel_pause_is_z:
                        self.channel_pause_z = self.extract_coord(line, 'Z')
                    if self.channel_pause_is_x:
                        self.channel_pause_x = self.extract_coord(line, 'X')
                    if self.channel_pause_is_y:
                        self.channel_pause_y = self.extract_coord(line, 'Y')
                    
                    if self.channel_pause_is_y and self.channel_pause_is_x:
                        self.gcode.run_script(f"G1 X{self.channel_pause_x} Y{self.channel_pause_y} F36000")
                        if self.channel_pause_is_z:
                            self.gcode.run_script(f"G1 Z{self.channel_pause_z} F500")
                        else:
                            self.gcode.run_script(f"G1 Z{self.channel_z} F500")
                        self.after_channel_g1 = False
                        self.channel_pause_is_z = False
                        self.channel_pause_is_y = False
                        self.channel_pause_is_x = False
                    self.doingChangeEx = False
                    self.file_position = self.next_file_position
                    continue

                if (self.m104 in line or self.m109 in line) and 'T' not in line:
                    comment_pos = line.find(';')
                    if comment_pos != -1:
                        line = line[:comment_pos]
                    line = line.strip() + " T" + str(self.print_channel)

                if line.startswith("EXCLUDE_OBJECT_START"):
                    exclude_line = line
                elif line.startswith("EXCLUDE_OBJECT_END"):
                    exclude_line = line

                if "WIPE_TOWER_START" in line:
                    if exclude_line and exclude_line.startswith("EXCLUDE_OBJECT_START"):
                        exclude_line = exclude_line.replace("EXCLUDE_OBJECT_START", "EXCLUDE_OBJECT_END")
                        self.gcode.run_script(exclude_line)
                        exclude_flag = True

                if "WIPE_TOWER_END" in line and exclude_flag:
                    exclude_flag = False
                    if exclude_line:
                        exclude_line = exclude_line.replace("EXCLUDE_OBJECT_END", "EXCLUDE_OBJECT_START")
                        self.gcode.run_script(exclude_line)

                if line.startswith("T") and line in VALID_GCODE_T:
                    self.print_channel = int(line[1:])
                    if self.print_channel != self.load_channel:
                        self.gcode.run_script("M400")
                        self.change_filament = True
                        self.doingChangeEx = True
                        while self.change_filament:
                            self.reactor.pause(self.reactor.monotonic() + 0.05)
                        self.gcode.run_script(self.set_velocity_limit)
                        self.after_channel_g1 = True
                    self.load_channel = self.print_channel
                    self.change_filament = False
                    self.file_position = self.next_file_position
                    continue

                try:
                    self.gcode.run_script(line)
                except self.gcode.error as e:
                    error_message = str(e)
                    try:
                        self.gcode.run_script(self.on_error_gcode.render())
                    except:
                        logging.exception("virtual_sdcard on_error")
                    break
                except:
                    logging.exception("virtual_sdcard dispatch")
                    break
            self.cmd_from_sd = False
            self.file_position = self.next_file_position
            # Do we need to skip around?
            if self.next_file_position != next_file_position:
                try:
                    self.current_file.seek(self.file_position)
                except:
                    logging.exception("virtual_sdcard seek")
                    self.work_timer = None
                    return self.reactor.NEVER
                lines = []
                partial_input = ""
        logging.info("Exiting SD card print (position %d)", self.file_position)
        self.work_timer = None
        self.cmd_from_sd = False
        if error_message is not None:
            self.print_stats.note_error(error_message)
        elif self.current_file is not None:
            self.print_stats.note_pause()
        else:
            self.print_stats.note_complete()
        return self.reactor.NEVER

def load_config(config):
    return VirtualSD(config)
