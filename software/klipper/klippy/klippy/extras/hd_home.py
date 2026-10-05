import logging
import pins
from . import manual_probe


HINT_TIMEOUT = """
If the toolhead did not move far enough to trigger, then
consider increase the x_offset or y_offset value so the toolhead
can travel further.
"""


# Endstop wrapper that enables TmcHome specific features
class HdHomeEndstopWrapper:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.stepper_name = config.get_name().split()[-1]

        self.position_endstop = config.getfloat('offset')
        # Create an "endstop" object to handle the probe
        ppins = self.printer.lookup_object('pins')
        self.mcu_endstop = ppins.setup_pin('endstop', config.get('pin'))
        self.printer.register_event_handler('klippy:mcu_identify',
                                            self._handle_mcu_identify)
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self.mcu_endstop.get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop
        # multi probes state
        self.multi = 'OFF'
    def _handle_mcu_identify(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis('z') and self.stepper_name == "Z":
                self.add_stepper(stepper)
            if stepper.is_active_axis('x') and self.stepper_name == "X":
                self.add_stepper(stepper)
            if stepper.is_active_axis('y') and self.stepper_name == "Y":
                self.add_stepper(stepper)
    def hd_home_move(self, pos, speed):
        phoming = self.printer.lookup_object('homing')
        return phoming.probing_move(self, pos, speed)
    def get_position_endstop(self):
        return self.x_endstop


class HdlmtHome:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.stepper_name = config.get_name().split()[-1]
        print(self.stepper_name)
        self.mcu_probe = HdHomeEndstopWrapper(config)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command("HDHOME", "AXES",
                                   self.stepper_name,
                                   self.cmd_HDHOME,
                                   desc=self.cmd_HDHOME_help)

        self.speed = config.getfloat('speed', 5.0, above=0.)
        self.position_offset = config.getfloat('offset', 0.)
    def _probe(self, speed):
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        #X移动100mm
        if self.stepper_name == "X":
            pos[0] = self.position_offset
        elif self.stepper_name == "Y":
            pos[1] = self.position_offset
        elif self.stepper_name == "Z":
            pos[2] = self.position_offset
        else:
            return

        try:
            epos = self.mcu_probe.hd_home_move(pos, speed)
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            raise self.printer.command_error(reason)
        # Allow axis_twist_compensation to update results
        self.printer.send_event("probe:update_results", epos)
        # Report results
        gcode = self.printer.lookup_object('gcode')
        gcode.respond_info("hdhome endstop at [%.3f,%.3f,%.3f]" % (epos[0], epos[1], epos[2]))
        return epos[:3]
    def run_probe(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        #probexy = toolhead.get_position()[:2]
        positions = []
        # Probe position
        pos = self._probe(self.speed)
        positions.append(pos)
        return pos
    cmd_HDHOME_help = "measure XYZ position mm value use hd limit"
    def cmd_HDHOME(self, gcmd):
        self.position_offset = gcmd.get_float('TARGET', self.position_offset)
        pos = self.run_probe(gcmd)
        if self.stepper_name == "X":
            gcmd.respond_info("Result is X=%.6f" % (pos[0],))
        elif self.stepper_name == "Y":
            gcmd.respond_info("Result is Y=%.6f" % (pos[1],))
        elif self.stepper_name == "Z":
            gcmd.respond_info("Result is Z=%.6f" % (pos[2],))
        #self.last_z_result = pos[2]

def load_config_prefix(config):
    return HdlmtHome(config)

