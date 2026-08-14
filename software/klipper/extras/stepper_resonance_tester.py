import numpy as np
import logging, time
#from scipy.signal import butter, filtfilt
#from scipy.fftpack import fft,ifft


CSV_DIR = "/tmp/"
#CSV_DIR = "/usr/data/logs/"  # --- IGNORE ---
BACK_VELOCITY = 300.0  # mm/s
FREQ_RESOLUTION = 3.0  # Hz

# 寻找指定频率范围内的峰值点
def find_fft_peak(fft_freqs, fft_amps, freq, range=3.0):
    # Find freq idx range
    idx0 = np.argmin(np.abs(fft_freqs - (freq-range)))
    idx1 = np.argmin(np.abs(fft_freqs - (freq+range)))

    # Find peak idx
    idx = np.argmax(fft_amps[idx0: idx1+1])
    peak_freq = fft_freqs[idx0: idx1+1][idx]
    peak_amp = fft_amps[idx0: idx1+1][idx]

    return peak_freq, peak_amp

# 三点插值找峰值（抛物线插值法）
def parabolic_interpolation(x, y):
    coeff = np.polyfit(x, y, 2)
    if np.abs(coeff[0]) < 1e-10:
        return x[1], y[1]
    x_peak = -coeff[1] / (2 * coeff[0])
    y_peak = coeff[0] * x_peak**2 + coeff[1] * x_peak + coeff[2]
    return x_peak, y_peak 

# 使用三点插值法找到峰值
def find_peak_with_interpolation(values):
    if values is None:
        return None
    if isinstance(values, np.ndarray):
        data = values
    else:
        data = np.array(values)

    # 三点插值找峰值（抛物线插值法）
    idx = np.argmax(data[:, 1])
    if 0 < idx < len(data) - 1:
        x_peak, y_peak = parabolic_interpolation(data[idx-1:idx+2, 0], data[idx-1:idx+2, 1])
    else:
        x_peak = data[idx, 0]
        y_peak = data[idx, 1]

    return x_peak, y_peak

# 黄金分割法寻找最小值
def golden_section_search(f, a, b, tol=0.05, max_iter=20):
    """
    黄金分割法寻找函数极小值
    
    参数:
        f: 目标函数（单峰函数）
        a: 搜索区间左边界
        b: 搜索区间右边界
        tol: 容差，当区间宽度小于此值时停止
        max_iter: 最大迭代次数
    返回:
        x_opt: 最优点
        f_opt: 最优函数值
        history: 迭代历史 [(x, f(x)), ...]
    """
    # 黄金比例常数
    phi = (np.sqrt(5) - 1) / 2  # ≈ 0.618
    
    # 计算初始两个内部点
    x1 = b - phi * (b - a)  # 左侧内部点
    x2 = a + phi * (b - a)  # 右侧内部点

    # 计算函数值
    f1 = f(x1)
    f2 = f(x2)
    x_best = x1 if f1 < f2 else x2
    f_best = min(f1, f2)

    # 记录历史
    history = []
    iter_count = 0
    history.append(
        {'a': a,
         'b': b,
         'x1': x1,
         'x2': x2,
         'f1': f1,
         'f2': f2,
         'x_best': x_best,
         'f_best': f_best})
    # 迭代优化
    while abs(b - a) > tol and iter_count < max_iter:
        iter_count += 1
        
        # 根据函数值比较，缩小区间
        if f1 < f2:
            # 极小值在 [a, x2] 区间
            b = x2
            x2 = x1
            f2 = f1
            x1 = b - phi * (b - a)
            f1 = f(x1)
        else:
            # 极小值在 [x1, b] 区间
            a = x1
            x1 = x2
            f1 = f2
            x2 = a + phi * (b - a)
            f2 = f(x2)
        
        # 更新最优解：比较当前所有点，选择函数值最小的
        if f1 < f_best:
            x_best = x1
            f_best = f1
        if f2 < f_best:
            x_best = x2
            f_best = f2

        # 记录历史
        history.append(
            {'a': a,
             'b': b,
             'x1': x1,
             'x2': x2,
             'f1': f1,
             'f2': f2,
             'x_best': x_best,
             'f_best': f_best})
    # 直接返回已知最优点，无需额外函数调用
    x_opt = x_best
    f_opt = f_best

    return x_opt, f_opt, history

