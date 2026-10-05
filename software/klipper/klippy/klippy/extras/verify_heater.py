# Heater/sensor verification code
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

HINT_THERMAL = """
See the 'verify_heater' section in docs/Config_Reference.md
for the parameters that control this check.
"""

class HeaterCheck:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
        self.printer.register_event_handler("klippy:shutdown",
                                            self.handle_shutdown)
        self.heater_name = config.get_name().split()[1]
        self.heater = None
        self.hysteresis = config.getfloat('hysteresis', 5., minval=0.)
        self.max_error = config.getfloat('max_error', 120., minval=0.)
        self.heating_gain = config.getfloat('heating_gain', 2., above=0.)
        # fp add: max allowed temperature when heater is idle (target <= 0).
        # Detects "ghost heating" of a broken/uncommanded heater (e.g. a
        # faulty MOSFET or shorted heater causing it to heat up on its own).
        self.idle_max_temp = config.getfloat('idle_max_temp', 80., minval=0.)
        # fp add: absolute temperature hard limit for IDLE heaters only. A
        # heater that was NOT commanded to heat must never reach this high.
        self.max_abs_temp = config.getfloat('max_abs_temp', 320., minval=0.)
        # fp add: how long the idle temperature must keep rising (above the
        # idle limit) before a "ghost heating" fault is reported.
        self.idle_rise_time = 5.
        # fp add: minimum per-sample temperature increase (degC) required to
        # consider the idle heater as "rising". Filters out thermistor noise
        # during natural cool-down so a small fluctuation is not mistaken for
        # ghost heating (e.g. right after cancelling a print).
        self.idle_rise_gain = 1.0
        # fp add: grace period (seconds) after the heater stops being commanded
        # (target goes from >0 to 0). During this period the residual thermal
        # inertia keeps raising the temperature even though heating is off, so
        # idle "ghost heating" detection is suspended.
        self.idle_grace_time = 30.
        default_gain_time = 20.
        self.check_gain_time = config.getfloat(
            'check_gain_time', default_gain_time, minval=1.)
        
        self.check_gain_time = 20.
        if self.heater_name == 'heater_bed':
            self.hysteresis = 10.
            self.check_gain_time = 100.
            self.max_error = 120.
            self.heating_gain = 5.
            self.idle_rise_time = 100.
        elif self.heater_name == 'chamber_heater':
            self.hysteresis = 5.
            self.check_gain_time = 900.
            self.max_error = 100.
            self.heating_gain = 5.
            self.idle_rise_time = 100.
        else:
            self.hysteresis = 4.
            self.check_gain_time = 20.
            self.max_error = 120.
            self.heating_gain = 5.
            self.idle_rise_time = 5.
        
        self.approaching_target = self.starting_approach = False
        self.last_target = self.goal_temp = self.error = 0.
        self.goal_systime = self.printer.get_reactor().NEVER
        # fp add: track idle "ghost heating" (temperature rising while idle)
        self.idle_over_temp_time = 0.
        self.idle_last_temp = None
        self.idle_last_time = 0.
        # fp add: grace period end time after heater stops being commanded
        self.idle_grace_until = 0.
        self.check_timer = None
    def handle_connect(self):
        if self.printer.get_start_args().get('debugoutput') is not None:
            # Disable verify_heater if outputting to a debug file
            return
        pheaters = self.printer.lookup_object('heaters')
        self.heater = pheaters.lookup_heater(self.heater_name)
        logging.info("Starting heater checks for %s", self.heater_name)
        reactor = self.printer.get_reactor()
        self.check_timer = reactor.register_timer(self.check_event, reactor.NOW)
    def handle_shutdown(self):
        if self.check_timer is not None:
            reactor = self.printer.get_reactor()
            reactor.update_timer(self.check_timer, reactor.NEVER)
    def check_event(self, eventtime):
        temp, target = self.heater.get_temp(eventtime)
        # fp add: detect "ghost heating" when the heater is idle (target <= 0).
        # A broken heater (shorted heater / faulty MOSFET) can heat up on its
        # own even though no heating was commanded. We detect this by watching
        # the temperature TREND while idle: natural cool-down (residual heat
        # after a print / after restart) makes temp FALL, whereas a faulty
        # heater makes temp RISE. Only a sustained RISE above idle_max_temp is
        # treated as a fault, so residual heat is never mistaken for a fault.
        if target <= 0.:
            self.approaching_target = self.starting_approach = False
            # fp add: if we just stopped commanding heat, the residual thermal
            # inertia keeps raising the temperature for a while (e.g. right
            # after cancelling a print). Skip idle ghost-heating detection
            # during this grace period.
            if eventtime < self.idle_grace_until:
                self.idle_over_temp_time = 0.
                self.idle_last_temp = temp
                self.idle_last_time = eventtime
                self.last_target = target
                return eventtime + 1.
            # fp add: detect "ghost heating" when idle. Two levels:
            #  1) absolute limit (max_abs_temp): the heater was never supposed
            #     to be this hot while idle. But a temp overshoot just after
            #     cancelling preheat (e.g. target was 320, overshoot to 325,
            #     then M104 S0) is a NORMAL cool-down, so we must NOT fault
            #     while the temperature is FALLING. Only fault if it stays
            #     above the limit without cooling down.
            #  2) idle limit (idle_max_temp): a rising temperature while idle
            #     means the heater is heating on its own -> fault.
            over_abs = temp > self.max_abs_temp
            over_idle = temp > self.idle_max_temp
            # Only treat the heater as "rising" if it increased by more than
            # idle_rise_gain since the last sample. This filters out small
            # thermistor fluctuations during cool-down (e.g. 95.4 -> 95.6)
            # which would otherwise be misread as ghost heating.
            rising = (self.idle_last_temp is not None
                      and temp - self.idle_last_temp > self.idle_rise_gain)
            if over_abs and not rising:
                # Above absolute limit but cooling down (overshoot residual):
                # do NOT fault, just wait for it to drop.
                self.idle_over_temp_time = 0.
            elif (over_abs and rising) or (over_idle and rising):
                # Above a limit AND still rising - genuine ghost heating
                if self.idle_over_temp_time == 0.:
                    self.idle_over_temp_time = eventtime
                    logging.warning(
                        "Heater %s temperature rising while idle: %.3f -> %.3f",
                        self.heater_name, self.idle_last_temp, temp)
                elif eventtime - self.idle_over_temp_time >= self.idle_rise_time:
                    msg = ("Heater %s is heating while idle (temp %.3f)"
                           % (self.heater_name, temp))
                    return self.heater_fault(msg)
            else:
                # Cooling down or below limits - reset the rising timer
                self.idle_over_temp_time = 0.
            self.idle_last_temp = temp
            self.idle_last_time = eventtime
            self.last_target = target
            return eventtime + 1.
        # fp add: clear idle trend state once heating is commanded, and extend
        # the idle grace period so the residual thermal inertia after the
        # heater is later turned off does not trip the idle ghost-heating check.
        self.idle_last_temp = None
        self.idle_over_temp_time = 0.
        self.idle_grace_until = eventtime + self.idle_grace_time
        if temp >= target - self.hysteresis:
            # Temperature near target - reset checks
            if self.approaching_target and target:
                logging.info("Heater %s within range of %.3f",
                             self.heater_name, target)
            self.approaching_target = self.starting_approach = False
            if temp <= target + self.hysteresis:
                self.error = 0.
            self.last_target = target
            return eventtime + 1.
        self.error += (target - self.hysteresis) - temp
        if not self.approaching_target:
            if target != self.last_target:
                # Target changed - reset checks
                logging.info("Heater %s approaching new target of %.3f",
                             self.heater_name, target)
                self.approaching_target = self.starting_approach = True
                self.goal_temp = temp + self.heating_gain
                self.goal_systime = eventtime + self.check_gain_time
            elif self.error >= self.max_error:
                # Failure due to inability to maintain target temperature
                return self.heater_fault()
        elif temp >= self.goal_temp:
            # Temperature approaching target - reset checks
            self.starting_approach = False
            self.error = 0.
            self.goal_temp = temp + self.heating_gain
            self.goal_systime = eventtime + self.check_gain_time
        elif eventtime >= self.goal_systime:
            # Temperature is no longer approaching target
            self.approaching_target = False
            logging.info("Heater %s no longer approaching target %.3f",
                         self.heater_name, target)
        elif self.starting_approach:
            self.goal_temp = min(self.goal_temp, temp + self.heating_gain)
        self.last_target = target
        return eventtime + 1.
    def heater_fault(self, msg=None):
        if msg is None:
            msg = "Heater %s not heating at expected rate" % (self.heater_name,)
        self.heater.error_info = msg
        logging.error(msg)
        self.printer.invoke_shutdown(msg + HINT_THERMAL)
        return self.printer.get_reactor().NEVER

def load_config_prefix(config):
    return HeaterCheck(config)
