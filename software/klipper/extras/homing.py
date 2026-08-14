# Helper code for implementing homing operations
#
# Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math,time

HOMING_START_DELAY = 0.001
ENDSTOP_SAMPLE_TIME = .000015
ENDSTOP_SAMPLE_COUNT = 4
HOMING_RETRY_DELAY = 0.20

# Return a completion that completes when all completions in a list complete
def multi_complete(printer, completions):
    if len(completions) == 1:
        return completions[0]
    # Build completion that waits for all completions
    reactor = printer.get_reactor()
    cp = reactor.register_callback(lambda e: [c.wait() for c in completions])
    # If any completion indicates an error, then exit main completion early
    for c in completions:
        reactor.register_callback(
            lambda e, c=c: cp.complete(1) if c.wait() else 0)
    return cp

# Tracking of stepper positions during a homing/probing move
class StepperPosition:
    def __init__(self, stepper, endstop_name):
        self.stepper = stepper
        self.endstop_name = endstop_name
        self.stepper_name = stepper.get_name()
        self.start_pos = stepper.get_mcu_position()
        self.halt_pos = self.trig_pos = None
    def note_home_end(self, trigger_time):
        self.halt_pos = self.stepper.get_mcu_position()
        self.trig_pos = self.stepper.get_past_mcu_position(trigger_time)

