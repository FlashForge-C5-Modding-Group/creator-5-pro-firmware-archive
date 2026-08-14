# Printer eddy fpadd
#
# Copyright (C) 2016-2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
from . import output_pin

class FF_eddy:
    def __init__(self, config):
        # Register commands
        self.printer = config.get_printer()
        gcode = config.get_printer().lookup_object('gcode')

        gcode.register_command(
            'GET_BASIC_PARAM', self.cmd_GET_BASIC_PARAM,
            desc=self.cmd_GET_BASIC_PARAM_help)
        gcode.register_command(
            'REMOVE_PEEL', self.cmd_REMOVE_PEEL,
            desc=self.cmd_REMOVE_PEEL_help)
        self.eboard = self.printer.lookup_object('mcu eboard')
        self.levelboard = self.printer.lookup_object('mcu levelboard')

        self.eboard.register_config_callback(self.build_config)
        #start end
    def build_config(self):
        # basic data
        self.get_basic_param_eboard_cmd = self.eboard.lookup_query_command(
            "get_basic_param num=%u",
            "param_value value=%u reserve=%u")

        self.get_basic_param_levelboard_cmd = self.levelboard.lookup_query_command(
            "get_basic_param num=%u",
            "param_value value=%u reserve=%u")
        # peel data
        self.peel_eboard_cmd = self.eboard.lookup_query_command(
            "remove_peel action=%u",
            "peel_data value=%i")
        self.peel_levelboard_cmd = self.levelboard.lookup_query_command(
            "remove_peel action=%u",
            "peel_data value=%i")
    cmd_GET_BASIC_PARAM_help = "Get A Eddy Param"
    def cmd_GET_BASIC_PARAM(self, gcmd):
        num = gcmd.get_int('NUM', 0)
        result_eboard = self.get_basic_param_eboard_cmd.send([num])
        result_levelboard = self.get_basic_param_levelboard_cmd.send([num])
        msg = "Value:[eboard_v=%d,eboard_diff=%d,levelboard_v=%d,levelboard_diff=%d]" % (result_eboard["value"], result_eboard["reserve"] , result_levelboard["value"], result_levelboard["reserve"])
        logging.warning("[FP_GET_BASIC_PARAM],MSG[%s]", msg)
        # gcmd.respond_info("Value:[eboard_v=%d,eboard_diff=%d,levelboard_v=%d,levelboard_diff=%d]" 
        #                            % (result_eboard["value"], result_eboard["reserve"] , result_levelboard["value"], result_levelboard["reserve"]))
    cmd_REMOVE_PEEL_help = "Remove peel and get a data"
    def cmd_REMOVE_PEEL(self, gcmd):
        action = 0
        peel_eboard = self.peel_eboard_cmd.send([action])
        peel_levelboard = self.peel_levelboard_cmd.send([action])

        gcmd.respond_info("Result is eboard_peel_data=%d,levelboard_peel_data=%d"
                                    % (peel_eboard["value"], peel_levelboard["value"]))
def load_config(config):
    return FF_eddy(config)
