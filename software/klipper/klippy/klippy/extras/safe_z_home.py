# Perform Z Homing at specific XY coordinates.
#
# Copyright (C) 2019 Florian Heilmann <Florian.Heilmann@gmx.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

# Endstop wrapper that enables TmcHome specific features
class SafeStopEndstopWrapper:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.stepper_name = "Z"  #config.get_name().split()[-1]

        #self.position_endstop = config.getfloat('offset')

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
        # 获取已注册的步进器名称，防止重复注册
        registered = {s.get_name() for s in self.mcu_endstop.get_steppers()}
        for stepper in kin.get_steppers():
            if stepper.get_name() in registered:
                continue  # 已注册，跳过
            if stepper.is_active_axis('z') and self.stepper_name == "Z":
                self.add_stepper(stepper)
            elif stepper.is_active_axis('x') and self.stepper_name == "X":
                self.add_stepper(stepper)
            elif stepper.is_active_axis('y') and self.stepper_name == "Y":
                self.add_stepper(stepper)
    def z_stop_move(self, pos, speed):
        phoming = self.printer.lookup_object('homing')
        epos = phoming.probing_move(self, pos, speed, safe_mode=True)
        # epos[0]=9999 表示移动前 endstop 已触发（Eddy 信号未释放），属于正常安全停止
        if epos[0] == 9999:
            logging.warning("safe_z_home: z_stop_move triggered prior to movement"
                            " (Eddy signal not released), position may be inaccurate")
        return epos
    def get_position_endstop(self):
        # 修复：原来引用未定义的 self.x_endstop，改为从 mcu_endstop 读取
        if hasattr(self.mcu_endstop, 'get_position_endstop'):
            return self.mcu_endstop.get_position_endstop()
        return 0.


class SafeZHoming:
    def __init__(self, config):
        self.printer = config.get_printer()
        x_pos, y_pos = config.getfloatlist("home_xy_position", count=2)
        self.home_x_pos, self.home_y_pos = x_pos, y_pos
        self.z_hop = config.getfloat("z_hop", default=0.0)
        self.z_hop_speed = config.getfloat('z_hop_speed', 15., above=0.)
        zconfig = config.getsection('stepper_z')
        self.max_z = zconfig.getfloat('position_max', note_valid=False)
        self.speed = config.getfloat('speed', 50.0, above=0.)
        self.move_to_previous = config.getboolean('move_to_previous', False)
        self.printer.load_object(config, 'homing')
        self.gcode = self.printer.lookup_object('gcode')
        self.prev_G28 = self.gcode.register_command("G28", None)
        self.gcode.register_command("G28", self.cmd_G28)

        self.mcu_probe = SafeStopEndstopWrapper(config)

        if config.has_section("homing_override"):
            raise config.error("homing_override and safe_z_homing cannot"
                               +" be used simultaneously")

    def cmd_G28(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')

        # Perform Z Hop if necessary
        if self.z_hop != 0.0:
            # Check if Z axis is homed and its last known position
            curtime = self.printer.get_reactor().monotonic()
            kin_status = toolhead.get_kinematics().get_status(curtime)
            pos = toolhead.get_position()

            if 'z' not in kin_status['homed_axes']:
                # Always perform the z_hop if the Z axis is not homed
                pos[2] = 0
                toolhead.set_position(pos, homing_axes=[2])
                #toolhead.manual_move([None, None, self.z_hop],self.z_hop_speed)
                pos[2] = self.z_hop
                self.mcu_probe.z_stop_move(pos, self.z_hop_speed)
                if hasattr(toolhead.get_kinematics(), "note_z_not_homed"):
                    toolhead.get_kinematics().note_z_not_homed()
            elif pos[2] < self.z_hop:
                # If the Z axis is homed, and below z_hop, lift it to z_hop
                toolhead.manual_move([None, None, self.z_hop],
                                     self.z_hop_speed)

        # Determine which axes we need to home
        need_x, need_y, need_z = [gcmd.get(axis, None) is not None
                                  for axis in "XYZ"]
        if not need_x and not need_y and not need_z:
            need_x = need_y = need_z = True

        # Home XY axes if necessary
        new_params = {}
        if need_x:
            new_params['X'] = '0'
        if need_y:
            new_params['Y'] = '0'
        if new_params:
            g28_gcmd = self.gcode.create_gcode_command("G28", "G28", new_params)
            self.prev_G28(g28_gcmd)

        # Home Z axis if necessary
        if need_z:
            # Throw an error if X or Y are not homed
            curtime = self.printer.get_reactor().monotonic()
            kin_status = toolhead.get_kinematics().get_status(curtime)
            if ('x' not in kin_status['homed_axes'] or
                'y' not in kin_status['homed_axes']):
                raise gcmd.error("Must home X and Y axes first")
            # Move to safe XY homing position
            prevpos = toolhead.get_position()
            toolhead.manual_move([self.home_x_pos, self.home_y_pos], self.speed)
            # Home Z
            g28_gcmd = self.gcode.create_gcode_command("G28", "G28", {'Z': '0'})
            self.prev_G28(g28_gcmd)
            # Perform Z Hop again for pressure-based probes
            if self.z_hop:
                pos = toolhead.get_position()
                if pos[2] < self.z_hop:
                    toolhead.manual_move([None, None, self.z_hop],
                                         self.z_hop_speed)
            # Move XY back to previous positions
            if self.move_to_previous:
                toolhead.manual_move(prevpos[:2], self.speed)

def load_config(config):
    return SafeZHoming(config)
