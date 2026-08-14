# Support fans that are controlled by gcode
#
# Copyright (C) 2016-2020  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import fan
MUTE_SPEED = 0.5
MUTE_MODE_ENABLE  = 0xFFFF
MUTE_MODE_DISABLE = 0xEEEE
class PrinterFanGeneric:
    cmd_SET_FAN_SPEED_help = "Sets the speed of a fan"
    def __init__(self, config):
        self.printer = config.get_printer()
        self.fan = fan.Fan(config, default_shutdown_speed=0.)
        self.fan_name = config.get_name().split()[-1]

        gcode = self.printer.lookup_object("gcode")
        gcode.register_mux_command("SET_FAN_SPEED", "FAN",
                                   self.fan_name,
                                   self.cmd_SET_FAN_SPEED,
                                   desc=self.cmd_SET_FAN_SPEED_help)
        self.user_speed = 0
        self.mute_mode = False
    def get_status(self, eventtime):
        return self.fan.get_status(eventtime)
    def cmd_SET_FAN_SPEED(self, gcmd):
        speed = gcmd.get_float('SPEED', 0.)
        if self.fan_name == 'fanM106':
            if (speed != MUTE_MODE_ENABLE) and (speed != MUTE_MODE_DISABLE):
                self.user_speed = speed
            if speed == MUTE_MODE_ENABLE:
                self.mute_mode = True
                speed = min(self.user_speed, MUTE_SPEED)
                gcmd.respond_info("MUTE_MODE_ENABLE = True, speed: %f" % (speed,))
            elif speed == MUTE_MODE_DISABLE:
                self.mute_mode = False
                speed = self.user_speed
                gcmd.respond_info("MUTE_MODE_ENABLE = False, speed: %f" % (speed,))
            else:
                if self.mute_mode:
                    speed = min(speed, MUTE_SPEED)
        self.fan.set_speed_from_command(speed)

def load_config_prefix(config):
    return PrinterFanGeneric(config)
