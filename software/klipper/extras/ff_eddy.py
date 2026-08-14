# Printer eddy fpadd
#
# Copyright (C) 2016-2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
from . import output_pin


class FF_eddy:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.name = config.get_name().split()[-1]
        self.mcu_name = config.get('mcu')
        self.trigger_threshold = config.getint(
            'trigger_threshold', -15, minval=-200, maxval=200)
        self.mcu = self.printer.lookup_object(self.mcu_name)

        self.value = 0
        self.diff = 0
        self.last_update_time = 0.

        gcode = self.printer.lookup_object('gcode')
        suffix = self.name.upper()
        gcode.register_command(
            'GET_BASIC_PARAM_%s' % (suffix,), self.cmd_GET_BASIC_PARAM,
            desc=self.cmd_GET_BASIC_PARAM_help)
        gcode.register_command(
            'REMOVE_PEEL_%s' % (suffix,), self.cmd_REMOVE_PEEL,
            desc=self.cmd_REMOVE_PEEL_help)
        gcode.register_command(
            'SET_TRIGGER_THRESHOLD_%s' % (suffix,),
            self.cmd_SET_TRIGGER_THRESHOLD,
            desc=self.cmd_SET_TRIGGER_THRESHOLD_help)

        self.mcu.register_config_callback(self.build_config)

    def build_config(self):
        self.get_basic_param_cmd = self.mcu.lookup_query_command(
            "get_basic_param num=%u",
            "param_value value=%u reserve=%u")
        self.peel_cmd = self.mcu.lookup_query_command(
            "remove_peel action=%u",
            "peel_data value=%i")
        self.set_trigger_threshold_cmd = self.mcu.lookup_query_command(
            "set_trigger_threshold threshold=%i",
            "trigger_threshold threshold=%i")
        self.set_trigger_threshold_cmd.send([self.trigger_threshold])

    cmd_GET_BASIC_PARAM_help = "Get eddy basic param"
    def cmd_GET_BASIC_PARAM(self, gcmd):
        num = gcmd.get_int('NUM', 0)
        result = self.get_basic_param_cmd.send([num])
        gcmd.respond_info(
            "%s result: value=%d,diff=%d"
            % (self.name, result['value'], result['reserve']))

    cmd_REMOVE_PEEL_help = "Remove peel and get a data"
    def cmd_REMOVE_PEEL(self, gcmd):
        action = gcmd.get_int('ACTION', 0)
        peel_data = self.peel_cmd.send([action])
        msg = "Value:[name=%s,value=%d,reserve=%d]" % (self.name, result['value'], result['reserve'])
        logging.warning("[GET_BASIC_PARAM],MSG[%s]", msg)
        #gcmd.respond_info(
        #    "%s peel_data=%d" % (self.name, peel_data['value']))

    cmd_SET_TRIGGER_THRESHOLD_help = "Set eddy trigger threshold"
    def cmd_SET_TRIGGER_THRESHOLD(self, gcmd):
        threshold = gcmd.get_int('THRESHOLD', self.trigger_threshold,
                                 minval=-200, maxval=200)
        self.set_trigger_threshold_cmd.send([threshold])
        self.trigger_threshold = threshold
        gcmd.respond_info(
            "%s trigger_threshold=%d" % (self.name, threshold))


def load_config_prefix(config):
    return FF_eddy(config)
