# Printer mcu ctrl temp
#
# Copyright (C) 2016-2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import pulse_counter, output_pin

class Mcuctrltemp:
    def __init__(self, config):
        # Register commands
        self.printer = config.get_printer()
        gcode = config.get_printer().lookup_object('gcode')
        gcode.register_command("TEMP_MCU", self.cmd_TEMP_MCU)
        gcode.register_command("SET_PID_PARA", self.cmd_SET_PID_PARA)
        gcode.register_command("PID_CAL_START", self.cmd_PID_CAL_START)
        gcode.register_command("GET_PID_CAL_STATS", self.cmd_GET_PID_CAL_STATS)

        self.mcu = self.printer.lookup_object('mcu eheaterboard')
        self.mcu.register_config_callback(self.build_config)
        self._temp_set_cmd = None
        #start end
    def build_config(self):
        self._temp_set_cmd = self.mcu.lookup_command(
            "temp_set value=%u num=%u")
        self._set_pid_para = self.mcu.lookup_command(
            "set_pid_para num=%u pv=%u iv=%u dv=%u")
        self._pid_cal_start = self.mcu.lookup_command(
            "pid_cal_start num=%u")
        self._get_pid_cal_stats = self.mcu.lookup_query_command(
            "get_pid_cal_stats num=%u",
            "pid_cal_stats stats=%u pr=%u ir=%u dr=%u")
        
    def cmd_TEMP_MCU(self, gcmd):
        #目标温度值
        value = gcmd.get_int('TEMP', 0)
        #喷头序号
        num = gcmd.get_int('NUM', 0)
        self._temp_set_cmd.send([value, num])
    def cmd_SET_PID_PARA(self, gcmd):
        num = gcmd.get_int('NUM', 0)
        PV = gcmd.get_float('PV', 0.0)
        IV = gcmd.get_float('IV', 0.0)
        DV = gcmd.get_float('DV', 0.0)
        self._set_pid_para.send([num, int(PV*1000), int(IV*1000), int(DV*1000)])
    def cmd_PID_CAL_START(self, gcmd):
        num = gcmd.get_int('NUM', 0)
        self._pid_cal_start.send([num])
    def cmd_GET_PID_CAL_STATS(self, gcmd):
        num = gcmd.get_int('NUM', 0)
        result = self._get_pid_cal_stats.send([num])
        pr = int(result["pr"])/1000.0
        ir = int(result["ir"])/1000.0
        dr = int(result["dr"])/1000.0
        gcmd.respond_info("Result is num=%d,stats=%s,pr=%.3f,ir=%.3f,dr=%.3f" % (num, result["stats"], pr, ir, dr))
def load_config(config):
    return Mcuctrltemp(config)



#[temp_ctrl]

#TEMP_MCU TEMP=50 NUM=1

#void
#command_temp_set(uint32_t *args)
#{
#    uint32_t temp_value = args[0];
#    uint32_t num = args[1]; //喷头序号
#}
#DECL_COMMAND(command_temp_set, "temp_set value=%u num=%u");

