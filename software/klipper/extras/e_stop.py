import logging
import pins
from . import homing


HINT_TIMEOUT = """
If the toolhead did not move far enough to trigger, then
consider increase the x_offset or y_offset value so the toolhead
can travel further.
"""


# Endstop wrapper that enables TmcHome specific features
class EStopEndstopWrapper:
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
        self.recover_endstop_state = self.mcu_endstop.recover_endstop_state
        # multi probes state
        self.multi = 'OFF'
        self.last_move_error = None

    def _handle_mcu_identify(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis('z') and self.stepper_name == "Z":
                self.add_stepper(stepper)
            if stepper.is_active_axis('x') and self.stepper_name == "X":
                self.add_stepper(stepper)
            if stepper.is_active_axis('y') and self.stepper_name == "Y":
                self.add_stepper(stepper)

    # def e_stop_move(self, pos, speed):
    #     endstops = [(self, "probe")]
    #     max_retries = 10
    #     last_error = None
    #     self.last_move_error = None
    #     for attempt in range(max_retries + 1):
    #         hmove = homing.HomingMove(self.printer, endstops)
    #         try:
    #             epos = hmove.homing_move(pos, speed, probe_pos=True)
    #         except self.printer.command_error as e:
    #             if self.printer.is_shutdown():
    #                 raise self.printer.command_error(
    #                     "E-stop probing failed due to printer shutdown")
    #             last_error = str(e)
    #             if attempt < max_retries:
    #                 logging.warning(
    #                     "e_stop_move: homing issue (%s), retrying (%d/%d)",
    #                     last_error, attempt + 1, max_retries)
    #                 continue
    #             self.last_move_error = (
    #                 "E-stop probing failed after %d retries. Last error: %s"
    #                 % (max_retries, last_error))
    #             return None
    #         if hmove.check_no_movement() is not None:
    #             if attempt < max_retries:
    #                 logging.warning(
    #                     "e_stop_move: endstop triggered before movement, retrying (%d/%d)",
    #                     attempt + 1, max_retries)
    #                 continue
    #             self.last_move_error = (
    #                 "The estop is unqualified %d retries"
    #                 % (max_retries,))
    #             return None
    #         return epos
    #     if last_error is not None:
    #         self.last_move_error = (
    #             "The estop is unqualified %d retries. Last error: %s"
    #             % (max_retries, last_error))
    #     else:
    #         self.last_move_error = (
    #             "The estop is unqualified %d retries" % max_retries)
    #     return None
    def e_stop_move(self, pos, speed):
        phoming = self.printer.lookup_object('homing')
        epos = phoming.probing_move(self, pos, speed, rase=False,
                                         safe_mode=False)
        return epos
    def get_position_endstop(self):
        return self.position_endstop


class EStopFunc:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.stepper_name = config.get_name().split()[-1]
        logging.info("EStopFunc init: axis=%s", self.stepper_name)
        self.mcu_probe = EStopEndstopWrapper(config)
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_mux_command("ESTOP", "AXES",
                                   self.stepper_name,
                                   self.cmd_ESTOP,
                                   desc=self.cmd_ESTOP_help)
        self.gcode.register_mux_command("QUERY_ESTOP", "AXES",
                                   self.stepper_name,
                                   self.cmd_QUERY_ESTOP,
                                   desc=self.cmd_QUERY_ESTOP_help)
        self.speed = config.getfloat('speed', 5.0, above=0.)
        self.position_offset = config.getfloat('offset', 0.)
        self.back_v = config.getfloat('back_v', 2.0)
        self.err_v = config.getfloat('error_v', 0.05)
        self.main_cnt = config.getfloat('main_cycle_cnt', 3.0)
        self.sub_cnt = config.getfloat('sub_cycle_cnt', 3.0)
        self._last_probe_error = None

    # def _probe(self, speed):
    #     toolhead = self.printer.lookup_object('toolhead')
    #     gcode = self.printer.lookup_object('gcode')
    #     self._last_probe_error = None

    #     # --- 确定轴索引和目标位置 ---
    #     if self.stepper_name == "X":
    #         axis_idx = 0
    #     elif self.stepper_name == "Y":
    #         axis_idx = 1
    #     elif self.stepper_name == "Z":
    #         axis_idx = 2
    #     else:
    #         return None

    #     # 重新获取当前位置
    #     cur_pos = toolhead.get_position()
    #     target_pos = list(cur_pos)
    #     target_pos[axis_idx] = self.position_offset

    #     # 回退方向：触发限位后，需要向远离限位的方向回退
    #     # 即回退方向与探测方向相反
    #     cur_val = cur_pos[axis_idx]
    #     if self.stepper_name == "Z":
    #         back_v = self.back_v          # Z 轴回退始终向上（正方向）
    #     elif cur_val > self.position_offset:
    #         # 当前在限位正侧，探测方向是负方向，触发后回退应向正方向
    #         back_v = self.back_v
    #     else:
    #         # 当前在限位负侧，探测方向是正方向，触发后回退应向负方向
    #         back_v = -self.back_v

    #     move_dist = abs(cur_val - self.position_offset)
    #     # gcode.respond_info(
    #     #     "estop endstop at: probing from %.3f to %.3f (%.2fmm)"
    #     #     % (cur_val, self.position_offset, move_dist)
    #     # )

    #     try:
    #         epos = self.mcu_probe.e_stop_move(target_pos, speed)
    #         if epos is None:
    #             reason = self.mcu_probe.last_move_error or "E-stop move returned no result"
    #             self._last_probe_error = reason
    #             return None
    #     except self.printer.command_error as e:
    #         reason = str(e)
    #         if "Timeout during endstop homing" in reason:
    #             reason += HINT_TIMEOUT
    #         if "No trigger on probe after full movement" in reason:
    #             reason += (
    #                 "\n[ESTOP Debug] axis=%s cur=%.3f target=%.3f dist=%.3fmm"
    #                 "\nCheck: 1) endstop wiring  2) position_offset config"
    #                 "  3) move direction" %
    #                 (self.stepper_name, cur_val, self.position_offset, move_dist)
    #             )
    #         self._last_probe_error = reason
    #         return None

    #     # 提取本轴触发位置
    #     s_pos = epos[axis_idx]

    #     # 回退
    #     ppos = toolhead.get_position()
    #     retract_pos = list(ppos)
    #     retract_pos[axis_idx] = ppos[axis_idx] + back_v
    #     toolhead.move(retract_pos, speed)
    #     self.printer.send_event("toolhead:manual_move")

    #     gcode.respond_info(
    #         "estop endstop at [%.3f, %.3f, %.3f]"
    #         % (epos[0], epos[1], epos[2])
    #     )
    #     return s_pos

    # def run_probe(self, gcmd):
    #     sample_cnt = max(1, int(self.sub_cnt))
    #     max_retries = max(0, int(self.main_cnt))
    #     # 两个独立重试计数器：探测失败 vs spread 超标
    #     probe_retries = 0
    #     spread_retries = 0
    #     positions = []

    #     while len(positions) < sample_cnt:
    #         pos = self._probe(self.speed)
    #         if pos is None:
    #             # 探测本身失败（未触发 / 异常）
    #             reason = self._last_probe_error or "probe returned no position"
    #             if probe_retries >= max_retries:
    #                 logging.warning("ESTOP %s final probe failure: %s",
    #                                 self.stepper_name, reason)
    #                 self._last_probe_error = reason
    #                 return None
    #             probe_retries += 1
    #             positions = []
    #             logging.warning("ESTOP %s probe issue (%d/%d): %s",
    #                             self.stepper_name, probe_retries, max_retries, reason)
    #             continue

    #         positions.append(pos)
    #         if len(positions) < 2:
    #             # 只有一个样本，无法判断 spread
    #             continue

    #         spread = max(positions) - min(positions)
    #         if spread <= self.err_v:
    #             # spread 合格，继续采集下一个样本
    #             continue

    #         # spread 超标，独立计重试
    #         if spread_retries >= max_retries:
    #             msg = ("The estop is unqualified (spread=%.4f > err_v=%.4f)"
    #                    % (spread, self.err_v))
    #             logging.warning("ESTOP %s %s", self.stepper_name, msg)
    #             self._last_probe_error = msg
    #             return None

    #         spread_retries += 1
    #         positions = []
    #         logging.warning("ESTOP %s spread %.4f > %.4f, retrying (%d/%d)",
    #                         self.stepper_name, spread, self.err_v,
    #                         spread_retries, max_retries)

    #     return sum(positions) / len(positions)
    def _probe(self, speed):
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        back_v = 2
        if self.stepper_name == "X":
            if pos[0] > self.position_offset:
                back_v = -self.back_v
            else:
                back_v = self.back_v
            pos[0] = self.position_offset
        elif self.stepper_name == "Y":
            if pos[1] > self.position_offset:
                back_v = -self.back_v
            else:
                back_v = self.back_v
            pos[1] = self.position_offset
        elif self.stepper_name == "Z":
            back_v = self.back_v
            pos[2] = self.position_offset
        else:
            return

        try:
            reactor = self.printer.get_reactor()
            for i in range(6): 
                pin_state = self.get_pin_state()
                if pin_state == "triggered":
                    self.gcode.run_script_from_command("GET_BASIC_PARAM")
                    reactor.pause(reactor.monotonic() + 0.500)
                    if i == 5:
                        error = '{"coded": "0099-0000-0000-0001", "msg":"Probe triggered prior to movement"}'
                        raise self.printer.command_error(error)
                    continue
                else:
                    break
            epos = self.mcu_probe.e_stop_move(pos, speed)
            if epos[0] == 9999:
                return epos[0]
            ppos = toolhead.get_position()
            #ppos = list(pos) 
            gcode = self.printer.lookup_object('gcode')
            #gcode.respond_info("get_position at [%.3f,%.3f,%.3f]" % (pos[0], pos[1], pos[2]))
            #calc up value
            if self.stepper_name == "X":
                s_pos = epos[0]
                if ppos[0] > 0:
                    ppos[0] = ppos[0] - back_v
                else:
                    ppos[0] = ppos[0] + back_v
                epos[1] = ppos[1]
                epos[2] = ppos[2]
            elif self.stepper_name == "Y":
                s_pos = epos[1]
                if ppos[1] > 0:
                    ppos[1] = ppos[1] - back_v
                else:
                    ppos[1] = ppos[1] + back_v
                epos[0] = ppos[0]
                epos[2] = ppos[2]
            elif self.stepper_name == "Z":
                s_pos = epos[2]
                ppos[2] = ppos[2] + back_v
                epos[0] = ppos[0]
                epos[1] = ppos[1]
            else:
                return
            toolhead.move(ppos, speed)
            #toolhead.set_position(pos)
            self.printer.send_event("toolhead:manual_move")
            #toolhead.flush_step_generation()
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            logging.warning("coded:9999-0528-0000-0008,MSG[%s]", reason)
            raise self.printer.command_error(reason)
        # Allow axis_twist_compensation to update results
        #self.printer.send_event("probe:update_results", epos)
        # Report results
        gcode.respond_info("estop endstop at [%.3f,%.3f,%.3f]" % (epos[0], epos[1], epos[2]))
        #logging.info("estop endstop at [%.3f,%.3f,%.3f]", epos[0], epos[1], epos[2])
        #p_pos = toolhead.get_position()
        #gcode.respond_info("curr：[%.3f,%.3f,%.3f]" % (p_pos[0], p_pos[1], p_pos[2]))
        #return epos[:3]
        return s_pos
    def run_probe(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        #probexy = toolhead.get_position()[:2]
        positions = []
        retries = 0
        # Probe position
        while len(positions) < self.sub_cnt:
            pos = self._probe(self.speed)
            if pos == 9999:
                continue
            positions.append(pos)
            if max(positions)-min(positions) > self.err_v:
                if retries >= self.main_cnt:
                    logging.info("The estop is unqualified.")
                    gcmd.respond_info("The estop is unqualified.")
                    raise gcmd.error("The estop is unqualified.")
                retries += 1
                positions = []
        average = 0
        if len(positions) >= self.sub_cnt:
            average = sum(positions) / len(positions);
        return average

    cmd_ESTOP_help = "measure XYZ position mm value use hd limit"
    cmd_QUERY_ESTOP_help = "query estop pin state and last move error"
    def cmd_QUERY_ESTOP(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        pin_state = self.mcu_probe.query_endstop(print_time)
        state_text = "triggered" if pin_state else "open"
        gcmd.respond_info(
            "QUERY_ESTOP %s: pin_state=%s (%s)" % (
                self.stepper_name, pin_state, state_text))
        msg = "FP_QUERY_ESTOP %s: pin_state=%s (%s)" % (self.stepper_name, pin_state, state_text)
        logging.warning("[%s]", msg)
        if self.mcu_probe.last_move_error:
            gcmd.respond_info(
                "QUERY_ESTOP %s: last_move_error=%s" % (
                    self.stepper_name, self.mcu_probe.last_move_error))
    def get_pin_state(self):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        pin_state = self.mcu_probe.query_endstop(print_time)
        state_text = "triggered" if pin_state else "open"
        return state_text
    def cmd_ESTOP(self, gcmd):
        self.position_offset = gcmd.get_float('TARGET', self.position_offset)
        pos = self.run_probe(gcmd)
        if self.stepper_name == "X":
            gcmd.respond_info("Result is X=%.6f" % (pos,))
        elif self.stepper_name == "Y":
            gcmd.respond_info("Result is Y=%.6f" % (pos,))
        elif self.stepper_name == "Z":
            gcmd.respond_info("Result is Z=%.6f" % (pos,))


def load_config_prefix(config):
    return EStopFunc(config)