# Implementation of homing/probing moves
class HomingMove:
    def __init__(self, printer, endstops, toolhead=None):
        self.printer = printer
        self.endstops = endstops
        if toolhead is None:
            toolhead = printer.lookup_object('toolhead')
        self.toolhead = toolhead
        self.stepper_positions = []
    def get_mcu_endstops(self):
        return [es for es, name in self.endstops]
    def _calc_endstop_rate(self, mcu_endstop, movepos, speed):
        startpos = self.toolhead.get_position()
        axes_d = [mp - sp for mp, sp in zip(movepos, startpos)]
        move_d = math.sqrt(sum([d*d for d in axes_d[:3]]))
        move_t = move_d / speed
        max_steps = max([(abs(s.calc_position_from_coord(startpos)
                              - s.calc_position_from_coord(movepos))
                          / s.get_step_dist())
                         for s in mcu_endstop.get_steppers()])
        if max_steps <= 0.:
            return .001
        return move_t / max_steps
    def calc_toolhead_pos(self, kin_spos, offsets):
        kin_spos = dict(kin_spos)
        kin = self.toolhead.get_kinematics()
        for stepper in kin.get_steppers():
            sname = stepper.get_name()
            kin_spos[sname] += offsets.get(sname, 0) * stepper.get_step_dist()
        thpos = self.toolhead.get_position()
        return list(kin.calc_position(kin_spos))[:3] + thpos[3:]
    def homing_move(self, movepos, speed, probe_pos=False,
                    triggered=True, check_triggered=True, safe_z=False):
        # Notify start of homing/probing move
        self.printer.send_event("homing:homing_move_begin", self)
        # Note start location
        self.toolhead.flush_step_generation()
        kin = self.toolhead.get_kinematics()
        kin_spos = {s.get_name(): s.get_commanded_position()
                    for s in kin.get_steppers()}
        self.stepper_positions = [ StepperPosition(s, name)
                                   for es, name in self.endstops
                                   for s in es.get_steppers() ]
        # Start endstop checking
        print_time = self.toolhead.get_last_move_time()
        endstop_triggers = []
        for mcu_endstop, name in self.endstops:
            rest_time = self._calc_endstop_rate(mcu_endstop, movepos, speed)
            wait = mcu_endstop.home_start(print_time, ENDSTOP_SAMPLE_TIME,
                                          ENDSTOP_SAMPLE_COUNT, rest_time,
                                          triggered=triggered)
            endstop_triggers.append(wait)
        all_endstop_trigger = multi_complete(self.printer, endstop_triggers)
        self.toolhead.dwell(HOMING_START_DELAY)
        # Issue move
        error = None
        try:
            self.toolhead.drip_move(movepos, speed, all_endstop_trigger)
        except self.printer.command_error as e:
            index = {'x': 0, 'y': 1, 'z': 2, 'probe': 3}.get(name, 255)
            error = '{"coded": "0003-0528-%4d-0002", "msg":"%s", "action": "cancel"}' % (index, "Error during homing move %s: %s" % (name, str(e),))
        # Wait for endstops to trigger
        trigger_times = {}
        move_end_print_time = self.toolhead.get_last_move_time()
        for mcu_endstop, name in self.endstops:
            try:
                trigger_time = mcu_endstop.home_wait(move_end_print_time)
            except self.printer.command_error as e:
                if error is None:
                    if safe_z:
                        error = "Warning during homing %s: %s" % (name, str(e),)
                    else:
                        index = {'x': 0, 'y': 1, 'z': 2, 'probe': 3}.get(name, 255)
                        error = '{"coded": "0003-0528-%4d-0003", "msg":"%s", "action": "cancel"}' % (index, "Error during homing %s: %s" % (name, str(e),))
                continue
            if trigger_time > 0.:
                trigger_times[name] = trigger_time
            elif check_triggered and error is None:
                if safe_z:
                    logging.warning("safe_z_001 No trigger on %s after full movement", name)
                else:
                    index = {'x': 0, 'y': 1, 'z': 2, 'probe': 3}.get(name, 255)
                    error = '{"coded": "0003-0528-%4d-0004", "msg":"%s", "action": "cancel"}' % (index, "No trigger on %s after full movement" % (name,))
        # Determine stepper halt positions
        self.toolhead.flush_step_generation()
        for sp in self.stepper_positions:
            tt = trigger_times.get(sp.endstop_name, move_end_print_time)
            sp.note_home_end(tt)
        if probe_pos:
            halt_steps = {sp.stepper_name: sp.halt_pos - sp.start_pos
                          for sp in self.stepper_positions}
            trig_steps = {sp.stepper_name: sp.trig_pos - sp.start_pos
                          for sp in self.stepper_positions}
            haltpos = trigpos = self.calc_toolhead_pos(kin_spos, trig_steps)
            if trig_steps != halt_steps:
                haltpos = self.calc_toolhead_pos(kin_spos, halt_steps)
        else:
            trig_steps = {sp.stepper_name: sp.trig_pos - sp.start_pos
                          for sp in self.stepper_positions}
            trigpos = self.calc_toolhead_pos(kin_spos, trig_steps)
            
            haltpos = movepos
            #haltpos = trigpos = movepos
            over_steps = {sp.stepper_name: sp.halt_pos - sp.trig_pos
                          for sp in self.stepper_positions}
            if any(over_steps.values()):
                self.toolhead.set_position(movepos)
                halt_kin_spos = {s.get_name(): s.get_commanded_position()
                                 for s in kin.get_steppers()}
                haltpos = self.calc_toolhead_pos(halt_kin_spos, over_steps)
        self.toolhead.set_position(haltpos)
        # Signal homing/probing move complete
        try:
            self.printer.send_event("homing:homing_move_end", self)
        except self.printer.command_error as e:
            if error is None:
                error = str(e)
        if error is not None:
            if not safe_z:
                raise self.printer.command_error(error)
            else:
                # safe_z 模式：记录日志但不抛出异常
                logging.warning("homing_move safe_z suppressed error: %s", error)
        return trigpos
    def check_no_movement(self):
        if self.printer.get_start_args().get('debuginput') is not None:
            return None
        for sp in self.stepper_positions:
            if sp.start_pos == sp.trig_pos:
                return sp.endstop_name
        return None
    def homing_move_small(self, movepos, speed, probe_pos=False,
                triggered=True, check_triggered=True, safe_z=False):
        # Notify start of homing/probing move
        self.printer.send_event("homing:homing_move_begin", self)
        # Note start location
        self.toolhead.flush_step_generation()
        kin = self.toolhead.get_kinematics()
        kin_spos = {s.get_name(): s.get_commanded_position()
                    for s in kin.get_steppers()}
        self.stepper_positions = [ StepperPosition(s, name)
                                   for es, name in self.endstops
                                   for s in es.get_steppers() ]
        # Start endstop checking
        print_time = self.toolhead.get_last_move_time()
        endstop_triggers = []
        for mcu_endstop, name in self.endstops:
            rest_time = self._calc_endstop_rate(mcu_endstop, movepos, speed)
            wait = mcu_endstop.home_start(print_time, ENDSTOP_SAMPLE_TIME,
                                          ENDSTOP_SAMPLE_COUNT, rest_time,
                                          triggered=triggered)
            endstop_triggers.append(wait)
        all_endstop_trigger = multi_complete(self.printer, endstop_triggers)
        self.toolhead.dwell(HOMING_START_DELAY)
        # Issue move
        error = None
        try:
            self.toolhead.drip_move(movepos, speed, all_endstop_trigger)
        except self.printer.command_error as e:
            index = {'x': 0, 'y': 1, 'z': 2, 'probe': 3}.get(name, 255)
            error = '{"small_coded": "0003-0528-%4d-0002", "msg":"%s", "action": "cancel"}' % (index, "Error during homing move %s: %s" % (name, str(e),))
        # Wait for endstops to trigger
        trigger_times = {}
        move_end_print_time = self.toolhead.get_last_move_time()
        for mcu_endstop, name in self.endstops:
            try:
                trigger_time = mcu_endstop.home_wait(move_end_print_time)
            except self.printer.command_error as e:
                if error is None:
                    if safe_z:
                        error = "small_Warning during homing %s: %s" % (name, str(e),)
                    else:
                        index = {'x': 0, 'y': 1, 'z': 2, 'probe': 3}.get(name, 255)
                        error = '{"small_coded": "0003-0528-%4d-0003", "msg":"%s", "action": "cancel"}' % (index, "Error during homing %s: %s" % (name, str(e),))
                continue
            if trigger_time > 0.:
                trigger_times[name] = trigger_time
            elif check_triggered and error is None:
                if safe_z:
                    logging.warning("samll_safe_z_002 No trigger on %s after full movement", name)
                else:
                    index = {'x': 0, 'y': 1, 'z': 2, 'probe': 3}.get(name, 255)
                    error = '{"small_coded": "0003-0528-%4d-0004", "msg":"%s", "action": "cancel"}' % (index, "No trigger on %s after full movement" % (name,))
        # Determine stepper halt positions
        self.toolhead.flush_step_generation()
        for sp in self.stepper_positions:
            tt = trigger_times.get(sp.endstop_name, move_end_print_time)
            sp.note_home_end(tt)
        if probe_pos:
            halt_steps = {sp.stepper_name: sp.halt_pos - sp.start_pos
                          for sp in self.stepper_positions}
            trig_steps = {sp.stepper_name: sp.trig_pos - sp.start_pos
                          for sp in self.stepper_positions}
            haltpos = trigpos = self.calc_toolhead_pos(kin_spos, trig_steps)
            if trig_steps != halt_steps:
                haltpos = self.calc_toolhead_pos(kin_spos, halt_steps)
        else:
            trig_steps = {sp.stepper_name: sp.trig_pos - sp.start_pos
                          for sp in self.stepper_positions}
            trigpos = self.calc_toolhead_pos(kin_spos, trig_steps)
            
            haltpos = movepos
            #haltpos = trigpos = movepos
            over_steps = {sp.stepper_name: sp.halt_pos - sp.trig_pos
                          for sp in self.stepper_positions}
            if any(over_steps.values()):
                self.toolhead.set_position(movepos)
                halt_kin_spos = {s.get_name(): s.get_commanded_position()
                                 for s in kin.get_steppers()}
                haltpos = self.calc_toolhead_pos(halt_kin_spos, over_steps)
        self.toolhead.set_position(haltpos)
        # Signal homing/probing move complete
        try:
            self.printer.send_event("homing:homing_move_end", self)
        except self.printer.command_error as e:
            if error is None:
                error = str(e)
        if error is not None:
            if not safe_z:
                raise self.printer.command_error(error)
            else:
                # safe_z 模式：记录日志但不抛出异常
                logging.warning("small_homing_move safe_z suppressed error: %s", error)
        return trigpos

