import logging
import pins
from . import manual_probe


HINT_TIMEOUT = """
If the toolhead did not move far enough to trigger, then
consider increase the x_offset or y_offset value so the toolhead
can travel further.
"""


# Endstop wrapper that enables TmcHome specific features
class TmcHomeEndstopWrapper:
    def __init__(self, config):
        self.printer = config.get_printer()
        #self.position_endstop = config.getfloat('offset')
        # Create an "endstop" object to handle the probe pin
        #ppins = self.printer.lookup_object('pins')
        #self.mcu_endstop = ppins.setup_pin('endstop', config.get('pin'))
        #self.printer.register_event_handler('klippy:mcu_identify',
        #                                    self._handle_mcu_identify)
        # Wrappers
        #self.get_mcu = self.mcu_endstop.get_mcu
        #self.add_stepper = self.mcu_endstop.add_stepper
        #self.get_steppers = self.mcu_endstop.get_steppers
        #self.home_start = self.mcu_endstop.home_start
        #self.home_wait = self.mcu_endstop.home_wait
        #self.query_endstop = self.mcu_endstop.query_endstop
        # multi probes state
        self.multi = 'OFF'
    def _handle_mcu_identify(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis('x'):
                #self.add_stepper(stepper)
                return
    def tmc_home_move(self, pos, speed, num):
        phoming = self.printer.lookup_object('homing')
        return phoming.probing_move_xy(self, pos, speed, num)
    def get_position_endstop(self):
        #return self.x_endstop
        return


class TmcHomeCy:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.stepper_name = config.get_name().split()[-1]
        print(self.stepper_name)
        self.mcu_probe = TmcHomeEndstopWrapper(config)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('TMCHOME_X_CY', self.cmd_TMCHOME_X_CY, desc=self.cmd_TMCHOMECY_help)
        gcode.register_command('TMCHOME_Y_CY', self.cmd_TMCHOME_Y_CY, desc=self.cmd_TMCHOMECY_help)

        self.speed = config.getfloat('speed', 5.0, above=0.)
        self.x_offset = config.getfloat('x_offset', 0.)
        self.y_offset = config.getfloat('y_offset', 0.)
    def _probe(self, speed, num):
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        if num == 0:
            pos[0] = self.x_offset
        elif num == 1:
            pos[1] = self.y_offset
        else:
            return

        try:
            epos = self.mcu_probe.tmc_home_move(pos, speed, num)
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            raise self.printer.command_error(reason)
        # Allow axis_twist_compensation to update results
        self.printer.send_event("probe:update_results", epos)
        # Report results
        gcode = self.printer.lookup_object('gcode')
        gcode.respond_info("tmchome endstop at [%.3f,%.3f]" % (epos[0], epos[1]))
        return epos[:3]
    def run_probe(self, gcmd, num):
        toolhead = self.printer.lookup_object('toolhead')
        #probexy = toolhead.get_position()[:2]
        positions = []
        # Probe position
        pos = self._probe(self.speed, num)
        positions.append(pos)
        return pos
    cmd_TMCHOMECY_help = "measure XY position mm value"
    def cmd_TMCHOME_X_CY(self, gcmd):
        pos = self.run_probe(gcmd, 0)
        gcmd.respond_info("Result is x=%.6f" % (pos[0],))
        self.last_z_result = pos[2]
    def cmd_TMCHOME_Y_CY(self, gcmd):
        pos = self.run_probe(gcmd, 1)
        gcmd.respond_info("Result is y=%.6f" % (pos[1],))
        self.last_z_result = pos[2]

def load_config(config):
    return TmcHomeCy(config)