class StepperResonanceTester:
    def __init__(self, config):
        self.printer = config.get_printer()
        # Get the range of velocity, amp and phase for curve and mesh test
        self.vel_min, self.vel_max, self.vel_step = config.getfloatlist('vel_range', count=3)
        self.amp_min, self.amp_max, self.amp_step = config.getfloatlist('amp_range', count=3)
        self.phs_min, self.phs_max, self.phs_step = config.getfloatlist('phase_range', count=3)
        self.x_min, self.x_max = config.getfloatlist('x_range', count=2)
        self.y_min, self.y_max = config.getfloatlist('y_range', count=2)
        self.main_tdx = 2 # 产生振幅最大的倍频 1,2,4
        if self.x_max < self.x_min or self.y_max < self.y_min:
             raise config.error('stepper resonance damping: invalid min/max points')

        self.td_config = {'stepper_x': {}, 'stepper_y': {}}

        #获取机器结构信息
        sconfig = config.getsection('printer')
        self.max_accel = sconfig.getfloat('max_accel')
        self.kin = sconfig.get('kinematics')

        # get velocity ratio
        if self.kin == 'cartesian':
            self.td_config['stepper_x']['accel_axis'] = 0 # 0-x,1-y,2-z
            self.td_config['stepper_y']['accel_axis'] = 1 # 0-x,1-y,2-z
        elif self.kin == 'corexy':
            self.td_config['stepper_x']['accel_axis'] = 0 # 0-x,1-y,2-z
            self.td_config['stepper_y']['accel_axis'] = 0 # 0-x,1-y,2-z
        else:
            raise config.error("Not supported kinematics for stepper resonance tester: %s" % self.kin)

        # 获取步进电机共振频率
        self.td_config['stepper_x']['freq'] =  config.getfloat('stepper_x_freq', 200., above=0.)
        self.td_config['stepper_y']['freq'] =  config.getfloat('stepper_y_freq', 200., above=0.)

        # 初始化 td_amp 和 td_phase 为列表
        self.td_config['stepper_x']['td_amp'] = [0.0] * 3
        self.td_config['stepper_x']['td_phase'] = [[0.0, 0.0] for _ in range(3)]
        self.td_config['stepper_y']['td_amp'] = [0.0] * 3
        self.td_config['stepper_y']['td_phase'] = [[0.0, 0.0] for _ in range(3)]

        # 从[mclib stepper]获取幅值、相位初值
        sconfig = config.getsection('mclib stepper_x')
        for i in range(3):
            tdx = int(2**i)
            self.td_config['stepper_x']['td_amp'][i] = sconfig.getfloat('td%d_amp' % tdx, 0.010, minval=0., maxval=0.1)
            self.td_config['stepper_x']['td_phase'][i][0] = sconfig.getfloat('td%d_phase1' % tdx, np.pi, minval=0., maxval=(2*np.pi))
            self.td_config['stepper_x']['td_phase'][i][1] = sconfig.getfloat('td%d_phase2' % tdx, np.pi, minval=0., maxval=(2*np.pi))

        sconfig = config.getsection('mclib stepper_y')
        for i in range(3):
            tdx = int(2**i)
            self.td_config['stepper_y']['td_amp'][i] = sconfig.getfloat('td%d_amp' % tdx, 0.010, minval=0., maxval=0.1)
            self.td_config['stepper_y']['td_phase'][i][0] = sconfig.getfloat('td%d_phase1' % tdx, np.pi, minval=0., maxval=(2*np.pi))
            self.td_config['stepper_y']['td_phase'][i][1] = sconfig.getfloat('td%d_phase2' % tdx, np.pi, minval=0., maxval=(2*np.pi))

        # get rotation distance and dir inversion
        sconfig = config.getsection('stepper_x')
        dir_pin_desc = sconfig.get('dir_pin').strip()
        self.td_config['stepper_x']['dir_inverted'] = dir_pin_desc.startswith('!')
        self.td_config['stepper_x']['rotation_dis'] = sconfig.getfloat('rotation_distance')

        sconfig = config.getsection('stepper_y')
        dir_pin_desc = sconfig.get('dir_pin').strip()
        self.td_config['stepper_y']['dir_inverted'] = dir_pin_desc.startswith('!')
        self.td_config['stepper_y']['rotation_dis'] = sconfig.getfloat('rotation_distance')

        # get accelerometer chip names
        if not config.get('accel_chip_x', None):
            self.td_config['stepper_x']['accel_chip'] = config.get('accel_chip').strip()
            self.td_config['stepper_y']['accel_chip'] = config.get('accel_chip').strip()
        else:
            self.td_config['stepper_x']['accel_chip'] = config.get('accel_chip_x').strip()
            self.td_config['stepper_y']['accel_chip'] = config.get('accel_chip_y').strip()

        # register gcode commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("STEPPER_RESONANCE_TEST",
                                    self.cmd_STEPPER_RESONANCE_TEST,
                                    desc=self.cmd_STEPPER_RESONANCE_TEST_help)
        self.gcode.register_command("STEPPER_RESONANCE_CURVE_TEST",
                                    self.cmd_STEPPER_RESONANCE_CURVE_TEST,
                                    desc=self.cmd_STEPPER_RESONANCE_CURVE_TEST_help)
        self.gcode.register_command("STEPPER_RESONANCE_MESH_TEST",
                                    self.cmd_STEPPER_RESONANCE_MESH_TEST,
                                    desc=self.cmd_STEPPER_RESONANCE_MESH_TEST_help)
        self.gcode.register_command("STEPPER_RESONANCE_AMP_CALIBRATE",
                                    self.cmd_STEPPER_RESONANCE_AMP_CALIBRATE,
                                    desc=self.cmd_STEPPER_RESONANCE_AMP_CALIBRATE_help)
        self.gcode.register_command("STEPPER_RESONANCE_PHASE_CALIBRATE",
                                    self.cmd_STEPPER_RESONANCE_PHASE_CALIBRATE,
                                    desc=self.cmd_STEPPER_RESONANCE_PHASE_CALIBRATE_help)
        self.printer.register_event_handler("klippy:connect", self.connect)

    def connect(self):
        pass

    # prepare test parameters
    def prepare_test(self, gcmd):
        # Parse parameters
        self.stepper = gcmd.get('STEPPER')
        self.dir = gcmd.get_int('DIR', 1) # 1 for forward or 0 for backward
        self.vel = gcmd.get_float('VEL', None) # velocity in mm/s
        self.count = gcmd.get_int('COUNT', 1)

        # check stepper validity
        if self.stepper not in ['stepper_x', 'stepper_y']:
            raise gcmd.error("Invalid STEPPER value: %s" % self.stepper)   

        # check dir validity
        if self.dir not in [0, 1]:
            raise gcmd.error("Invalid DIR value: %s" % self.dir)

        # Parse TDX parameter: a list of integers, e.g., TDX=1,2,4
        try:
            self.tdx = [int(v.strip()) for v in gcmd.get('TDX', "1,2,4").split(',')]
            self.tdx.sort()
        except:
            raise gcmd.error("Unable to parse parameter '%s'" % ('TDX',))

        # check tdx validity
        valid_set = {1, 2, 4}
        if not (set(self.tdx).issubset(valid_set) and len(set(self.tdx)) == len(self.tdx)):
            raise gcmd.error("Invalid TDX value list: %s" % (self.tdx,))

        # Set freq and rotation distance
        self.res_freq = self.td_config[self.stepper]['freq'] # stepper resonance frequency
        self.rotation_dis = self.td_config[self.stepper]['rotation_dis']
        self.dir_inverted = self.td_config[self.stepper]['dir_inverted']

        # Get calibration td_amp and td_phase initial values
        self.td_idx = self.tdx[0] // 2 # 0 for td1, 1 for td2, 2 for td4
        self.phase_idx = int(not (self.dir ^ self.dir_inverted)) + 1 # 1 for phase1, 2 for phase2
        self.td_amp = self.td_config[self.stepper]['td_amp'][self.td_idx]
        self.td_phase = self.td_config[self.stepper]['td_phase'][self.td_idx][self.phase_idx-1]

    # Get move start and end position
    def prepare_move1(self, stepper, dir):
        # Disable input shaper if enabled
        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is not None:
            input_shaper.disable_shaping()

        # Override maximum acceleration and acceleration to
        # deceleration based on the maximum test frequency
        self.gcode.run_script_from_command(
                "SET_VELOCITY_LIMIT ACCEL=%.3f MINIMUM_CRUISE_RATIO=%.3f" % (self.max_accel, 0.0))

        # Specify move start and end
        start_x = (self.x_min + self.x_max)/2
        start_y = (self.y_min + self.y_max)/2
        end_x = start_x
        end_y = start_y
        # corexy
        if self.kin == 'corexy':
            if stepper == 'stepper_x':
                if dir == 1: # forward
                    end_x = self.x_max
                    end_y = self.y_max
                else: # backward
                    end_x = self.x_min
                    end_y = self.y_min
            if stepper == 'stepper_y':
                if dir == 1: # forward
                    end_x = self.x_max
                    end_y = self.y_min
                else: # backward
                    end_x = self.x_min
                    end_y = self.y_max
            self.vel_ratio = 2**0.5
            if end_y == start_y or end_x == start_x:
                self.vel_ratio = 1.0
        # cartesian
        if self.kin == 'cartesian':
            if stepper == 'stepper_x':
                if dir == 1:
                    end_x = self.x_max
                    end_y = start_y
                else:
                    end_x = self.x_min
                    end_y = start_y
            if stepper == 'stepper_y':
                if dir == 1:
                    end_x = start_x
                    end_y = self.y_max
                else:
                    end_x = start_x
                    end_y = self.y_min
            self.vel_ratio = 1.0

        # 未指定速度，使用共振频率计算速度
        if self.vel is None:
            self.vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        self.move = [(start_x, start_y), (end_x, end_y)]

    # Get move start and end position
    def prepare_move(self, stepper, dir):
        # Disable input shaper if enabled
        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is not None:
            input_shaper.disable_shaping()

        # Override maximum acceleration and acceleration to
        # deceleration based on the maximum test frequency
        self.gcode.run_script_from_command(
                "SET_VELOCITY_LIMIT ACCEL=%.3f MINIMUM_CRUISE_RATIO=%.3f" % (self.max_accel, 0.0))

        # Specify move start and end
        start_x = (self.x_min + self.x_max)/2
        start_y = (self.y_min + self.y_max)/2
        end_x = start_x
        end_y = start_y
        # corexy
        if self.kin == 'corexy':
            if stepper == 'stepper_x':
                if dir == 1: # forward
                    start_x = self.x_min
                    start_y = self.y_max - 100.0
                    end_x = self.x_min + 100.0
                    end_y = self.y_max
                else: # backward
                    start_x = self.x_min + 100.0
                    start_y = self.y_max
                    end_x = self.x_min
                    end_y = self.y_max - 100.0
            if stepper == 'stepper_y':
                if dir == 1: # forward
                    start_x = self.x_max - 100.0
                    start_y = self.y_max
                    end_x = self.x_max
                    end_y = self.y_max - 100.0
                else: # backward
                    start_x = self.x_max
                    start_y = self.y_max - 100.0
                    end_x = self.x_max - 100.0
                    end_y = self.y_max
            self.vel_ratio = 2**0.5
            if end_y == start_y or end_x == start_x:
                self.vel_ratio = 1.0
        # cartesian
        if self.kin == 'cartesian':
            if stepper == 'stepper_x':
                if dir == 1:
                    end_x = self.x_max
                    end_y = start_y
                else:
                    end_x = self.x_min
                    end_y = start_y
            if stepper == 'stepper_y':
                if dir == 1:
                    end_x = start_x
                    end_y = self.y_max
                else:
                    end_x = start_x
                    end_y = self.y_min
            self.vel_ratio = 1.0

        # 未指定速度，使用共振频率计算速度
        if self.vel is None:
            self.vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        self.move = [(start_x, start_y), (end_x, end_y)]

    # perform operations after the end of test
    def end_test(self, gcmd):
        # Restore input shaper if it was disabled for resonance testing
        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is not None:
            input_shaper.enable_shaping()
            gcmd.respond_info("Re-enabled [input_shaper]")

    def save_to_csv(self, filename, data, header=None, format_spec='%.3f'):
        """
        保存数据到CSV文件
        
        参数:
            filename: 文件路径
            data: 数据列表，每行是一个列表或元组
            header: CSV文件头（字符串或列表）
            format_spec: 数值格式化字符串，默认保留3位小数
        """
        with open(filename, 'w') as f:
            # 写入文件头
             if header is not None:
                if isinstance(header, list):
                    f.write(','.join(header) + '\n')
                else:
                    f.write(header + '\n')

            # 写入数据
             for row in data:
                if isinstance(row, (list, tuple)):
                    formatted_values = []
                    for v in row:
                        if isinstance(v, (int, float)):
                            formatted_values.append(format_spec % v)
                        else:
                            formatted_values.append(str(v))
                    f.write(','.join(formatted_values) + '\n')
                else:
                    f.write(str(row) + '\n')
        return

    # Move toolhead and perform accel measurement
    def do_move_and_accel_measure(self, move_speed):
        # Get move start and end positions
        start_x = self.move[0][0]
        start_y = self.move[0][1]
        end_x = self.move[1][0]
        end_y = self.move[1][1]
        toolhead = self.printer.lookup_object('toolhead')

        # Move to start position
        self.gcode.run_script_from_command(
            "G1 X%.3f Y%.3f F%.3f" % (start_x, start_y, BACK_VELOCITY * 60.0))
        # Wait for all movements to finish
        self.gcode.run_script_from_command("M400")

        # Start accelerometer measurement
        chip_name = self.td_config[self.stepper]['accel_chip']
        chip = self.printer.lookup_object(chip_name)
        aclient = chip.start_internal_client()

        toolhead.dwell(0.5)
        # Move at resonance speed to excite resonance         
        self.gcode.run_script_from_command(
            "G1 X%.3f Y%.3f F%.3f" % (end_x, end_y, move_speed * 60.0))
        toolhead.dwell(0.5)
        # Wait for all movements to finish
        self.gcode.run_script_from_command("M400")

        # After move, finish accelerometer measurement
        aclient.finish_measurements()
        samples = aclient.get_samples()

        # Write data to file
        # filename = "/tmp/%s_resonance-%s.csv" % (stepper, time.strftime("%Y%m%d_%H%M%S"))
        # aclient.write_to_file(filename)
        # gcmd.respond_info("Writing raw accelerometer data to %s file" % (filename,))

        return samples

    def calculate_resonance_frequency(self, gcmd, samples, gcode_accel):
        if samples is None:
            return None
        if isinstance(samples, np.ndarray):
            data = samples
        else:
            data = np.array(samples)
        t = data[:,0]
        accel = data[:,1]
        N = data.shape[0]
        T = t[-1] - t[0]
        fs = N / T  # 采样频率

        # Remove dc component
        accel_dc = np.mean(accel)
        accel_ac = accel - accel_dc

        # Find start and end idx of movement
        index = np.where(np.abs(accel_ac) > gcode_accel)[0]
        if len(index) == 0:
            return None
        start_idx = index[0]
        end_idx = index[-1] + 1
        gcmd.respond_info("start and end time of movement: %.6f, %.6f" % (t[start_idx], t[end_idx]))

        # Find resonance peak idx
        half_idx = start_idx + (end_idx - start_idx)//2
        peak = np.max(np.abs(accel_ac[start_idx:half_idx]))
        peak_idx = np.argmax(np.abs(accel_ac[start_idx:half_idx])) + start_idx
        gcmd.respond_info("Peak acceleration: %.3f at time %.6f sec" % (peak, t[peak_idx]))

        # Calculate resonance velocity
        time_to_peak = t[peak_idx] - t[start_idx]
        resonance_vel = gcode_accel * time_to_peak
        gcmd.respond_info("Estimated resonance velocity: %.3f mm/s" % resonance_vel)

        # Calculate resonance frequency
        N = 1024
        samples = accel_ac[peak_idx - N//2:peak_idx + N//2]
        fft_result = np.fft.fft(samples)
        freqs = np.fft.fftfreq(N, d=1/fs)
        idx = np.argmax(np.abs(fft_result))
        resonance_freq = np.abs(freqs[idx])

        return resonance_vel, resonance_freq

    def calculate_resonance_amps(self, samples, freqs):
        axis = self.td_config[self.stepper]['accel_axis']

        if samples is None:
            return None
        if isinstance(samples, np.ndarray):
            data = samples
        else:
            data = np.array(samples)

        t = data[:,0]
        accel = data[:, axis + 1]
        N = data.shape[0]
        T = t[-1] - t[0]
        fs = N / T  # 采样频率
        # Round up to the nearest power of 2 for faster FFT
        # M = 1 << int(fs * WINDOW_T_SEC - 1).bit_length()
        # if N <= M:
        #     return None

        # Remove dc component
        accel_dc = np.mean(accel)
        accel_ac = accel - accel_dc
        #gcmd.respond_info("DC component: %.3f" % accel_dc)

        # Find start and end idx of movement
        index = np.where(np.abs(accel_ac) > 0.5 * np.max(np.abs(accel_ac)))[0]
        if len(index) == 0:
            return None
        start_idx = index[0]
        end_idx = index[-1] + 1
        mid_idx = (start_idx + end_idx)//2
        #gcmd.respond_info("start and end time of movement: %.6f, %.6f" % (t[start_idx], t[end_idx]))

        # Calculate resonance amplitude of 1024 samples before the end idx
        N = 1024
        id0 = mid_idx - N//2
        id1 = mid_idx + N//2
        samples = accel_ac[id0 : id1]
        fft_result = np.fft.fft(samples)
        fft_freqs = np.fft.fftfreq(N, d=1/fs)

        # Get half freqs and amp
        fft_freqs = fft_freqs[range(int(N/2))]
        fft_amps = np.abs(fft_result)[range(int(N/2))]/N * 2

        # Find peak amp and freq in the specified freq range
        peak_freqs = []
        amplitude = []
        for i in range(len(freqs)):
            peak_freq, peak_amp = find_fft_peak(fft_freqs, fft_amps, freqs[i], range=FREQ_RESOLUTION)
            #gcmd.respond_info("Peak: freq=%.3f Hz, amp=%.3f" % (peak_freq, peak_amp))
            peak_freqs.append(peak_freq)
            amplitude.append(peak_amp)
        
        return peak_freqs, amplitude

    def do_resonance_vs_vel_test(self, vel):
        # Perform move and accel measurement at positive direction
        samples = self.do_move_and_accel_measure(vel)

        # calculate the resonance amplitude at res_point freq
        freqs = [vel/self.rotation_dis*self.vel_ratio*50*v for v in self.tdx]
        peak_freqs, resonance_amps = self.calculate_resonance_amps(samples, freqs)

        return resonance_amps

    def do_resonance_vs_amp_phase_test(self, td_amp, td_phase1, td_phase2):
        # Set the resonance damping amp and phase
        cmd_str = "MCLIB_SET_RESONANCE_DAMP STEPPER=%s" %(self.stepper)
        cmd_str += " TDX=%d AMP=%.3f PHASE1=%.3f PHASE2=%.3f" % (self.tdx[0], td_amp, td_phase1, td_phase2)
        self.gcode.run_script_from_command(cmd_str)

        # calculate the resonance amplitude at res_point freq
        vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        # Perform move and accel measurement at positive direction
        samples = self.do_move_and_accel_measure(vel)

        # calculate the resonance amplitude
        peak_freqs, resonance_amps = self.calculate_resonance_amps(samples, [self.res_freq])
        resonance_amp = resonance_amps[0]

        return resonance_amp

    def do_resonance_vs_phase_test(self, td_phase):
        # Set the resonance damping amp and phase
        cmd_str = "MCLIB_SET_RESONANCE_DAMP STEPPER=%s" %(self.stepper)
        cmd_str += " TDX=%d AMP=%.3f PHASE1=%.3f PHASE2=%.3f" % (self.tdx[0], self.td_amp, td_phase, td_phase)
        self.gcode.run_script_from_command(cmd_str)

        # calculate the resonance amplitude at res_point freq
        vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        # Perform move and accel measurement at positive direction
        samples = self.do_move_and_accel_measure(vel)

        # calculate the resonance amplitude
        peak_freqs, resonance_amps = self.calculate_resonance_amps(samples, [self.res_freq])
        resonance_amp = resonance_amps[0]

        return resonance_amp
    
    def do_resonance_vs_amp_test(self, td_amp):
        # Set the resonance damping amp and phase
        cmd_str = "MCLIB_SET_RESONANCE_DAMP STEPPER=%s" %(self.stepper)
        cmd_str += " TDX=%d AMP=%.3f PHASE1=%.3f PHASE2=%.3f" % (self.tdx[0], td_amp, self.td_phase, self.td_phase)
        self.gcode.run_script_from_command(cmd_str)

        # calculate the resonance amplitude at res_point freq
        vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        # Perform move and accel measurement at positive direction
        samples = self.do_move_and_accel_measure(vel)

        # calculate the resonance amplitude
        peak_freqs, resonance_amps = self.calculate_resonance_amps(samples, [self.res_freq])
        resonance_amp = resonance_amps[0]

        return resonance_amp

    # Test the resonance amp and frequency at specified velocity
    cmd_STEPPER_RESONANCE_TEST_help = ("Test the resonance amps at specified velocity for a stepper")
    def cmd_STEPPER_RESONANCE_TEST(self, gcmd):
        # prepare test parameters        
        self.prepare_test(gcmd)

        # get move start and end position
        self.prepare_move(self.stepper, self.dir)

        # Perform move and accel measurement at positive direction
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s" % (self.vel,))
        count = 0
        result = []
        while count < self.count:
            count += 1
            samples = self.do_move_and_accel_measure(self.vel)
  
            # calculate the resonance amplitude at specified frequency
            freqs = [self.vel/self.rotation_dis*self.vel_ratio*50*v for v in self.tdx]
            peak_freqs, resonance_amps = self.calculate_resonance_amps(samples, freqs)
  
            # Output result
            str = "Result:"
            for i in range(len(freqs)):
                str += " td%d_resonance_amp=%.3f;" % (self.tdx[i], resonance_amps[i])
            gcmd.respond_info(str)
  
            output = [count] + resonance_amps
            result.append(output)

            # Save the result to csv file
            filename = CSV_DIR + "%s_accel-%s.csv" % (self.stepper, time.strftime("%Y%m%d_%H%M%S"))
            csv_header = ["time", "accel_x", "accel_y", "accel_z"]
            self.save_to_csv(filename, samples, header=csv_header)
            gcmd.respond_info("Writing raw accel samples to %s file" % (filename,))

        # call after the end of test
        self.end_test(gcmd)

        # Save the result to csv file
        filename = CSV_DIR + "%s_resonance-%s.csv" % (self.stepper, time.strftime("%Y%m%d_%H%M%S"))
        csv_header = ["count"] + ["td%d_resonance_amp" % v for v in self.tdx]
        self.save_to_csv(filename, result, header=csv_header)
        gcmd.respond_info("Writing stepper resonance test result to %s file" % (filename,))


    # Test the relationship of resonance_amp and vel
    cmd_STEPPER_RESONANCE_CURVE_TEST_help = ("Test the resonance amp vs velocity for a stepper")
    def cmd_STEPPER_RESONANCE_CURVE_TEST(self, gcmd):
        # prepare test parameters
        self.prepare_test(gcmd)

        # get move start and end position
        self.prepare_move(self.stepper, self.dir)

        result = []
        for vel in np.arange(self.vel_min, self.vel_max, self.vel_step):
            # Perform move and accel measurement at positive direction
            gcmd.respond_info("Testing resonance at velocity %.3f mm/s" % (vel,))
            samples = self.do_move_and_accel_measure(vel)

            # calculate the resonance amplitude at res_point freq
            freqs = [vel/self.rotation_dis*self.vel_ratio*50*v for v in self.tdx]
            peak_freqs, resonance_amps = self.calculate_resonance_amps(samples, freqs)

            # Output result
            str = "Result:"
            for i in range(len(freqs)):
                str += " td%d_resonance_amp=%.3f" % (self.tdx[i], resonance_amps[i])
            gcmd.respond_info(str)

            output = [vel] + resonance_amps
            result.append(output)

        # Restore input shaper if it was disabled for resonance testing
        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is not None:
            input_shaper.enable_shaping()
            gcmd.respond_info("Re-enabled [input_shaper]")

        # Save the result to csv file
        filename = CSV_DIR + "%s_resonance_curve-%s.csv" % (self.stepper, time.strftime("%Y%m%d_%H%M%S"))
        csv_header = ["vel"] + ["td%d_resonance_amp" % v for v in self.tdx]
        self.save_to_csv(filename, result, header=csv_header)
        gcmd.respond_info("Writing stepper resonance test result to %s file" % (filename,))

        # Find the resonance frequency at maximum resonance amp
        data = np.array(result)
        # if 2 in self.tdx:
        #     peak_vel, peak_amp = find_peak_with_interpolation(data[:,[0,2]])
        #     res_freq = peak_vel/self.rotation_dis*2*self.vel_ratio*50 # resonance frequency
        #     gcmd.respond_info("Maximum resonance velocity %.1fmm/s, freq %.1f and amp %.1f" % (peak_vel, res_freq, peak_amp))
        if self.main_tdx in self.tdx:
            peak_vel, peak_amp = find_peak_with_interpolation(data[:,[0,int(self.main_tdx//2)+1]])
            res_freq = peak_vel/self.rotation_dis*self.main_tdx*self.vel_ratio*50 # resonance frequency
            gcmd.respond_info("Maximum resonance velocity %.1fmm/s, freq %.1f and amp %.1f" % (peak_vel, res_freq, peak_amp))

        # save the config
        configfile = self.printer.lookup_object('configfile')
        configfile.set('stepper_resonance_tester', '%s_freq'% self.stepper, "%.1f" % (res_freq, ))

        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")
        # update to system
        self.td_config[self.stepper]['freq']=res_freq

    # Test the mesh data of resonance_amp and (td2_amp, td2_phase)
    cmd_STEPPER_RESONANCE_MESH_TEST_help = ("Test the resonance amp and frequency at specified velocity for a stepper")
    def cmd_STEPPER_RESONANCE_MESH_TEST(self, gcmd):
        # prepare test parameters
        self.prepare_test(gcmd)
        if len(self.tdx) != 1:
            raise gcmd.error("TDX parameter should be a single value for mesh test")

        # get move start and end position
        self.prepare_move(self.stepper, self.dir)
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s" % (self.vel,))
        # do test
        tdx = self.tdx[0]
        result = []
        td_amp_opt = 0.0
        td_phase_opt = 0.0
        resonance_amp_min = float('inf')
        for td_amp in np.arange(self.amp_min, self.amp_max, self.amp_step):
            for td_phase in np.arange(self.phs_min, self.phs_max, self.phs_step):
                # perform resonance test vs amp and phase
                resonance_amp = self.do_resonance_vs_amp_phase_test(td_amp, td_phase, td_phase)

                # Output result
                gcmd.respond_info("Result: td_amp=%.3f, td_phase%d=%.3f, resonance_amp=%.3f" 
                                % (td_amp, self.phase_idx, td_phase, resonance_amp))

                # save result and find optimal value
                result.append([td_amp, td_phase, resonance_amp])
                if resonance_amp_min >= resonance_amp:
                    resonance_amp_min = resonance_amp
                    td_amp_opt = td_amp
                    td_phase_opt = td_phase
        
        gcmd.respond_info("Optimized td_amp=%.3f, td_phase%d=%.3f, resonance_amp=%.3f" 
                                % (td_amp_opt, self.phase_idx, td_phase_opt, resonance_amp_min))

        # Restore input shaper if it was disabled for resonance testing
        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is not None:
            input_shaper.enable_shaping()
            gcmd.respond_info("Re-enabled [input_shaper]")

        # Save the result to csv file
        filename = CSV_DIR + "%s_resonance_mesh-%s.csv" % (self.stepper, time.strftime("%Y%m%d_%H%M%S"))
        csv_header = ["td%d_amp" % tdx, "td%d_phase%d" % (tdx, self.phase_idx), "resonance_amp"]
        self.save_to_csv(filename, result, header=csv_header)
        gcmd.respond_info("Writing stepper resonance test result to %s file" % (filename,)) 

        # save the config
        configfile = self.printer.lookup_object('configfile')
        configfile.set('mclib %s'%self.stepper, 'td%d_amp'%(tdx), "%.3f" % (td_amp_opt, ))
        configfile.set('mclib %s'%self.stepper, 'td%d_phase%d'%(tdx, self.phase_idx), "%.3f" % (td_phase_opt, ))
        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")
        # update to system
        self.td_config[self.stepper]['td_amp'][int(np.log2(tdx))]=td_amp_opt
        self.td_config[self.stepper]['td_phase'][int(np.log2(tdx))][self.phase_idx-1] = td_phase_opt

    # calibrate stepper resonance amplitude
    cmd_STEPPER_RESONANCE_AMP_CALIBRATE_help = ("Calibrate the resonance amplitude for a specified stepper")    
    def cmd_STEPPER_RESONANCE_AMP_CALIBRATE(self, gcmd):        
        # prepare test parameters
        self.prepare_test(gcmd)
        if len(self.tdx) != 1:
            raise gcmd.error("TDX parameter should be a single value for amp calibration")

        # get move start and end position
        self.prepare_move(self.stepper, self.dir)
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s" % (self.vel,))

        # 设置初始搜索区间、容差和最大搜索次数
        a = max(self.td_amp - 0.005, 0.0) # amp must be non-negative
        b = max(self.td_amp + 0.005, 0.0) # amp must be non-negative
        tolerance = 0.002
        # 黄金分割搜索最优值
        gcmd.respond_info("Starting optimization search at range [%.3f, %.3f] with tolerance %.3f" % (a, b, tolerance))
        td_amp_opt, res_amp_opt, history = golden_section_search(self.do_resonance_vs_amp_test, a, b, tolerance, 10)

        gcmd.respond_info("Optimized td_amp=%.3f, resonance_amp=%.1f" % (td_amp_opt, res_amp_opt))
        # dump history
        for item in history:
            gcmd.respond_info("a=%.3f b=%.3f x1=%.3f x2=%.3f f1=%.3f f2=%.3f x_best=%.3f f_best=%.3f" 
                              % (item['a'], item['b'], item['x1'], item['x2'], item['f1'], item['f2'], item['x_best'], item['f_best']))

        # Save the final parameters to config file
        configfile = self.printer.lookup_object('configfile')
        configfile.set('mclib %s'%self.stepper, 'td%d_amp'%(self.tdx[0]), "%.3f" % (td_amp_opt, ))
        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")
        # update to system
        self.td_config[self.stepper]['td_amp'][int(np.log2(self.tdx[0]))]=td_amp_opt

    # calibrate stepper resonance phase1 and phase2
    cmd_STEPPER_RESONANCE_PHASE_CALIBRATE_help = ("Calibrate the resonance phase for a specified stepper")
    def cmd_STEPPER_RESONANCE_PHASE_CALIBRATE(self, gcmd):
        # prepare test parameters
        self.prepare_test(gcmd)
        if len(self.tdx) != 1:
            raise gcmd.error("TDX parameter should be a single value for phase calibration")

        # get move start and end position
        self.prepare_move(self.stepper, self.dir)
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s" % (self.vel,))

        # 设置初始搜索区间、容差和最大搜索次数
        a = self.td_phase - np.pi/2 # 2.0 # 0.0
        b = self.td_phase + np.pi/2 # np.pi
        tolerance = 0.05 #0.05

        # 黄金分割搜索最优值
        gcmd.respond_info("Starting optimization search at range [%.3f, %.3f] with tolerance %.3f" % (a, b, tolerance))        
        phase_opt, res_amp_opt, history = golden_section_search(self.do_resonance_vs_phase_test, a, b, tolerance, 10)

        # 归一化phase到0~2π范围内
        phase_opt = phase_opt % (2 * np.pi)
        gcmd.respond_info("Optimized td_phase=%.3f, resonance_amp=%.1f" % (phase_opt, res_amp_opt))
        # dump history
        for item in history:
            gcmd.respond_info("a=%.3f b=%.3f x1=%.3f x2=%.3f f1=%.3f f2=%.3f x_best=%.3f f_best=%.3f" 
                              % (item['a'], item['b'], item['x1'], item['x2'], item['f1'], item['f2'], item['x_best'], item['f_best']))

        # Save the final parameters to config file
        configfile = self.printer.lookup_object('configfile')
        configfile.set('mclib %s'%self.stepper, 'td%d_phase%d'%(self.tdx[0], self.phase_idx), "%.3f" % (phase_opt, ))
        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")
        # update to system
        self.td_config[self.stepper]['td_phase'][int(np.log2(self.tdx[0]))][self.phase_idx-1] = phase_opt

def load_config(config):
    return StepperResonanceTester(config)