# State tracking of homing requests
class Homing:
    def __init__(self, printer):
        self.printer = printer
        self.toolhead = printer.lookup_object('toolhead')
        self.changed_axes = []
        self.trigger_mcu_pos = {}
        self.adjust_pos = {}
    def set_axes(self, axes):
        self.changed_axes = axes
    def get_axes(self):
        return self.changed_axes
    def get_trigger_position(self, stepper_name):
        return self.trigger_mcu_pos[stepper_name]
    def set_stepper_adjustment(self, stepper_name, adjustment):
        self.adjust_pos[stepper_name] = adjustment
    def _fill_coord(self, coord):
        # Fill in any None entries in 'coord' with current toolhead position
        thcoord = list(self.toolhead.get_position())
        for i in range(len(coord)):
            if coord[i] is not None:
                thcoord[i] = coord[i]
        return thcoord
    def set_homed_position(self, pos):
        self.toolhead.set_position(self._fill_coord(pos))
    def home_rails_z(self, rails, forcepos, movepos):
        # Notify of upcoming homing operation
        self.printer.send_event("homing:home_rails_begin", self, rails)
        # Alter kinematics class to think printer is at forcepos
        homing_axes = [axis for axis in range(3) if forcepos[axis] is not None]
        startpos = self._fill_coord(forcepos)
        homepos = self._fill_coord(movepos)
        self.toolhead.set_position(startpos, homing_axes=homing_axes)
        # Perform first home
        endstops = [es for rail in rails for es in rail.get_endstops()]
        hi = rails[0].get_homing_info()
        hmove = HomingMove(self.printer, endstops)
        hmove.homing_move(homepos, hi.speed)
        # Perform second/third/... home with multi-sample tolerance check
        if hi.retract_dist:
            # 预计算回退参数（固定，每次回退量相同）
            startpos = self._fill_coord(forcepos)
            homepos = self._fill_coord(movepos)
            axes_d = [hp - sp for hp, sp in zip(homepos, startpos)]
            move_d = math.sqrt(sum([d*d for d in axes_d[:3]]))
            retract_r = min(1., hi.retract_dist / move_d)
            retractpos = [hp - ad * retract_r
                          for hp, ad in zip(homepos, axes_d)]
            second_startpos = [rp - ad * retract_r
                               for rp, ad in zip(retractpos, axes_d)]
            # 容差与重试参数（优先从 homing_info 读取，否则使用默认值）
            samples_tolerance = getattr(hi, 'samples_tolerance', 0.010)
            samples_tolerance = 25
            samples_retries   = getattr(hi, 'samples_retries',   10)
            # 三次慢速回零，收集各次 trigger_mcu_pos，按容差判断一致性
            SAMPLE_COUNT = 3
            all_trig_pos = []   # 每次的 trigger_mcu_pos dict
            retries = 0
            reactor = self.printer.get_reactor()
            gcode = self.printer.lookup_object('gcode')
            while len(all_trig_pos) < SAMPLE_COUNT:
                # Retract
                self.toolhead.move(retractpos, hi.retract_speed)
                self.toolhead.flush_step_generation()
                # Home again (slow)
                self.toolhead.set_position(second_startpos)
                hmove = HomingMove(self.printer, endstops)
                # start
                for mcu_endstop, name in endstops:
                    mcu_stop = mcu_endstop
                    break
                for i in range(6):
                    toolhead = self.printer.lookup_object('toolhead')
                    print_time = toolhead.get_last_move_time()
                    res = mcu_stop.query_endstop(print_time)
                    logging.warning("z_homing:[%d]:[%d]",i, res)
                    if res:
                        gcode.run_script_from_command("GET_BASIC_PARAM")
                        reactor.pause(reactor.monotonic() + 0.500)
                        if i == 5:
                            error = '{"coded": "0055-0000-0000-0001", "msg":"Probe triggered prior to movement"}'
                            raise self.printer.command_error(error)
                        continue
                    else:
                        break
                # end
                hmove.homing_move(homepos, hi.second_homing_speed)
                no_move_name = hmove.check_no_movement()
                if no_move_name is not None:
                    if retries >= samples_retries:
                        raise self.printer.command_error(
                            "Probe triggered prior %s remained triggered during homing samples "
                            "after %d retries"
                            % (no_move_name, samples_retries))
                    wait_s = min(1.0, HOMING_RETRY_DELAY * (retries + 1))
                    logging.warning(
                        "home_rails_z: endstop '%s' still triggered, waiting %.2fs "
                        "and retrying (%d/%d)",
                        no_move_name, wait_s, retries + 1, samples_retries)
                    reactor.pause(reactor.monotonic() + wait_s)
                    retries += 1
                    all_trig_pos = []  # 清空已有样本，重新采集
                    continue
                # 收集本次各步进电机的触发位置
                trig_pos_this = {sp.stepper_name: sp.trig_pos
                                 for sp in hmove.stepper_positions}
                all_trig_pos.append(trig_pos_this)
                logging.info("home_rails: sample %d trig_pos=%s",
                             len(all_trig_pos), trig_pos_this)
                # 容差检查：对每个步进轴，判断所有样本的 trig_pos 极差
                if len(all_trig_pos) > 1:
                    stepper_names = list(all_trig_pos[0].keys())
                    spread_ok = True
                    for sname in stepper_names:
                        vals = [s[sname] for s in all_trig_pos]
                        spread = max(vals) - min(vals)
                        if spread > samples_tolerance:
                            spread_ok = False
                            break
                    if not spread_ok:
                        if retries >= samples_retries:
                            raise self.printer.command_error(
                                "Probe triggered prior samples exceed tolerance on stepper '%s'"
                                " (spread=%d steps > %.4fmm tolerance). "
                                "Check endstop and mechanics."
                                % (sname, spread, samples_tolerance))
                        wait_s = min(1.0, HOMING_RETRY_DELAY * (retries + 1))
                        logging.warning(
                            "home_rails: samples spread %d steps on '%s', "
                            "waiting %.2fs and retrying (%d/%d)...",
                            spread, sname, wait_s, retries + 1, samples_retries)
                        reactor.pause(reactor.monotonic() + wait_s)
                        retries += 1
                        all_trig_pos = []
            # 三次一致，取最后一次 hmove 作为最终结果（最新触发位置最准确）
            # trigger_mcu_pos 在下方统一赋值
        # Signal home operation complete
        self.toolhead.flush_step_generation()
        self.trigger_mcu_pos = {sp.stepper_name: sp.trig_pos
                                for sp in hmove.stepper_positions}
        self.adjust_pos = {}
        self.printer.send_event("homing:home_rails_end", self, rails)
        if any(self.adjust_pos.values()):
            # Apply any homing offsets
            kin = self.toolhead.get_kinematics()
            homepos = self.toolhead.get_position()
            kin_spos = {s.get_name(): (s.get_commanded_position()
                                       + self.adjust_pos.get(s.get_name(), 0.))
                        for s in kin.get_steppers()}
            newpos = kin.calc_position(kin_spos)
            for axis in homing_axes:
                homepos[axis] = newpos[axis]
            self.toolhead.set_position(homepos)
    def home_rails(self, rails, forcepos, movepos):
        # Notify of upcoming homing operation
        self.printer.send_event("homing:home_rails_begin", self, rails)
        # Alter kinematics class to think printer is at forcepos
        homing_axes = [axis for axis in range(3) if forcepos[axis] is not None]
        startpos = self._fill_coord(forcepos)
        homepos = self._fill_coord(movepos)
        self.toolhead.set_position(startpos, homing_axes=homing_axes)
        # Perform first home
        endstops = [es for rail in rails for es in rail.get_endstops()]
        hi = rails[0].get_homing_info()
        hmove = HomingMove(self.printer, endstops)
        hmove.homing_move(homepos, hi.speed)
        # Perform second home
        if hi.retract_dist:
            # Retract
            startpos = self._fill_coord(forcepos)
            homepos = self._fill_coord(movepos)
            axes_d = [hp - sp for hp, sp in zip(homepos, startpos)]
            move_d = math.sqrt(sum([d*d for d in axes_d[:3]]))
            retract_r = min(1., hi.retract_dist / move_d)
            retractpos = [hp - ad * retract_r
                          for hp, ad in zip(homepos, axes_d)]
            self.toolhead.move(retractpos, hi.retract_speed)
            self.toolhead.flush_step_generation()
            # Home again
            startpos = [rp - ad * retract_r
                        for rp, ad in zip(retractpos, axes_d)]
            self.toolhead.set_position(startpos)
            hmove = HomingMove(self.printer, endstops)
            hmove.homing_move(homepos, hi.second_homing_speed)
            no_move_endstop = hmove.check_no_movement()
            if no_move_endstop is not None:
                reactor = self.printer.get_reactor()
                recover_ok = False
                for attempt in range(3):
                    wait_s = HOMING_RETRY_DELAY * (attempt + 1)
                    logging.warning(
                        "home_rails: endstop '%s' still triggered after retract, "
                        "waiting %.2fs and retrying (%d/3)",
                        no_move_endstop, wait_s, attempt + 1)
                    reactor.pause(reactor.monotonic() + wait_s)
                    self.toolhead.move(retractpos, hi.retract_speed)
                    self.toolhead.flush_step_generation()
                    self.toolhead.set_position(startpos)
                    hmove = HomingMove(self.printer, endstops)
                    hmove.homing_move(homepos, hi.second_homing_speed)
                    no_move_endstop = hmove.check_no_movement()
                    if no_move_endstop is None:
                        recover_ok = True
                        break
                    if not recover_ok:
                        raise self.printer.command_error(
                            "Probe triggered prior %s still triggered after retract and retries"
                            % (no_move_endstop,))
        # Signal home operation complete
        self.toolhead.flush_step_generation()
        self.trigger_mcu_pos = {sp.stepper_name: sp.trig_pos
                                for sp in hmove.stepper_positions}
        self.adjust_pos = {}
        self.printer.send_event("homing:home_rails_end", self, rails)
        if any(self.adjust_pos.values()):
            # Apply any homing offsets
            kin = self.toolhead.get_kinematics()
            homepos = self.toolhead.get_position()
            kin_spos = {s.get_name(): (s.get_commanded_position()
                                       + self.adjust_pos.get(s.get_name(), 0.))
                        for s in kin.get_steppers()}
            newpos = kin.calc_position(kin_spos)
            for axis in homing_axes:
                homepos[axis] = newpos[axis]
            self.toolhead.set_position(homepos)
