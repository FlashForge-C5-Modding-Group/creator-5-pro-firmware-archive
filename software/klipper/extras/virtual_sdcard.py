# Virtual sdcard support (print files directly from a host g-code file)
#
# Copyright (C) 2018-2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, sys, logging, io

VALID_GCODE_EXTS = ['gcode', 'g', 'gco','gx']
VALID_GCODE_T = ['T0', 'T1', 'T2', 'T3', 'T4', 'T5']
VALID_M104_T = ['M104', 'M109']
EXTRUDER_COUNT = 4

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
            for root, dirs, files in os.walk(
                    self.sdcard_dirname, followlinks=True):
                for name in files:
                    ext = name[name.rfind('.')+1:]
                    if ext not in VALID_GCODE_EXTS:
                        continue
                    full_path = os.path.join(root, name)
                    r_path = full_path[len(self.sdcard_dirname) + 1:]
                    size = os.path.getsize(full_path)
                    flist.append((r_path, size))
            return sorted(flist, key=lambda f: f[0].lower())
        else:
            dname = self.sdcard_dirname
            try:
                filenames = os.listdir(self.sdcard_dirname)
                return [(fname, os.path.getsize(os.path.join(dname, fname)))
                        for fname in sorted(filenames, key=str.lower)
                        if not fname.startswith('.')
                        and os.path.isfile((os.path.join(dname, fname)))]
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
    def extract_between_chars(self,src, char1, char2):
        try:
            start = src.index(char1) + 1
            end = src.index(char2, start)
            return src[start:end]
        except ValueError:
            return '0'
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
        velocity_str = ""
        lines = []
        exclude_line = []
        exclude_flag = False
        error_message = None
        while not self.must_pause_work:
            if not lines:
                # Read more data
                try:
                    data = self.current_file.read(8192)
                except:
                    logging.exception("virtual_sdcard read")
                    break
                if not data:
                    # End of file
                    self.current_file.close()
                    self.current_file = None
                    logging.info("Finished SD card print")
                    self.gcode.respond_raw("Done printing file")
                    break
                lines = data.split('\n')
                lines[0] = partial_input + lines[0]
                partial_input = lines.pop()
                lines.reverse()
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
            
            # Start: Convert extruder index to 0~3
            if ((self.m104 in line) or (self.m109 in line)) and ("T" in line) and (line.startswith(";") == False) :
                if ';' in line :
                    index = line.index(';')
                    line = line[:index]
                parts = line.split()
                for i in range(len(parts)):
                    if parts[i][0] == 'T':
                        ex_index = parts[i][1:]
                        if ex_index.isdigit() :
                            if self.need_check_ex or self.no_filament_check_ex :
                                strBase = "T" + str(ex_index)
                                try :
                                    iBase = self.gcode_ex_used.index(strBase)
                                except ValueError :
                                    iBase = -1
                                    parts[i] = f'T{int(ex_index) % EXTRUDER_COUNT}'
                                    logging.info("T:Convert exIndex not found (%s)",old_line)
                                if iBase >= 0 :
                                    strChanged = self.gcode_ex_used_changed[iBase]
                                    parts[i] = strChanged
                            else :
                                parts[i] = f'T{int(ex_index) % EXTRUDER_COUNT}'
                        break
                new_line = ' '.join(parts)
                logging.info("Temp:Convert exIndex from : (%s), to : (%s)",line,new_line)
                line = new_line
                
            if line.startswith("T") :
                old_line = line
                ex_index = old_line[old_line.rfind('T')+1:].strip()
                if ex_index.isdigit():
                    if self.need_check_ex or self.no_filament_check_ex :
                        strBase = "T" + str(ex_index)
                        try :
                            iBase = self.gcode_ex_used.index(strBase)
                        except ValueError :
                            iBase = -1
                            str_int = (int(ex_index)) % EXTRUDER_COUNT
                            line = "T" + str(str_int)
                        if iBase >= 0 :
                            strChanged = self.gcode_ex_used_changed[iBase]
                            line = strChanged
                    else :
                        int_t = (int(ex_index)) % EXTRUDER_COUNT
                        line = "T" + str(int_t)
                    logging.info("T:Convert exIndex from : (%s), to : (%s)",old_line,line)
            # End: Convert extruder index to 0~3
            
            # get SET_VELOCITY_LIMIT from gcode 
            if ('SET_VELOCITY_LIMIT' in line) and (line.startswith(";") == False) :
                velocity_str = line.rstrip()
                self.set_velocity_limit = velocity_str
            if ('SET_PRESSURE_ADVANCE' in line) and ((line.startswith(";") == False) and (self.pa_enable == 1)) :
                if (self.load_channel == 0) :
                    pa_value = self.pa_value_t0
                elif (self.load_channel == 1) :
                    pa_value = self.pa_value_t1
                elif (self.load_channel == 2) :
                    pa_value = self.pa_value_t2
                elif (self.load_channel == 3) :
                    pa_value = self.pa_value_t3
                    
                if pa_value > 10.0 :
                    self.gcode.run_script(line)
                    #logging.info("gcode pa_value: (%s), self.load_channel: (%d)",line,self.load_channel)
                else :
                    str_pa = "SET_PRESSURE_ADVANCE ADVANCE=" + str(pa_value)
                    self.gcode.run_script(str_pa)
                    #logging.info("PATest-set_pa_advance: (%s), self.load_channel: (%d)",str_pa,self.load_channel)
                self.file_position = self.next_file_position
                continue
            #check adjust M106 P2 from firmware
            if ('M106' in line) and (line.startswith(";") == False) :
                if ';' in line :
                    index = line.index(';')
                    line = line[:index]
                line = line.strip()
                if ('P2' in line) and (self.adjust_M106P2 == 1) :
                    speed = int(line.split('S')[-1])
                    targetSpeed = speed + int(self.factor_M106P2 * 255 / 100)
                    self.gcode.run_script("M106 P2 S" + str(targetSpeed))
                    #logging.info("M106 P2, speed: (%d), starget speed: (%d)",speed,targetSpeed)
                    self.file_position = self.next_file_position
                    continue
                if ('P' not in line) and (self.adjust_M106 == 1) :
                    speed = int(line.split('S')[-1])
                    targetSpeed = speed + int(self.factor_M106 * 255 / 100)
                    self.gcode.run_script("M106 S" + str(targetSpeed))
                    #logging.info("M106, speed: (%d), starget speed: (%d)",speed,targetSpeed)
                    self.file_position = self.next_file_position
                    continue
            #check after change channel find g1 (go g1 here)
            if (self.after_channel_g1) and (('G1' in line) or ('G0' in line)) and (line.startswith(";") == False) :
                if ';' in line :
                    index = line.index(';')
                    line = line[:index]
                line = line.strip()
                line = line + " "
                #logging.info("Before change channel first go G1 (%s)",line)
                if 'Z' in line :
                    self.channel_pause_z = self.extract_between_chars(line,'Z',' ')
                    self.channel_pause_is_z = True
                if 'X' in line :
                    self.channel_pause_x = self.extract_between_chars(line,'X',' ')
                    self.channel_pause_is_x = True
                if 'Y' in line :
                    self.channel_pause_y = self.extract_between_chars(line,'Y',' ')
                    self.channel_pause_is_y = True
                if self.channel_pause_is_y and self.channel_pause_is_x :
                    pause_gcode = "G1" + " X" + self.channel_pause_x + " Y" + self.channel_pause_y + " F36000"
                    #logging.info("After change channel first go pause_gcode_xy (%s)",pause_gcode)
                    self.gcode.run_script(pause_gcode)
                    if self.channel_pause_is_z :
                        pause_gcode = "G1" + " Z" + self.channel_pause_z + " F500"
                        #logging.info("After change channel first go pause_gcode_z (gcode z) (%s)",pause_gcode)
                        self.gcode.run_script(pause_gcode)
                    else :
                        pause_gcode = "G1" + " Z" + str(self.channel_z) + " F500"
                        #logging.info("After change channel first go pause_gcode_z (channel_z): (%s)",pause_gcode)
                        self.gcode.run_script(pause_gcode)    
                    self.after_channel_g1 = False
                    self.channel_pause_is_z = False
                    self.channel_pause_is_y = False
                    self.channel_pause_is_x = False
                self.doingChangeEx = False
                self.file_position = self.next_file_position
                continue
            #end check after change channel find g1 (go g1 here)
            #check m104/m109 whitch no extruder
            if ((self.m104 in line) or (self.m109 in line)) and ("T" not in line) and (line.startswith(";") == False) :
                if ';' in line :
                    index = line.index(';')
                    line = line[:index]
                line = line.strip() + " T" + str(self.print_channel)
            #end check m104/m109 whitch extruder
            if line.startswith("EXCLUDE_OBJECT_START") or line.startswith("EXCLUDE_OBJECT_END") :
                exclude_line = []
                exclude_line = line
            if "WIPE_TOWER_START" in line :
                exclude_line = str(exclude_line)
                if exclude_line.startswith("EXCLUDE_OBJECT_START") :
                    #logging.info("======change head, start send exclude_object_end")
                    exclude_line = exclude_line.replace("EXCLUDE_OBJECT_START", "EXCLUDE_OBJECT_END")
                    #logging.info("exclude_line=[%s]", exclude_line)
                    self.gcode.run_script(exclude_line)
                    exclude_flag = True
            if "WIPE_TOWER_END" in line :
                exclude_line = str(exclude_line)
                if exclude_flag :
                    exclude_flag = False
                    #logging.info("======change back,  send exclude_object_start")
                    exclude_line = exclude_line.replace("EXCLUDE_OBJECT_END", "EXCLUDE_OBJECT_START")
                    #logging.info("exclude_line=[%s]", exclude_line)
                    self.gcode.run_script(exclude_line)
            if line in VALID_GCODE_T and line.startswith("T"):
                self.print_channel = int(line[line.rfind('T')+1:])
                if self.print_channel != self.load_channel:
                    self.gcode.run_script("M400")
                    self.change_filament = True
                    self.doingChangeEx = True
                    #if self.set_velocity_limit != "" :
                    #    limit = "SET_VELOCITY_LIMIT ACCEL=30000"
                    #    self.gcode.run_script(limit)
                        #logging.info("Change channel update accel:%s",limit)
                    while True:
                        if not self.change_filament:
                           self.gcode.run_script(self.set_velocity_limit)
                           logging.info("Change channel complete back to gcode accel:%s",self.set_velocity_limit)
                           break 
                        self.reactor.pause(self.reactor.monotonic() + 0.05)
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
