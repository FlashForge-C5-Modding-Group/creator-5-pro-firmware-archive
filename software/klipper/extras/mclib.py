# GD32 mcu motor control library configuration
#
# Copyright (C) 2024  Dongzhi Yu <dongzhi.yu@gigadevice.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import stepper

######################################################################
# MCLIB printer object
######################################################################

MAX_CURRENT = 4.0
steps = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6, 128: 7, 256: 8}
stepper_id = {'stepper_x':0, 'stepper_y':1, 'stepper_z':2, 'extruder':3}

class MCLIB:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.stepper_name = " ".join(config.get_name().split()[1:])
        self.name = config.get_name().split()[-1]
        if not config.has_section(self.stepper_name):
            raise config.error(
                "Could not find config section '[%s]' required by MCLIB"
                % (self.stepper_name,))
        self.stepper = None
        # Get config parameters
        sconfig = config.getsection(self.stepper_name)

        self.microstep = sconfig.getchoice('microsteps', steps)
        self.motor_rs  = int(config.getfloat('motor_rs', above=0.) * 1000)
        self.motor_ls  = int(config.getfloat('motor_ls', above=0.) * 1000000)
        self.motor_km  = int(config.getfloat('motor_km', above=0.) * 1000000)
        self.bus_voltage  = int(config.getfloat('bus_voltage', above=0.)* 1000)
        run_current = config.getfloat('run_current', 1., minval=0., maxval=4.)
        self.run_current = int(run_current * 1000)
        self.hold_current = int(config.getfloat('hold_current', run_current, minval=0., maxval=run_current)* 1000)
        self.interpolate = config.getboolean('interpolate', True)
        self.stall_threshold = int(config.getfloat('stall_threshold', self.bus_voltage, above=0.)* 1000)
        self.td1_amp = int(config.getfloat('td1_amp', 0., minval=0., maxval=run_current)* 1000)
        self.td1_phase1 = int(config.getfloat('td1_phase1', 0.)* 1000)
        self.td1_phase2 = int(config.getfloat('td1_phase2', 0.)* 1000)
        self.td2_amp = int(config.getfloat('td2_amp', 0., minval=0., maxval=run_current)* 1000)
        self.td2_phase1 = int(config.getfloat('td2_phase1', 0.)* 1000)
        self.td2_phase2 = int(config.getfloat('td2_phase2', 0.)* 1000)
        self.td4_amp = int(config.getfloat('td4_amp', 0., minval=0., maxval=run_current)* 1000)
        self.td4_phase1 = int(config.getfloat('td4_phase1', 0.)* 1000)
        self.td4_phase2 = int(config.getfloat('td4_phase2', 0.)* 1000)

        self.printer.register_event_handler("klippy:mcu_identify",
                                            self._handle_mcu_identify)
        self.set_current_cmd = None
        gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command("MCLIB_SET_CURRENT", "STEPPER", self.name,
                                   self.cmd_MCLIB_SET_CURRENT,
                                   desc=self.cmd_MCLIB_SET_CURRENT_help)

        self.set_resonance_damp_cmd = None
        if self.name != 'extruder':
            gcode.register_mux_command("MCLIB_SET_RESONANCE_DAMP", "STEPPER", self.name,
                                   self.cmd_MCLIB_SET_RESONANCE_DAMP,
                                   desc=self.cmd_MCLIB_SET_RESONANCE_DAMP_help)

    def _handle_mcu_identify(self):
        # Lookup stepper object
        force_move = self.printer.lookup_object("force_move")
        self.stepper = force_move.lookup_stepper(self.stepper_name)
        self.mcu = self.stepper.get_mcu()
        self.mcu.register_config_callback(self._build_config)

    def _build_config(self):
        self.oid = self.mcu.create_oid()

        self.mcu.add_config_cmd("config_mclib oid=%d stepper=%s rs=%u ls=%u km=%u" % (
            self.oid, self.stepper_name, self.motor_rs, self.motor_ls, self.motor_km))

        self.mcu.add_config_cmd("mclib_config_microstep oid=%d interpolate=%d mstep=%u" % (
            self.oid, self.interpolate, self.microstep))
            
        self.mcu.add_config_cmd("mclib_set_current oid=%d run_current=%u hold_current=%u"% (
            self.oid, self.run_current, self.hold_current))
            
        self.mcu.add_config_cmd("mclib_config_stalldetect oid=%d stallthrs=%u" % (
            self.oid, self.stall_threshold))

        if self.name != 'extruder':
            self.mcu.add_config_cmd("mclib_set_resonance_damp oid=%d tdx=1 amp=%u phase1=%u phase2=%u"% (
                self.oid, self.td1_amp, self.td1_phase1, self.td1_phase2))
            self.mcu.add_config_cmd("mclib_set_resonance_damp oid=%d tdx=2 amp=%u phase1=%u phase2=%u"% (
                self.oid, self.td2_amp, self.td2_phase1, self.td2_phase2))
            self.mcu.add_config_cmd("mclib_set_resonance_damp oid=%d tdx=4 amp=%u phase1=%u phase2=%u"% (
                self.oid, self.td4_amp, self.td4_phase1, self.td4_phase2))

        self.set_current_cmd = self.mcu.lookup_command(
            "mclib_set_current oid=%c run_current=%u hold_current=%u")

        if self.name != 'extruder':
            self.set_resonance_damp_cmd = self.mcu.lookup_command(
                "mclib_set_resonance_damp oid=%c tdx=%c amp=%u phase1=%u phase2=%u")

    cmd_MCLIB_SET_CURRENT_help = "Sets the current of stepper in mclib "
    def cmd_MCLIB_SET_CURRENT(self, gcmd):
        run_current = int(gcmd.get_float('CURRENT', None, minval=0., maxval=MAX_CURRENT)* 1000)
        hold_current = int(gcmd.get_float('HOLDCURRENT', None, above=0., maxval=run_current)* 1000)

        gcmd.respond_info("set run_current=%u hold_current=%u" % (run_current, hold_current))

        if self.set_current_cmd is None:
            # Send setup message via mcu initialization
            self.mcu.add_config_cmd("mclib_set_current oid=%d run_current=%u hold_current=%u"
                                    % (self.oid, run_current, hold_current))
            return
        self.set_current_cmd.send([self.oid, run_current, hold_current])

    cmd_MCLIB_SET_RESONANCE_DAMP_help = "Sets the stepper resonance damp paramters in mclib"
    def cmd_MCLIB_SET_RESONANCE_DAMP(self, gcmd):
        if self.name == 'extruder':
            raise gcmd.error("Extruder don't support resonance damping")
        tdx = gcmd.get_int('TDX', 1, minval=1, maxval=4) # 1, 2, 4
        if tdx not in [1, 2, 4]:
            raise gcmd.error("Invalid tdx, only 1, 2 or 4 supported!")
        amp = int(gcmd.get_float('AMP', None, minval=0., maxval=MAX_CURRENT)* 1000)
        phase1 = int(gcmd.get_float('PHASE1', None)* 1000)
        phase2 = int(gcmd.get_float('PHASE2', None)* 1000)

        if self.set_resonance_damp_cmd is None:
            # Send setup message via mcu initialization
            self.mcu.add_config_cmd("mclib_set_resonance_damp oid=%d td=1 amp=%u phase1=%u phase2=%u"
                                    % (self.oid, self.td1_amp, self.td1_phase1, self.td1_phase2))
            self.mcu.add_config_cmd("mclib_set_resonance_damp oid=%d td=2 amp=%u phase1=%u phase2=%u"
                                    % (self.oid, self.td2_amp, self.td2_phase1, self.td2_phase2))
            self.mcu.add_config_cmd("mclib_set_resonance_damp oid=%d td=4 amp=%u phase1=%u phase2=%u"
                                    % (self.oid, self.td4_amp, self.td4_phase1, self.td4_phase2))
            return
        self.set_resonance_damp_cmd.send([self.oid, tdx, amp, phase1, phase2])

def load_config_prefix(config):
    return MCLIB(config)