class PrinterHoming:
    def __init__(self, config):
        self.printer = config.get_printer()
        # Register g-code commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('G28', self.cmd_G28)
    def manual_home(self, toolhead, endstops, pos, speed,
                    triggered, check_triggered):
        hmove = HomingMove(self.printer, endstops, toolhead)
        try:
            hmove.homing_move_small(pos, speed, triggered=triggered,
                              check_triggered=check_triggered)
        except self.printer.command_error:
            if self.printer.is_shutdown():
                raise self.printer.command_error(
                    "Homing failed due to printer shutdown")
            raise
    def probing_move(self, mcu_probe, pos, speed, rase=True, safe_mode=False):
        endstops = [(mcu_probe, "probe")]
        hmove = HomingMove(self.printer, endstops)
        try:
              epos = hmove.homing_move(pos, speed, probe_pos=True,
                                         safe_z=safe_mode)
        except self.printer.command_error:
            if self.printer.is_shutdown():
                error = '{"coded": "0003-0528-0000-0008", "msg":"%s"}' % ("Probing failed due to printer shutdown")
                raise self.printer.command_error(error)
            raise
        if hmove.check_no_movement() is not None:
            #reactor = self.printer.get_reactor()
            #self.gcode.run_script_from_command("QUERY_ESTOP AXES=X")
            #self.gcode.run_script_from_command("QUERY_ENDSTOPS")
            #self.gcode.run_script_from_command("GET_BASIC_PARAM")
            #for i in range(5):
            #    reactor.pause(reactor.monotonic() + 0.500)
            #    self.gcode.run_script_from_command("GET_BASIC_PARAM")
            if rase:
                error = '{"coded": "0003-0528-0000-0009", "msg":"%s"}' % ("Probe triggered prior to movement")
                raise self.printer.command_error(error)
            epos[0] = 9999
        return epos
    def cmd_G28(self, gcmd):
        # Move to origin
        axes = []
        for pos, axis in enumerate('XYZ'):
            if gcmd.get(axis, None) is not None:
                axes.append(pos)
        if not axes:
            axes = [0, 1, 2]
        homing_state = Homing(self.printer)
        homing_state.set_axes(axes)
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        try:
            kin.home(homing_state, gcmd)
        except self.printer.command_error:
            if self.printer.is_shutdown():
                raise self.printer.command_error(
                    "Homing failed due to printer shutdown")
            self.printer.lookup_object('stepper_enable').motor_off()
            raise

def load_config(config):
    return PrinterHoming(config)
