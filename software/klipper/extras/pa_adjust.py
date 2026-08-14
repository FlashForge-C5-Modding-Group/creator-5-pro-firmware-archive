# Printer cooling fan
#
# Copyright (C) 2016-2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import pulse_counter, output_pin

class PrinterPA:
    def __init__(self, config):
        # Register commands
        self.printer = config.get_printer()
        gcode = config.get_printer().lookup_object('gcode')
        gcode.register_command("PA_GET", self.cmd_PA_GET)
        gcode.register_command("PA_ACTION", self.cmd_PA_ACTION)

        self.mcu = self.printer.lookup_object('mcu eboard')
        self.mcu.register_config_callback(self.build_config)
        self._pa_value_get_cmd = None
        self._pa_action_cmd = None
        #start end
    def build_config(self):
        self._pa_value_get_cmd = self.mcu.lookup_query_command(
            "get_emcu_pa_value",
            "pa_value value=%u")

        self._pa_action_cmd = self.mcu.lookup_command(
            "pa_action action=%u pc=%u")
    def cmd_PA_ACTION(self, gcmd):
        #0:PA_close  1:PA_start
        action = gcmd.get_int('ACTION', 0)
        #材料
        pc = gcmd.get_int('PC', 0)
        self._pa_action_cmd.send([action, pc])

    def cmd_PA_GET(self, gcmd):
        # Get PA value
        result = self._pa_value_get_cmd.send()
        gcmd.respond_info("Result is value=%s" % (result["value"],))
def load_config(config):
    return PrinterPA(config)
