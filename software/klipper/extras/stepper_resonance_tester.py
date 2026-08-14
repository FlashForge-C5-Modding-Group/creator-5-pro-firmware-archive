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

# 一阶IIR低通滤波器
def iir_lowpass_filter(signal, fc, fs):
    alpha = 2 * np.pi * fc / fs
    filtered = np.zeros_like(signal, dtype=float)
    filtered[0] = signal[0]
    for i in range(1, len(signal)):
        filtered[i] = alpha * signal[i] + (1.0 - alpha) * filtered[i-1]
    return filtered

def harmonic_extract_using_fft(t, accel, freqs, fs):
    N = len(t)

    # Remove dc component
    accel_dc = np.mean(accel)
    accel_ac = accel - accel_dc
    if not isinstance(freqs, (list, np.ndarray)):
        freqs = [freqs]

    # Hanning 窗抑制频谱泄漏
    window = np.hanning(N)
    accel_win = accel_ac * window

    fft_result = np.fft.rfft(accel_win)
    fft_freqs = np.fft.rfftfreq(N, d=1.0/fs)
    # Hanning窗幅度校正: 单边幅值 = |X|*4/N (窗均值0.5, 单边×2)
    fft_amps = np.abs(fft_result) * 4.0 / N

    # Find peak amp and freq in the specified freq range
    peak_freqs = []
    amplitude = []
    for freq in freqs:
        # 自适应搜索范围 ±2% 或 ±3Hz 取大者
        search_range = max(3.0, freq * 0.02)
        idx_lo = np.searchsorted(fft_freqs, freq - search_range)
        idx_hi = np.searchsorted(fft_freqs, freq + search_range)
        idx_hi = min(idx_hi, len(fft_freqs) - 1)
        idx_lo = min(idx_lo, idx_hi - 1)

        peak_idx = idx_lo + np.argmax(fft_amps[idx_lo:idx_hi])

        # 抛物线插值精化频率和幅值（减少栅栏效应）
        if idx_lo < peak_idx < idx_hi - 1:
            alpha = fft_amps[peak_idx - 1]
            beta = fft_amps[peak_idx]
            gamma = fft_amps[peak_idx + 1]
            denom = alpha - 2.0 * beta + gamma
            if abs(denom) > 1e-10:
                correction = 0.5 * (alpha - gamma) / denom
                peak_freq = fft_freqs[peak_idx] + correction * (fft_freqs[1] - fft_freqs[0])
                peak_amp = beta - 0.25 * (alpha - gamma) * correction
            else:
                peak_freq = fft_freqs[peak_idx]
                peak_amp = beta
        else:
            peak_freq = fft_freqs[peak_idx]
            peak_amp = fft_amps[peak_idx]

        peak_freqs.append(peak_freq)
        amplitude.append(peak_amp)
        logging.info("FFT peak search around %.2f Hz: found peak at %.2f Hz with amplitude %.1f" % (freq, peak_freq, peak_amp))

    return amplitude, peak_freqs

def harmonic_extract(t, accel, freqs):
    """
    基于正交解调的谐波幅值提取
    参数:
        t: 时间数组
        accel: 加速度数组
        freqs: 需要提取的频率列表
    返回:
        amps: 提取的频率对应的幅值列表
        phases: 提取的频率对应的相位列表
    """
    # 谐波提取 - 加窗 I/Q 解调
    # Remove dc component
    accel_dc = np.mean(accel)
    accel_ac = accel - accel_dc
    if not isinstance(freqs, (list, np.ndarray)):
        freqs = [freqs]

    # Hanning 窗抑制非整周期截断导致的频谱泄漏（旁瓣 -31dB）
    N = len(accel_ac)
    window = np.hanning(N)
    accel_win = accel_ac * window

    amps = []
    phases = []
    for freq in freqs:
        # Hanning窗正交解调
        omega = 2.0 * np.pi * freq
        I = 2.0 * np.mean(accel_win * np.sin(omega * t))
        Q = 2.0 * np.mean(accel_win * np.cos(omega * t))
        # Hanning 窗的相干增益为 0.5，补偿回来
        I *= 2.0
        Q *= 2.0

        # 计算幅值和相位
        amp = np.sqrt(I**2 + Q**2)
        phase = np.arctan2(Q, I)
        amps.append(amp)
        phases.append(phase)

    return amps, phases

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
        self.move_accel = config.getfloat('move_accel', 5000.0, minval=2000.0, maxval=10000.0)
        self.vel_min, self.vel_max, self.vel_step = config.getfloatlist('vel_range', count=3)
        self.amp_min, self.amp_max, self.amp_step = config.getfloatlist('amp_range', count=3)
        self.phs_min, self.phs_max, self.phs_step = config.getfloatlist('phase_range', count=3)
        self.x_min, self.x_max = config.getfloatlist('x_range', count=2)
        self.y_min, self.y_max = config.getfloatlist('y_range', count=2)
        self.distance = config.getfloat('move_distance', 100.0, minval=10.0)
        self.initial_trial_amp = config.getfloat('initial_trial_amp', 0.010, minval=0.005, maxval=0.1)
        self.min_distortion_threshold = config.getfloat('min_distortion_threshold', 200.0, minval=0.0)
        self.main_tdx = 2 # 产生振幅最大的倍频 1,2,4
        if self.x_max < self.x_min or self.y_max < self.y_min:
             raise config.error('stepper resonance damping: invalid min/max points')

        self.center_xy = {'stepper_x': {}, 'stepper_y': {}}
        self.center_xy['stepper_x'] = config.getfloatlist('stepper_x_center_xy', count=2)
        self.center_xy['stepper_y'] = config.getfloatlist('stepper_y_center_xy', count=2)

        # 从[stepper_resonance_tester]读取初始中心相位和幅值（负载角扫描用，XY共用）
        self.td_amp_initial = [0.0] * 3
        self.td_phase_initial = [0.0] * 3
        for i in range(3):
            tdx = int(2**i)
            self.td_amp_initial[i] = config.getfloat('td%d_amp_initial' % tdx, 0.0, minval=0., maxval=0.1)
            self.td_phase_initial[i] = config.getfloat('td%d_phase_initial' % tdx, 0.0, minval=0., maxval=(2*np.pi))
        self.load_angle_max = config.getfloat('load_angle_max', 30.0, minval=5., maxval=60.)

        self.td_config = {'stepper_x': {}, 'stepper_y': {}}

        #获取机器结构信息
        sconfig = config.getsection('printer')
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
        self.gcode.register_command("STEPPER_RESONANCE_SEARCH_CALIBRATE",
                                    self.cmd_STEPPER_RESONANCE_SEARCH_CALIBRATE,
                                    desc=self.cmd_STEPPER_RESONANCE_SEARCH_CALIBRATE_help)
        self.gcode.register_command("STEPPER_RESONANCE_REFINE_CALIBRATE",
                                    self.cmd_STEPPER_RESONANCE_REFINE_CALIBRATE,
                                    desc=self.cmd_STEPPER_RESONANCE_REFINE_CALIBRATE_help)
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
        self.axis = gcmd.get('AXIS', 'A') # for curve test, specify the axis to test, e.g., AXIS=X or AXIS=Y
        self.move_params = gcmd.get('MOVE', None) # specify move parameters: MOVE=center_x,center_y,angle,distance

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

        # Disable input shaper if enabled
        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is not None:
            input_shaper.disable_shaping()

        # Override maximum acceleration and acceleration to
        # deceleration based on the maximum test frequency
        self.gcode.run_script_from_command(
                "SET_VELOCITY_LIMIT ACCEL=%.3f MINIMUM_CRUISE_RATIO=%.3f" % (self.move_accel, 0.0))

    # Get move start and end position
    def update_move(self, stepper, dir):
        # get move parameters if specified
        if self.move_params is not None:
            try:
                move_parts = self.move_params.split(',')
                if len(move_parts) != 4:
                    raise ValueError
                center_x = float(move_parts[0].strip())
                center_y = float(move_parts[1].strip())
                angle = float(move_parts[2].strip())
                distance = float(move_parts[3].strip())
            except:
                raise ValueError("Invalid MOVE parameter format: %s. Expected format: center_x,center_y,angle,distance" % self.move_params)
        else: # 根据中心点、距离和角度，计算起点和终点
            distance = self.distance
            center_x = self.center_xy[self.stepper][0]
            center_y = self.center_xy[self.stepper][1]
            if self.kin == 'corexy':
                if stepper == 'stepper_x':
                    angle = 45.0 if dir == 1 else -135.0
                if stepper == 'stepper_y':
                    angle = -45.0 if dir == 1 else 135.0
            if self.kin == 'cartesian':
                if stepper == 'stepper_x':
                    angle = 0.0 if dir == 1 else 180.0
                if stepper == 'stepper_y':
                    angle = 90.0 if dir == 1 else -90.0

        # calculate move start and end points based on center, angle and distance
        half_dist = distance / 2.0
        cos_a = np.cos(np.radians(angle))
        sin_a = np.sin(np.radians(angle))
        dx = half_dist * cos_a
        dy = half_dist * sin_a
        start_x = center_x - dx
        start_y = center_y - dy
        end_x = center_x + dx
        end_y = center_y + dy

        self.move_angle = angle
        self.move = [(start_x, start_y), (end_x, end_y)]

        # 计算速度倍率: vel_ratio = |v_stepper| / v_toolhead
        # Cartesian: stepper_x → |cos(θ)|, stepper_y → |sin(θ)|
        # CoreXY:    stepper_x → |cos(θ)+sin(θ)|, stepper_y → |cos(θ)-sin(θ)|
        if self.kin == 'corexy':
            if stepper == 'stepper_x':
                self.vel_ratio = abs(cos_a + sin_a)
            else:
                self.vel_ratio = abs(cos_a - sin_a)
        if self.kin == 'cartesian':
            if stepper == 'stepper_x':
                self.vel_ratio = abs(cos_a)
            else:
                self.vel_ratio = abs(sin_a)
        # 防止除零（移动方向与电机轴正交时该电机不动）
        if self.vel_ratio < 1e-6:
            self.vel_ratio = 1e-6

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

        toolhead.dwell(0.2)
        # Record print_time at the start of the G1 move
        # (accelerometer timestamps are in the same print_time domain)
        t_move_start = toolhead.get_last_move_time()
        # Move at resonance speed to excite resonance         
        self.gcode.run_script_from_command(
            "G1 X%.3f Y%.3f F%.3f" % (end_x, end_y, move_speed * 60.0))
        t_move_end = toolhead.get_last_move_time()
        toolhead.dwell(0.2)
        # Wait for all movements to finish
        self.gcode.run_script_from_command("M400")

        # After move, finish accelerometer measurement
        aclient.finish_measurements()
        samples = aclient.get_samples()
        logging.info("do_move_and_accel_measure: t_move_start=%.6f "
                     "t_move_end=%.6f move_duration=%.6f samples=%d "
                     "t_sample_first=%.6f t_sample_last=%.6f"
                     % (t_move_start, t_move_end,
                        t_move_end - t_move_start, len(samples),
                        samples[0][0] if samples else 0.,
                        samples[-1][0] if samples else 0.))

        # Write data to file
        # filename = "/tmp/%s_resonance-%s.csv" % (stepper, time.strftime("%Y%m%d_%H%M%S"))
        # aclient.write_to_file(filename)
        # gcmd.respond_info("Writing raw accelerometer data to %s file" % (filename,))

        return samples, t_move_start, t_move_end

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

    def calculate_resonance_amps(self, samples, freqs, move_angle, axis='X', avg_num=1024):
        if samples is None:
            return None
        if isinstance(samples, np.ndarray):
            data = samples
        else:
            data = np.array(samples)

        if len(data) == 0:
            return None

        t = data[:, 0]
        accel_x = data[:, 1]
        accel_y = data[:, 2]
        angle_rad = np.radians(move_angle)
        accel_d = accel_x * np.cos(angle_rad) + accel_y * np.sin(angle_rad)
        accel_q = -accel_x * np.sin(angle_rad) + accel_y * np.cos(angle_rad)

        # 使用 accel_d 找到移动起始时间和终止时间 (aligned with move direction)
        index = np.where(np.abs(accel_d) > 0.5 * np.max(np.abs(accel_d)))[0]
        if len(index) == 0:
            return None
        start_idx = index[0]
        end_idx = index[-1] + 1
        mid_idx = (start_idx + end_idx)//2

        # 截取匀速段进行分析，避免加减速段对频谱的影响
        id0 = max(start_idx, mid_idx - avg_num//2)
        id1 = min(end_idx, mid_idx + avg_num//2)

        # 分别提取XYDQ方向振动幅度，再计算振动矢量幅度
        N = len(t)
        fs = N / (t[-1] - t[0])  # 采样频率
        t_seg = t[id0:id1]
        accel_x_amp, _ = harmonic_extract_using_fft(t_seg, accel_x[id0:id1], freqs, fs)
        accel_y_amp, _ = harmonic_extract_using_fft(t_seg, accel_y[id0:id1], freqs, fs)
        accel_d_amp, _ = harmonic_extract_using_fft(t_seg, accel_d[id0:id1], freqs, fs)
        accel_q_amp, _ = harmonic_extract_using_fft(t_seg, accel_q[id0:id1], freqs, fs)

        accel_amp = []
        for ax, ay in zip(accel_x_amp, accel_y_amp):
            accel_amp.append(np.sqrt(ax**2 + ay**2))

        resonances_amp = {'X': accel_x_amp, 'Y': accel_y_amp, 'D': accel_d_amp, 'Q': accel_q_amp, 'A': accel_amp}

        return resonances_amp[axis]

    def do_resonance_vs_vel_test(self, vel):
        # Perform move and accel measurement at positive direction
        samples, _, _ = self.do_move_and_accel_measure(vel)

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
        samples, _, _ = self.do_move_and_accel_measure(vel)

        # calculate the resonance amplitude
        resonance_amps = self.calculate_resonance_amps(samples, [self.res_freq], self.move_angle, self.axis)
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
        samples, _, _ = self.do_move_and_accel_measure(vel)

        # calculate the resonance amplitude
        resonance_amps = self.calculate_resonance_amps(samples, [self.res_freq], self.move_angle, self.axis)
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
        samples, _, _ = self.do_move_and_accel_measure(vel)

        # calculate the resonance amplitude
        resonance_amps = self.calculate_resonance_amps(samples, [self.res_freq], self.move_angle, self.axis)
        resonance_amp = resonance_amps[0]

        return resonance_amp

    # Test the resonance amp and frequency at specified velocity
    cmd_STEPPER_RESONANCE_TEST_help = ("Test the resonance amps at specified velocity for a stepper")
    def cmd_STEPPER_RESONANCE_TEST(self, gcmd):
        # prepare test parameters        
        self.prepare_test(gcmd)

        # update move path based on move parameters or stepper/direction
        self.update_move(self.stepper, self.dir)

        # 未指定速度，使用共振频率(td1基频)计算速度
        if self.vel is None:
            self.vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        # Perform move and accel measurement at positive direction
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s and angle %.3f degrees" % (self.vel, self.move_angle))
        count = 0
        result = []
        while count < self.count:
          count += 1
          samples, t_move_start, t_move_end = self.do_move_and_accel_measure(self.vel)
  
          # calculate the resonance amplitude at specified frequency
          freqs = [self.vel/self.rotation_dis*self.vel_ratio*50*v for v in self.tdx]
          resonance_amps = self.calculate_resonance_amps(samples, freqs, self.move_angle, self.axis)

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
          self.save_to_csv(filename, samples, header=csv_header, format_spec='%.6f')
          gcmd.respond_info("Writing raw accel samples at [%.6f %.6f] to %s file" % (t_move_start, t_move_end, filename))

        # call after the end of test
        self.end_test(gcmd)

        # Save the result to csv file
        filename = CSV_DIR + "%s_resonance-%s.csv" % (self.stepper, time.strftime("%Y%m%d_%H%M%S"))
        csv_header = ["count"] + ["td%d_%s_amp" % (v, self.axis) for v in self.tdx]
        self.save_to_csv(filename, result, header=csv_header, format_spec='%.6f')
        gcmd.respond_info("Writing stepper resonance test result to %s file" % (filename,))

    # Test the relationship of resonance_amp and vel
    cmd_STEPPER_RESONANCE_CURVE_TEST_help = ("Test the resonance amp vs velocity for a stepper")
    def cmd_STEPPER_RESONANCE_CURVE_TEST(self, gcmd):
        # prepare test parameters
        self.prepare_test(gcmd)

        # if apply new resonance freq immeditely
        apply = gcmd.get_int('APPLY', 0)

        # update move path based on move parameters or stepper/direction
        self.update_move(self.stepper, self.dir)

        result = []
        for vel in np.arange(self.vel_min, self.vel_max, self.vel_step):
            # Perform move and accel measurement at positive direction
            gcmd.respond_info("Testing resonance at velocity %.3f mm/s and angle %.3f degrees" % (vel, self.move_angle))
            # samples, _, _ = self.do_move_and_accel_measure(vel)

            # # calculate the resonance amplitude at res_point freq
            # freqs = [vel/self.rotation_dis*self.vel_ratio*50*v for v in self.tdx]
            # resonance_amps = self.calculate_resonance_amps(samples, freqs, self.move_angle, self.axis)
            retry_count = 0
            while retry_count < 5:
                samples, _, _ = self.do_move_and_accel_measure(vel)

                # calculate the resonance amplitude
                freqs = [vel/self.rotation_dis*self.vel_ratio*50*v for v in self.tdx]
                resonance_amps = self.calculate_resonance_amps(samples, freqs, self.move_angle, self.axis)
                if resonance_amps is not None:
                    break
                retry_count += 1

            # Output result
            str = "Result:"
            for i in range(len(freqs)):
                str += " td%d_%s_amp=%.3f" % (self.tdx[i], self.axis, resonance_amps[i])
            gcmd.respond_info(str)

            output = [vel] + resonance_amps
            result.append(output)

        # call after the end of test
        self.end_test(gcmd)

        # Save the result to csv file
        filename = CSV_DIR + "%s_resonance_curve-%s.csv" % (self.stepper, time.strftime("%Y%m%d_%H%M%S"))
        csv_header = ["vel"] + ["td%d_%s_amp" % (v, self.axis) for v in self.tdx]
        self.save_to_csv(filename, result, header=csv_header)
        gcmd.respond_info("Writing stepper resonance test result to %s file" % (filename,))

        # Find the resonance frequency at maximum resonance amp
        data = np.array(result)
        if self.main_tdx in self.tdx:
            peak_vel, peak_amp = find_peak_with_interpolation(data[:,[0,int(self.main_tdx//2)+1]])
            res_freq = peak_vel/self.rotation_dis*self.main_tdx*self.vel_ratio*50 # resonance frequency
            gcmd.respond_info("Maximum resonance velocity %.1fmm/s, freq %.1f and amp %.1f" % (peak_vel, res_freq, peak_amp))

        	# Determine if apply resonance frequency immeditely
            if apply == 1:
                self.td_config[self.stepper]['freq'] = res_freq

        # save the config
        configfile = self.printer.lookup_object('configfile')
        configfile.set('stepper_resonance_tester', '%s_freq'% self.stepper, "%.1f" % (res_freq, ))

        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")

    # Test the mesh data of resonance_amp and (td2_amp, td2_phase)
    cmd_STEPPER_RESONANCE_MESH_TEST_help = ("Test the resonance amp and frequency at specified velocity for a stepper")
    def cmd_STEPPER_RESONANCE_MESH_TEST(self, gcmd):
        # prepare test parameters
        self.prepare_test(gcmd)
        if len(self.tdx) != 1:
            raise gcmd.error("TDX parameter should be a single value for mesh test")

        # get move start and end position
        self.update_move(self.stepper, self.dir)

        # 未指定速度，使用共振频率(td1基频)计算速度
        if self.vel is None:
            self.vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        # Perform move and accel measurement at positive direction
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s and angle %.3f degrees" % (self.vel, self.move_angle))

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

        # call after the end of test
        self.end_test(gcmd)

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

    # calibrate stepper resonance amplitude
    cmd_STEPPER_RESONANCE_AMP_CALIBRATE_help = ("Calibrate the resonance amplitude for a specified stepper")    
    def cmd_STEPPER_RESONANCE_AMP_CALIBRATE(self, gcmd):        
        # prepare test parameters
        self.prepare_test(gcmd)
        if len(self.tdx) != 1:
            raise gcmd.error("TDX parameter should be a single value for amp calibration")

        # get move start and end position
        self.update_move(self.stepper, self.dir)

        # 未指定速度，使用共振频率(td1基频)计算速度
        if self.vel is None:
            self.vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        # Perform move and accel measurement at positive direction
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s and angle %.3f degrees" % (self.vel, self.move_angle))

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

        # call after the end of test
        self.end_test(gcmd)

        # Save the final parameters to config file
        configfile = self.printer.lookup_object('configfile')
        configfile.set('mclib %s'%self.stepper, 'td%d_amp'%(self.tdx[0]), "%.3f" % (td_amp_opt, ))
        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")

    # calibrate stepper resonance phase1 and phase2
    cmd_STEPPER_RESONANCE_PHASE_CALIBRATE_help = ("Calibrate the resonance phase for a specified stepper")
    def cmd_STEPPER_RESONANCE_PHASE_CALIBRATE(self, gcmd):
        # prepare test parameters
        self.prepare_test(gcmd)
        if len(self.tdx) != 1:
            raise gcmd.error("TDX parameter should be a single value for phase calibration")

        # get move start and end position
        self.update_move(self.stepper, self.dir)

        # 未指定速度，使用共振频率(td1基频)计算速度
        if self.vel is None:
            self.vel = self.res_freq/50/self.tdx[0]*self.rotation_dis/self.vel_ratio # resonance frequency

        # Perform move and accel measurement at positive direction
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s and angle %.3f degrees" % (self.vel, self.move_angle))

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

        # call after the end of test
        self.end_test(gcmd)

        # Save the final parameters to config file
        configfile = self.printer.lookup_object('configfile')
        configfile.set('mclib %s'%self.stepper, 'td%d_phase%d'%(self.tdx[0], self.phase_idx), "%.3f" % (phase_opt, ))
        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")

    @staticmethod
    def _parabolic_fit_3points(x_points, y_values):
        """最小值左右三点抛物线插值，返回插值极小值位置
        结果天然约束在左右邻点之间，不会跑飞
        返回: x_opt (极小值位置)，若无法插值则返回采样最小值位置"""
        min_idx = np.argmin(y_values)
        if 0 < min_idx < len(x_points) - 1:
            x = x_points[min_idx - 1:min_idx + 2]
            y = y_values[min_idx - 1:min_idx + 2]
            coeff = np.polyfit(x, y, 2)
            if coeff[0] > 1e-10:
                return np.clip(-coeff[1] / (2.0 * coeff[0]), x[0], x[2])
        return x_points[min_idx]

    @staticmethod
    def _r2_sinusoidal_fit(phases, residuals):
        """R² 正弦模型最小二乘: R²(φ) = C₀ + a·cos(φ-φc) + b·sin(φ-φc)
        φc 为相位中心（消除窄范围时 cos 列与常数列的共线性）
        返回 (phase_opt, C0, a, b)
        当拟合结果不可靠时（C0≤0 / SNR低 / 相位超出扫描范围），
        切换到最小值左右三点抛物线插值（直接用残差）"""
        R2 = residuals ** 2
        # 中心化：减去相位均值，避免窄范围时设计矩阵病态
        phase_center = np.mean(phases)
        phases_centered = phases - phase_center
        A_mat = np.column_stack(
            [np.ones(len(phases)),
             np.cos(phases_centered), np.sin(phases_centered)])
        coeffs, _, _, _ = np.linalg.lstsq(A_mat, R2, rcond=None)
        C0, a, b = coeffs
        amplitude = np.sqrt(a**2 + b**2)

        # 判断拟合是否可靠
        use_parabolic = False
        if C0 <= 0:
            # 模型物理无意义（R² 直流分量不应为负）
            use_parabolic = True
        elif amplitude / C0 < 0.1:
            # 正弦分量相对直流分量过小，LSQ相位不可靠
            use_parabolic = True
        else:
            phase_opt = (phase_center + np.arctan2(-b, -a)) % (2.0 * np.pi)
            # 检查相位是否在扫描范围内
            ph_min = phases[0] % (2.0 * np.pi)
            ph_max = phases[-1] % (2.0 * np.pi)
            if ph_min <= ph_max:
                if phase_opt < ph_min or phase_opt > ph_max:
                    use_parabolic = True

        if use_parabolic:
            phase_opt = StepperResonanceTester._parabolic_fit_3points(
                phases, residuals)
        return phase_opt, C0, a, b

    @staticmethod
    def _quadrature_estimate(quad_phases, R_quad, trial_amp):
        """4 点正交解析估计最优相位和幅值
        quad_phases: [0, π/2, π, 3π/2] 对应的相位
        R_quad: 4 个残余幅值
        trial_amp: 当前试探幅值
        返回 (phase_opt, amp_est, R0_sq, R1, check_err_rad)
            amp_est 可能为 None"""
        R2_quad = R_quad ** 2
        a_coeff = (R2_quad[0] - R2_quad[2]) / 2.0
        b_coeff = (R2_quad[1] - R2_quad[3]) / 2.0
        R0_sq = np.mean(R2_quad)
        R1 = np.sqrt(a_coeff**2 + b_coeff**2)
        phase_opt = np.arctan2(-b_coeff, -a_coeff) % (2.0 * np.pi)
        worst_phase = (phase_opt + np.pi) % (2.0 * np.pi)
        max_idx = np.argmax(R_quad)
        max_phase_actual = quad_phases[max_idx]
        check_err = abs(((max_phase_actual - worst_phase + np.pi)
                         % (2.0 * np.pi)) - np.pi)
        amp_est = None
        if R0_sq > R1 and R1 > 1e-6:
            D_abs = (np.sqrt(R0_sq + R1)
                     + np.sqrt(R0_sq - R1)) / 2.0
            GAt_abs = (np.sqrt(R0_sq + R1)
                       - np.sqrt(R0_sq - R1)) / 2.0
            if GAt_abs > 1e-6:
                amp_est = trial_amp * D_abs / GAt_abs
                amp_est = min(amp_est, 0.100)
        return phase_opt, amp_est, R0_sq, R1, check_err

    @staticmethod
    def _parabolic_fit_amplitude(amp_points, residuals):
        """R²抛物线拟合，R²(A)= c0 + c1*A + c2*A^2，返回 (amp_opt, c0, c1, c2)
        高SNR时用全点LSQ，低SNR时切换到最小值左右三点插值"""
        R2 = residuals ** 2
        # 全点 LSQ 拟合
        A_mat = np.column_stack([np.ones(len(amp_points)),
                                 amp_points, amp_points ** 2])
        coeffs, _, _, _ = np.linalg.lstsq(A_mat, R2, rcond=None)
        c0, c1, c2 = coeffs
        min_idx = np.argmin(R2)
        amp_sample_min = amp_points[min_idx]
        if c2 > 1e-6:
            amp_opt_lsq = np.clip(-c1 / (2.0 * c2), 0.0, 0.100)
            # SNR 判据：LSQ极值偏离采样最小值超过1步距时视为低SNR
            step = ((amp_points[-1] - amp_points[0])
                    / max(len(amp_points) - 1, 1))
            if abs(amp_opt_lsq - amp_sample_min) > step:
                amp_opt = StepperResonanceTester._parabolic_fit_3points(
                    amp_points, R2)
            else:
                amp_opt = amp_opt_lsq
        else:
            amp_opt = amp_sample_min
        return amp_opt, c0, c1, c2

    def _apply_comp_and_measure(self, gcmd, vel, tdx, direction, amp, phase):
        """施加补偿 (amp, phase) 并测量残余幅值（单次）"""
        phase_idx = int(not (direction ^ self.dir_inverted)) + 1
        if phase_idx == 1:
            cmd_str = ("MCLIB_SET_RESONANCE_DAMP STEPPER=%s TDX=%d "
                       "AMP=%.3f PHASE1=%.3f PHASE2=%.3f"
                       % (self.stepper, tdx, amp, phase, 0.0))
        else:
            cmd_str = ("MCLIB_SET_RESONANCE_DAMP STEPPER=%s TDX=%d "
                       "AMP=%.3f PHASE1=%.3f PHASE2=%.3f"
                       % (self.stepper, tdx, amp, 0.0, phase))
        self.gcode.run_script_from_command(cmd_str)
        # samples, t_move_start, t_move_end = self.do_move_and_accel_measure(vel)

        # # calculate the resonance amplitude
        # freqs = [vel/self.rotation_dis*self.vel_ratio*50*tdx]
        # resonance_amps = self.calculate_resonance_amps(samples, freqs, self.move_angle, self.axis)
        retry_count = 0
        while retry_count < 5:
            samples, t_move_start, t_move_end = self.do_move_and_accel_measure(vel)

            # calculate the resonance amplitude
            freqs = [vel/self.rotation_dis*self.vel_ratio*50*tdx]
            resonance_amps = self.calculate_resonance_amps(samples, freqs, self.move_angle, self.axis)
            if resonance_amps is not None:
                break
            retry_count += 1

        return resonance_amps[0]

    def search_calibrate_one_direction(self, gcmd, tdx, direction,
                                       n_phase=12, n_amp=5):
        """幅值和相位同时寻优搜索标定

        利用 R(φ) = R₀ + R₁·cos(φ - φ_opt - π) 的正弦特性：
          - 最优相位处残余最小（补偿抵消扰动）
          - 反相位处残余最大（补偿叠加扰动）

        安全优先搜索策略:
          Round 1: 4点正交扫描 — 0°/90°/180°/270°，用小幅值试探，
                   解析求解 φ_opt（仅 4 次移动，最大化安全）
          Round 2: 精细相位扫描 — 在 φ_opt ±30° 范围扫描 5 点，
                   全在"好相位"区间，抛物线精化
          Round 3: 幅值扫描 — 在最优相位扫描 n_amp 个幅值，
                   相位正确时所有幅值都在抑制振动
          Round 4: 最终精化 — 用最优幅值在精细相位 ±15° 扫 3 点

        总测量次数: 1 + 4 + 5 + n_amp + 3 + 1（默认 19 次移动）
        其中仅 1~2 次处于"坏相位"（Round 1），且使用小幅值

        返回: (optimal_amp, optimal_phase, history)
          history: list of [round, amp, phase, residual] 每次测量记录
        """
        # 设置移动参数
        self.update_move(self.stepper, direction)

        # 未指定速度，使用共振频率(td1基频)计算速度
        if self.vel is None:
            vel = self.res_freq/50/tdx*self.rotation_dis/self.vel_ratio # resonance frequency
        else:
            vel = self.vel

        td_idx = tdx // 2  # 0 for td1, 1 for td2, 2 for td4
        phase_idx = int(not (direction ^ self.dir_inverted)) + 1
        history = []  # [round, amp, phase, residual]

        # ---- Step 0: 零补偿测量，获取裸扰动幅值作为试探参考 ----
        gcmd.respond_info(
            "Search cal: Measuring bare distortion "
            "(td%d, dir=%d, vel=%.3f mm/s)"
            % (tdx, direction, vel))
        A_bare = self._apply_comp_and_measure(
            gcmd, vel, tdx, direction, 0.0, 0.0)
        history.append([0, 0.0, 0.0, A_bare])
        gcmd.respond_info("  Bare distortion: A=%.4f" % A_bare)

        if A_bare < self.min_distortion_threshold:
            gcmd.respond_info(
                "  Distortion too small (%.1f < %.1f), skipping" % (A_bare, self.min_distortion_threshold))
            return 0.0, 0.0, history

        # 试探幅值用小固定值，即使相位反了也只增加 ~10-15% 振动
        # 注意: A_bare 是加速度计单位(~数千)，trial_amp 是补偿电流单位(~0.005-0.050)
        # 两者量纲不同，不能直接做比值
        trial_amp = self.td_amp_initial[td_idx]
        if trial_amp < 0.001:
            trial_amp = self.initial_trial_amp

        # ==== Round 1: 4点正交扫描 — 解析求 φ_opt ====
        # R²(φ) = R₀² - R₁·cos(φ - φ_opt) 是精确的正弦关系（无近似）
        # 用 R² 而非 R 求解，消除 sqrt 展开带来的高阶谐波误差。
        # 4点解析解: a = (R²₀° - R²₁₈₀°)/2, b = (R²₉₀° - R²₂₇₀°)/2
        # φ_opt = atan2(-b, -a)
        #
        # 自适应试探幅值：如果所有 4 点残余 > A_bare，说明 trial_amp
        # 过大（即使最优相位也在过补偿），缩小后重试。
        quad_phases = [0.0, np.pi / 2, np.pi, 3 * np.pi / 2]
        quad_labels = ["0", "90", "180", "270"]
        max_retries = 3
        for retry in range(max_retries):
            gcmd.respond_info(
                "Round 1: Quadrature phase probe "
                "(4 points, amp=%.4f%s)"
                % (trial_amp,
                   ", retry %d" % retry if retry > 0 else ""))
            R_quad = np.zeros(4)
            for i, ph in enumerate(quad_phases):
                R_quad[i] = self._apply_comp_and_measure(
                    gcmd, vel, tdx, direction, trial_amp, ph)
                history.append([1, trial_amp, ph, R_quad[i]])
                gcmd.respond_info(
                    "  phase=%sdeg  residual=%.1f"
                    % (quad_labels[i], R_quad[i]))

            # 检查是否过补偿：所有残余都大于裸扰动
            if np.min(R_quad) > A_bare * 0.8:
                # 用最大残余与 A_bare 的比值估算缩放因子
                # R_max ≈ |D| + |GA_t|, A_bare ≈ |D|
                # 目标: |GA_t_new| ≈ |D|/5 → trial_amp_new ≈ trial_amp * A_bare / (5*(R_max - A_bare))
                R_max = np.max(R_quad)
                scale = A_bare / (5.0 * max(R_max - A_bare, A_bare * 0.1))
                scale = min(scale, 0.5)  # 确保缩小，不能放大
                trial_amp_new = trial_amp * scale
                trial_amp_new = max(trial_amp_new, 0.005) # 不要过度缩小，保持足够信噪比
                gcmd.respond_info(
                    "  WARNING: All residuals > A_bare (min=%.1f > "
                    "%.1f), trial_amp too large. "
                    "Reducing %.4f -> %.4f"
                    % (np.min(R_quad), A_bare,
                       trial_amp, trial_amp_new))
                trial_amp = trial_amp_new
            else:
                break

        best_phase_r1, amp_est, R0_sq, R1, phase_check_err = \
            self._quadrature_estimate(quad_phases, R_quad, trial_amp)
        worst_phase = (best_phase_r1 + np.pi) % (2.0 * np.pi)
        max_idx = np.argmax(R_quad)

        gcmd.respond_info(
            "  R0²=%.4f, R1=%.4f, phase_opt=%.1fdeg, "
            "worst=%.1fdeg (max_sample=%sdeg, check_err=%.0fdeg)"
            % (R0_sq, R1, np.degrees(best_phase_r1),
               np.degrees(worst_phase), quad_labels[max_idx],
               np.degrees(phase_check_err)))
        if amp_est is not None:
            gcmd.respond_info(
                "  Amplitude estimate: A_opt_est=%.4f" % amp_est)

        if phase_check_err > np.radians(60):
            gcmd.respond_info(
                "  WARNING: Sinusoidal model poor fit "
                "(check_err=%.0fdeg > 60deg), "
                "falling back to N_PHASE=%d uniform sweep"
                % (np.degrees(phase_check_err), n_phase))
            # 回退到均匀扫描
            phase_points = np.linspace(
                0, 2.0 * np.pi, n_phase, endpoint=False)
            residuals_phase = np.zeros(n_phase)
            for i, ph in enumerate(phase_points):
                residuals_phase[i] = self._apply_comp_and_measure(
                    gcmd, vel, tdx, direction, trial_amp, ph)
                history.append([1, trial_amp, ph, residuals_phase[i]])
                gcmd.respond_info(
                    "  phase=%.1fdeg  residual=%.4f"
                    % (np.degrees(ph), residuals_phase[i]))
            best_phase_r1, C0_fb, a_fb, b_fb = \
                self._r2_sinusoidal_fit(phase_points, residuals_phase)
            gcmd.respond_info(
                "  Fallback R2 LSQ: C0=%.0f, a=%.0f, b=%.0f, "
                "phase_opt=%.1fdeg"
                % (C0_fb, a_fb, b_fb, np.degrees(best_phase_r1)))

        # ==== Round 2: 精细相位扫描（全在好相位区间）====
        n_fine_phase = 5
        delta_ph = np.radians(30.0)
        fine_phases = np.linspace(best_phase_r1 - delta_ph,
                                  best_phase_r1 + delta_ph, n_fine_phase)

        gcmd.respond_info(
            "Round 2: Fine phase sweep (%d points, amp=%.4f, "
            "center=%.1fdeg ±30deg)"
            % (n_fine_phase, trial_amp, np.degrees(best_phase_r1)))
        residuals_fine_ph = np.zeros(n_fine_phase)
        for i, ph in enumerate(fine_phases):
            ph_wrapped = ph % (2.0 * np.pi)
            residuals_fine_ph[i] = self._apply_comp_and_measure(
                gcmd, vel, tdx, direction, trial_amp, ph_wrapped)
            history.append([2, trial_amp, ph_wrapped, residuals_fine_ph[i]])
            gcmd.respond_info(
                "  phase=%.1fdeg  residual=%.4f"
                % (np.degrees(ph_wrapped), residuals_fine_ph[i]))

        # R² 正弦模型最小二乘精化相位
        best_phase_r2, C0_r2, a_r2, b_r2 = self._r2_sinusoidal_fit(
            fine_phases, residuals_fine_ph)

        gcmd.respond_info(
            "  R2 sinusoidal LSQ: C0=%.0f, a=%.0f, b=%.0f, "
            "phase_opt=%.1fdeg (from %.1fdeg)"
            % (C0_r2, a_r2, b_r2,
               np.degrees(best_phase_r2),
               np.degrees(best_phase_r1)))

        # ==== Round 3: 幅值寻优（3点抛物线插值逐步缩小区间）====
        if amp_est is not None and amp_est > 0.001:
            amp_center = amp_est
        else:
            amp_center = trial_amp
        a = max(amp_center * 0.5, 0.001)
        b = min(amp_center * 1.5, 0.100)
        mid = (a + b) / 2.0

        # 初始3点测量
        R_a = self._apply_comp_and_measure(
            gcmd, vel, tdx, direction, a, best_phase_r2)
        R_mid = self._apply_comp_and_measure(
            gcmd, vel, tdx, direction, mid, best_phase_r2)
        R_b = self._apply_comp_and_measure(
            gcmd, vel, tdx, direction, b, best_phase_r2)
        history.append([3, a, best_phase_r2, R_a])
        history.append([3, mid, best_phase_r2, R_mid])
        history.append([3, b, best_phase_r2, R_b])
        gcmd.respond_info(
            "Round 3: Amplitude optimization (phase=%.1fdeg)"
            % np.degrees(best_phase_r2))
        gcmd.respond_info(
            "  Init [%.4f,%.4f,%.4f] R=[%.1f,%.1f,%.1f]"
            % (a, mid, b, R_a, R_mid, R_b))

        # 迭代优化（最多 n_amp-3 次额外测量）
        # 若最小值在边界：向该方向扩展；否则：抛物线内插精化
        for it in range(n_amp - 3):
            if R_mid <= R_a and R_mid <= R_b:
                # 有效bracket，抛物线内插
                pts = np.array([a, mid, b])
                res = np.array([R_a, R_mid, R_b])
                x_opt, _, _, _ = self._parabolic_fit_amplitude(pts, res)
                x_opt = np.clip(x_opt, a, b)
                tol = (b - a) * 0.1
                if min(abs(x_opt - a), abs(x_opt - mid),
                       abs(x_opt - b)) < tol:
                    break
                R_new = self._apply_comp_and_measure(
                    gcmd, vel, tdx, direction, x_opt, best_phase_r2)
                history.append([3, x_opt, best_phase_r2, R_new])
                gcmd.respond_info(
                    "  iter%d: amp=%.4f  residual=%.1f"
                    % (it, x_opt, R_new))
                # 4点中剔除最大residual，保留最优3点bracket
                all_pts = np.array([a, mid, b, x_opt])
                all_res = np.array([R_a, R_mid, R_b, R_new])
                order = np.argsort(all_pts)
                all_pts = all_pts[order]
                all_res = all_res[order]
                min_i = np.argmin(all_res)
                if min_i == 0:
                    keep = [0, 1, 2]
                elif min_i == 3:
                    keep = [1, 2, 3]
                else:
                    keep = [min_i - 1, min_i, min_i + 1]
                a, mid, b = all_pts[keep]
                R_a, R_mid, R_b = all_res[keep]
            elif R_a < R_mid:
                # 极值在左侧，向左扩展
                span = b - mid
                b, R_b = mid, R_mid
                mid, R_mid = a, R_a
                a = max(mid - span, 0.001)
                if a >= mid:
                    break  # 已到物理下限
                R_a = self._apply_comp_and_measure(
                    gcmd, vel, tdx, direction, a, best_phase_r2)
                history.append([3, a, best_phase_r2, R_a])
                gcmd.respond_info(
                    "  iter%d expand left: amp=%.4f  residual=%.1f"
                    % (it, a, R_a))
            else:
                # 极值在右侧，向右扩展
                span = mid - a
                a, R_a = mid, R_mid
                mid, R_mid = b, R_b
                b = min(mid + span, 0.100)
                if b <= mid:
                    break  # 已到物理上限
                R_b = self._apply_comp_and_measure(
                    gcmd, vel, tdx, direction, b, best_phase_r2)
                history.append([3, b, best_phase_r2, R_b])
                gcmd.respond_info(
                    "  iter%d expand right: amp=%.4f  residual=%.1f"
                    % (it, b, R_b))

        # 最终抛物线拟合
        amp_points = np.array([a, mid, b])
        residuals_amp = np.array([R_a, R_mid, R_b])
        best_amp, c0, c1, c2 = self._parabolic_fit_amplitude(
            amp_points, residuals_amp)
        gcmd.respond_info(
            "  Result: amp_opt=%.4f  bracket=[%.4f,%.4f]"
            % (best_amp, a, b))

        # ==== Round 4: 最终相位精化（用最优幅值）====
        # 之前的相位搜索用的是 trial_amp，最优幅值可能不同，
        # 传递函数的非线性可能导致最优相位微调
        # 使用 5 点 + R² 正弦 LSQ（与 Round 2 一致）
        n_final = 5
        delta_final = np.radians(15.0)
        final_phases = np.linspace(best_phase_r2 - delta_final,
                                   best_phase_r2 + delta_final, n_final)

        gcmd.respond_info(
            "Round 4: Final phase refinement "
            "(%d points, amp=%.4f, ±15deg)"
            % (n_final, best_amp))
        residuals_final = np.zeros(n_final)
        for i, ph in enumerate(final_phases):
            ph_wrapped = ph % (2.0 * np.pi)
            residuals_final[i] = self._apply_comp_and_measure(
                gcmd, vel, tdx, direction, best_amp, ph_wrapped)
            history.append([4, best_amp, ph_wrapped, residuals_final[i]])
            gcmd.respond_info(
                "  phase=%.1fdeg  residual=%.4f"
                % (np.degrees(ph_wrapped), residuals_final[i]))

        # R² 正弦模型最小二乘精化相位
        best_phase, C0_r4, a_r4, b_r4 = self._r2_sinusoidal_fit(
            final_phases, residuals_final)
        best_phase = best_phase % (2.0 * np.pi)

        gcmd.respond_info(
            "  R2 sinusoidal LSQ: C0=%.0f, a=%.0f, b=%.0f, "
            "phase_opt=%.1fdeg (from %.1fdeg)"
            % (C0_r4, a_r4, b_r4,
               np.degrees(best_phase),
               np.degrees(best_phase_r2)))

        # 最终验证
        A_final = self._apply_comp_and_measure(
            gcmd, vel, tdx, direction, best_amp, best_phase)
        history.append([5, best_amp, best_phase, A_final])

        gcmd.respond_info(
            "Search result: amp=%.4f, phase=%.3f rad (%.1fdeg), "
            "residual=%.4f (bare=%.4f, reduction=%.1f%%)"
            % (best_amp, best_phase, np.degrees(best_phase),
               A_final, A_bare,
               (1.0 - A_final / A_bare) * 100.0 if A_bare > 1e-6 else 0.0))

        return best_amp, best_phase, history

    cmd_STEPPER_RESONANCE_SEARCH_CALIBRATE_help = (
        "Search-based calibration: sweep phase then amplitude "
        "to find optimal resonance damping parameters")
    def cmd_STEPPER_RESONANCE_SEARCH_CALIBRATE(self, gcmd):
        """幅值-相位同时寻优搜索标定

        用法:
          STEPPER_RESONANCE_SEARCH_CALIBRATE STEPPER=stepper_x TDX=2
          STEPPER_RESONANCE_SEARCH_CALIBRATE STEPPER=stepper_x TDX=1,2,4
          STEPPER_RESONANCE_SEARCH_CALIBRATE STEPPER=stepper_x N_PHASE=16

        参数:
          STEPPER: stepper_x 或 stepper_y
          TDX: 谐波阶数，1,2,4 的组合（默认 1,2,4）
          DIR: 0=反向, 1=正向, 不指定则双向
          N_PHASE: 粗相位扫描点数（默认12）
          N_AMP: 幅值扫描点数（默认5）
        """
        self.prepare_test(gcmd)

        cal_dir = gcmd.get('DIR', None)
        if cal_dir is not None:
            directions = [int(cal_dir)]
        else:
            directions = [1, 0]

        n_phase = gcmd.get_int('N_PHASE', 12)
        n_amp = gcmd.get_int('N_AMP', 5)
        n_phase = max(6, min(n_phase, 36))
        n_amp = max(3, min(n_amp, 10))

        total_moves = (1 + n_phase + n_amp + 5 + 1) * len(directions)
        gcmd.respond_info(
            "Search calibration: N_PHASE=%d, N_AMP=%d "
            "(~%d moves per harmonic per direction, "
            "~%d total per harmonic)"
            % (n_phase, n_amp, 1 + n_phase + n_amp + 5 + 1, total_moves))

        configfile = self.printer.lookup_object('configfile')
        results = []

        for tdx in self.tdx:
            gcmd.respond_info(
                "===== Search calibrating td%d for %s ====="
                % (tdx, self.stepper))

            amp_by_dir = {}
            phase_by_dir = {}
            for direction in directions:
                dir_name = "Forward" if direction == 1 else "Backward"
                gcmd.respond_info(
                    "--- Direction: %s (dir=%d) ---"
                    % (dir_name, direction))

                opt_amp, opt_phase, meas_history = \
                    self.search_calibrate_one_direction(
                        gcmd, tdx, direction,
                        n_phase=n_phase, n_amp=n_amp)
                amp_by_dir[direction] = opt_amp
                phase_by_dir[direction] = opt_phase

                for h in meas_history:
                    results.append([tdx, direction] + h)

            # 保存结果到配置
            if len(directions) == 2:
                final_amp = max(amp_by_dir.get(1, 0.0),
                                amp_by_dir.get(0, 0.0))
                phase1_idx = int(not (1 ^ self.dir_inverted)) + 1
                phase2_idx = int(not (0 ^ self.dir_inverted)) + 1
                final_phase1 = phase_by_dir.get(1, 0.0)
                final_phase2 = phase_by_dir.get(0, 0.0)
                if phase1_idx == 2:
                    final_phase1, final_phase2 = final_phase2, final_phase1

                configfile.set('mclib %s' % self.stepper,
                               'td%d_amp' % tdx,
                               "%.4f" % final_amp)
                configfile.set('mclib %s' % self.stepper,
                               'td%d_phase1' % tdx,
                               "%.3f" % final_phase1)
                configfile.set('mclib %s' % self.stepper,
                               'td%d_phase2' % tdx,
                               "%.3f" % final_phase2)

                cmd_str = ("MCLIB_SET_RESONANCE_DAMP STEPPER=%s TDX=%d "
                           "AMP=%.3f PHASE1=%.3f PHASE2=%.3f"
                           % (self.stepper, tdx, final_amp,
                              final_phase1, final_phase2))
                self.gcode.run_script_from_command(cmd_str)

                gcmd.respond_info(
                    "td%d result: amp=%.4f, phase1=%.3f, phase2=%.3f"
                    % (tdx, final_amp, final_phase1, final_phase2))
            else:
                direction = directions[0]
                phase_idx = int(not (direction ^ self.dir_inverted)) + 1
                configfile.set('mclib %s' % self.stepper,
                               'td%d_amp' % tdx,
                               "%.4f" % amp_by_dir[direction])
                configfile.set('mclib %s' % self.stepper,
                               'td%d_phase%d' % (tdx, phase_idx),
                               "%.3f" % phase_by_dir[direction])

                gcmd.respond_info(
                    "td%d result: amp=%.4f, phase%d=%.3f"
                    % (tdx, amp_by_dir[direction],
                       phase_idx, phase_by_dir[direction]))

        self.end_test(gcmd)

        filename = (CSV_DIR + "%s_search_calibrate-%s.csv"
                    % (self.stepper, time.strftime("%Y%m%d_%H%M%S")))
        csv_header = ["tdx", "dir", "round", "amp", "phase", "residual"]
        self.save_to_csv(filename, results, header=csv_header,
                         format_spec='%.4f')
        gcmd.respond_info(
            "Search calibration history (%d measurements) saved to %s"
            % (len(results), filename))

        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")

    def refine_calibrate_one_direction(self, gcmd, tdx, direction,
                                       init_amp, init_phase,
                                       half_spread=None, n_amp=5):
        """基于已有校准结果的快速精化搜索

        init_phase: 正反向相位的平均值（= φ_cog - ∠G，方向无关）
        half_spread: 正反向相位差的一半（= n·δ），用于偏移搜索中心
                     若为 None 则直接以 init_phase 为中心搜索

        搜索策略（利用负载角关系）：
          φ_fwd = init_phase + half_spread
          φ_rev = init_phase - half_spread
          搜索中心 = init_phase ± half_spread（根据方向）
          搜索范围 = ±15°（覆盖 δ 的不确定性）

          Round 1: 精细相位扫描 — search_center ±15°，5 点
          Round 2: 幅值扫描 — init_amp ±40%，n_amp 点
          Round 3: 最终相位精化 — 用最优幅值在 ±10° 扫 3 点
          验证: 1 次

        总测量次数: 5 + n_amp + 3 + 1 = 14（默认）

        返回: (optimal_amp, optimal_phase, history)
        """
        self.update_move(self.stepper, direction)

        # 未指定速度，使用共振频率(td1基频)计算速度
        if self.vel is None:
            vel = self.res_freq/50/tdx*self.rotation_dis/self.vel_ratio # resonance frequency
        else:
            vel = self.vel

        # Perform move and accel measurement at positive direction
        gcmd.respond_info("Testing resonance at velocity %.3f mm/s and angle %.3f degrees" % (vel, self.move_angle))

        history = []

        # ==== Round 0: 零补偿测量，获取裸扰动幅值作为试探参考 ====
        gcmd.respond_info(
            "Refine cal: Measuring bare distortion "
            "(td%d, dir=%d, vel=%.3f mm/s)"
            % (tdx, direction, vel))
        A_bare = self._apply_comp_and_measure(
            gcmd, vel, tdx, direction, 0.0, 0.0)
        history.append([0, 0.0, 0.0, A_bare])
        gcmd.respond_info("  Bare distortion: A=%.4f" % A_bare)

        if A_bare < self.min_distortion_threshold:
            gcmd.respond_info(
                "  Distortion too small (%.1f < %.1f), skipping" % (A_bare, self.min_distortion_threshold))
            return 0.0, 0.0, history

        # 根据方向从中点偏移搜索中心
        # phase1 对应 dir=1(正向) 或 dir=0(反向) 取决于 dir_inverted
        # phase_idx=1 → phase1, phase_idx=2 → phase2
        # 约定: 正向转子滞后，相位减小
        #   phase1(正向) = midpoint - half_spread
        #   phase2(反向) = midpoint + half_spread
        phase_idx = int(not (direction ^ self.dir_inverted)) + 1
        if half_spread is not None:
            if phase_idx == 1:
                search_center = (init_phase - half_spread) % (2.0 * np.pi)
            else:
                search_center = (init_phase + half_spread) % (2.0 * np.pi)
        else:
            search_center = init_phase

        gcmd.respond_info(
            "  Midpoint=%.1fdeg, half_spread=%s, "
            "search_center=%.1fdeg (phase%d)"
            % (np.degrees(init_phase),
               "%.1fdeg" % np.degrees(half_spread)
               if half_spread is not None else "None",
               np.degrees(search_center), phase_idx))

        # ==== Round 1: 精细相位扫描 ====
        n_fine_phase = 5
        # 使用 half_spread 作为扫描半径，使得负载角扫描范围 = [0, 2*half_spread]
        delta_ph = half_spread if half_spread is not None else np.radians(15.0)
        fine_phases = np.linspace(search_center - delta_ph,
                                  search_center + delta_ph, n_fine_phase)

        gcmd.respond_info(
            "Refine Round 1: Fine phase sweep (%d points, amp=%.4f, "
            "center=%.1fdeg ±%.1fdeg)"
            % (n_fine_phase, init_amp, np.degrees(search_center),
               np.degrees(delta_ph)))
        residuals_fine_ph = np.zeros(n_fine_phase)
        for i, ph in enumerate(fine_phases):
            ph_wrapped = ph % (2.0 * np.pi)
            residuals_fine_ph[i] = self._apply_comp_and_measure(
                gcmd, vel, tdx, direction, init_amp, ph_wrapped)
            history.append([1, init_amp, ph_wrapped, residuals_fine_ph[i]])
            gcmd.respond_info(
                "  phase=%.1fdeg  residual=%.4f"
                % (np.degrees(ph_wrapped), residuals_fine_ph[i]))

        best_phase_r1, C0_r1, a_r1, b_r1 = self._r2_sinusoidal_fit(
            fine_phases, residuals_fine_ph)

        gcmd.respond_info(
            "  Phase fit: C0=%.0f, a=%.0f, b=%.0f, "
            "phase_opt=%.1fdeg (center=%.1fdeg)"
            % (C0_r1, a_r1, b_r1,
               np.degrees(best_phase_r1),
               np.degrees(search_center)))

        # ==== Round 2: 幅值扫描 ====
        amp_lo = max(init_amp * 0.6, 0.001)
        amp_hi = min(init_amp * 1.4, 0.100)
        amp_points = np.linspace(amp_lo, amp_hi, n_amp)

        gcmd.respond_info(
            "Refine Round 2: Amplitude sweep (%d points, "
            "phase=%.1fdeg, range=[%.4f, %.4f])"
            % (n_amp, np.degrees(best_phase_r1), amp_lo, amp_hi))
        residuals_amp = np.zeros(n_amp)
        for i, am in enumerate(amp_points):
            residuals_amp[i] = self._apply_comp_and_measure(
                gcmd, vel, tdx, direction, am, best_phase_r1)
            history.append([2, am, best_phase_r1, residuals_amp[i]])
            gcmd.respond_info(
                "  amp=%.4f  residual=%.4f" % (am, residuals_amp[i]))

        best_amp, c0, c1, c2 = self._parabolic_fit_amplitude(
            amp_points, residuals_amp)

        gcmd.respond_info(
            "  Fit: c0=%.4f, c1=%.4f, c2=%.4f -> amp_opt=%.4f "
            "(min_sample=%.4f)"
            % (c0, c1, c2, best_amp,
               amp_points[np.argmin(residuals_amp)]))

        # ==== Round 3: 最终相位精化（用最优幅值）====
        n_final = 3
        delta_final = np.radians(10.0)
        final_phases = np.linspace(best_phase_r1 - delta_final,
                                   best_phase_r1 + delta_final, n_final)

        gcmd.respond_info(
            "Refine Round 3: Final phase refinement "
            "(%d points, amp=%.4f, ±10deg)"
            % (n_final, best_amp))
        residuals_final = np.zeros(n_final)
        for i, ph in enumerate(final_phases):
            ph_wrapped = ph % (2.0 * np.pi)
            residuals_final[i] = self._apply_comp_and_measure(
                gcmd, vel, tdx, direction, best_amp, ph_wrapped)
            history.append([3, best_amp, ph_wrapped, residuals_final[i]])
            gcmd.respond_info(
                "  phase=%.1fdeg  residual=%.4f"
                % (np.degrees(ph_wrapped), residuals_final[i]))

        best_phase, C0_r3, a_r3, b_r3 = self._r2_sinusoidal_fit(
            final_phases, residuals_final)

        gcmd.respond_info(
            "  R2 sinusoidal LSQ: C0=%.0f, a=%.0f, b=%.0f, "
            "phase_opt=%.1fdeg (from %.1fdeg)"
            % (C0_r3, a_r3, b_r3,
               np.degrees(best_phase),
               np.degrees(best_phase_r1)))

        # 最终验证
        A_final = self._apply_comp_and_measure(
            gcmd, vel, tdx, direction, best_amp, best_phase)
        history.append([4, best_amp, best_phase, A_final])

        gcmd.respond_info(
            "Refine result: amp=%.4f, phase=%.3f rad (%.1fdeg), "
            "residual=%.4f (bare=%.4f, reduction=%.1f%%)"
            % (best_amp, best_phase, np.degrees(best_phase),
               A_final, A_bare,
               (1.0 - A_final / A_bare) * 100.0 if A_bare > 1e-6 else 0.0))

        return best_amp, best_phase, history

    cmd_STEPPER_RESONANCE_REFINE_CALIBRATE_help = (
        "Quick refinement calibration using existing parameters "
        "as initial values (~14 moves per direction)")
    def cmd_STEPPER_RESONANCE_REFINE_CALIBRATE(self, gcmd):
        """基于已有参数的快速精化搜索标定

        用法:
          STEPPER_RESONANCE_REFINE_CALIBRATE STEPPER=stepper_x TDX=2
          STEPPER_RESONANCE_REFINE_CALIBRATE STEPPER=stepper_x TDX=1,2,4
          STEPPER_RESONANCE_REFINE_CALIBRATE STEPPER=stepper_x TDX=2 DIR=1
          STEPPER_RESONANCE_REFINE_CALIBRATE STEPPER=stepper_x LOAD_ANGLE_MAX=30

        参数:
          STEPPER: stepper_x 或 stepper_y
          TDX: 谐波阶数，1,2,4 的组合（默认 1,2,4）
          DIR: 0=反向, 1=正向, 不指定则双向
          N_AMP: 幅值扫描点数（默认5）
          LOAD_ANGLE_MAX: 负载角扫描最大值（度，默认30）

        模式:
          1) 若配置了 tdX_phase_initial / tdX_amp_initial:
             以 phase_initial 为中心相位，沿负载角 δ∈[0, LOAD_ANGLE_MAX]
             方向搜索（forward: +δ, backward: -δ）
          2) 否则回退到已有 td_phase1/td_phase2 计算中点和半扩展
        """
        self.prepare_test(gcmd)

        cal_dir = gcmd.get('DIR', None)
        if cal_dir is not None:
            directions = [int(cal_dir)]
        else:
            directions = [1, 0]

        n_amp = gcmd.get_int('N_AMP', 5)
        n_amp = max(3, min(n_amp, 10))

        load_angle_max = gcmd.get_float('LOAD_ANGLE_MAX',
                                        self.load_angle_max,
                                        minval=5.0, maxval=60.0)

        moves_per_dir = 5 + n_amp + 3 + 1
        total_moves = moves_per_dir * len(directions)
        gcmd.respond_info(
            "Refine calibration: N_AMP=%d, LOAD_ANGLE_MAX=%.1fdeg "
            "(~%d moves per harmonic per direction, "
            "~%d total per harmonic)"
            % (n_amp, load_angle_max, moves_per_dir, total_moves))

        configfile = self.printer.lookup_object('configfile')
        results = []

        for tdx in self.tdx:
            td_idx = tdx // 2  # 0, 1, 2
            gcmd.respond_info(
                "===== Refine calibrating td%d for %s ====="
                % (tdx, self.stepper))

            # 优先使用 tdX_phase_initial / tdX_amp_initial 配置参数
            init_phase_cfg = self.td_phase_initial[td_idx]
            init_amp_cfg = self.td_amp_initial[td_idx]

            if init_amp_cfg > 0.001:
                # 模式1: 使用配置的初始中心相位，沿负载角方向扫描
                init_phase_mid = init_phase_cfg
                init_amp = init_amp_cfg
                # n次谐波的相位偏移 = n * δ，扫描范围 = n * load_angle_max
                # half_spread = n * load_angle_max / 2
                half_spread = np.radians(load_angle_max / 2.0) * tdx

                gcmd.respond_info(
                    "  Mode: initial config (phase_initial=%.1fdeg, "
                    "amp_initial=%.4f, load_angle_max=%.1fdeg)"
                    % (np.degrees(init_phase_mid), init_amp,
                       load_angle_max))
            else:
                # 模式2: 回退到已有 phase1/phase2 计算中点
                init_amp = self.td_config[self.stepper]['td_amp'][td_idx]
                init_phases = self.td_config[self.stepper][
                    'td_phase'][td_idx]

                if init_amp < 0.001:
                    gcmd.respond_info(
                        "  WARNING: td%d_amp=%.4f too small, "
                        "run SEARCH_CALIBRATE first" % (tdx, init_amp))
                    continue

                # 用最短弧计算正反相位平均和差
                ph1, ph2 = init_phases[0], init_phases[1]
                diff = ((ph1 - ph2 + np.pi) % (2.0 * np.pi)) - np.pi
                init_phase_mid = (ph2 + diff / 2.0) % (2.0 * np.pi)
                half_spread = abs(diff) / 2.0

                gcmd.respond_info(
                    "  Mode: midpoint from phase1/phase2 "
                    "(mid=%.1fdeg, half_spread=%.1fdeg, "
                    "phase1=%.1fdeg, phase2=%.1fdeg)"
                    % (np.degrees(init_phase_mid),
                       np.degrees(half_spread),
                       np.degrees(ph1), np.degrees(ph2)))

            amp_by_dir = {}
            phase_by_dir = {}
            for direction in directions:
                dir_name = "Forward" if direction == 1 else "Backward"

                gcmd.respond_info(
                    "--- Direction: %s (dir=%d) ---"
                    % (dir_name, direction))

                opt_amp, opt_phase, meas_history = \
                    self.refine_calibrate_one_direction(
                        gcmd, tdx, direction,
                        init_amp, init_phase_mid,
                        half_spread=half_spread, n_amp=n_amp)
                amp_by_dir[direction] = opt_amp
                phase_by_dir[direction] = opt_phase

                for h in meas_history:
                    results.append([tdx, direction] + h)

            # 保存结果到配置
            if len(directions) == 2:
                final_amp = max(amp_by_dir.get(1, 0.0),
                                amp_by_dir.get(0, 0.0))
                phase1_idx = int(not (1 ^ self.dir_inverted)) + 1
                final_phase1 = phase_by_dir.get(1, 0.0)
                final_phase2 = phase_by_dir.get(0, 0.0)
                if phase1_idx == 2:
                    final_phase1, final_phase2 = final_phase2, final_phase1

                configfile.set('mclib %s' % self.stepper,
                               'td%d_amp' % tdx,
                               "%.4f" % final_amp)
                configfile.set('mclib %s' % self.stepper,
                               'td%d_phase1' % tdx,
                               "%.3f" % final_phase1)
                configfile.set('mclib %s' % self.stepper,
                               'td%d_phase2' % tdx,
                               "%.3f" % final_phase2)

                cmd_str = ("MCLIB_SET_RESONANCE_DAMP STEPPER=%s TDX=%d "
                           "AMP=%.3f PHASE1=%.3f PHASE2=%.3f"
                           % (self.stepper, tdx, final_amp,
                              final_phase1, final_phase2))
                self.gcode.run_script_from_command(cmd_str)

                gcmd.respond_info(
                    "td%d result: amp=%.4f, phase1=%.3f, phase2=%.3f"
                    % (tdx, final_amp, final_phase1, final_phase2))
            else:
                direction = directions[0]
                phase_idx = int(not (direction ^ self.dir_inverted)) + 1
                configfile.set('mclib %s' % self.stepper,
                               'td%d_amp' % tdx,
                               "%.4f" % amp_by_dir[direction])
                configfile.set('mclib %s' % self.stepper,
                               'td%d_phase%d' % (tdx, phase_idx),
                               "%.3f" % phase_by_dir[direction])

                gcmd.respond_info(
                    "td%d result: amp=%.4f, phase%d=%.3f"
                    % (tdx, amp_by_dir[direction],
                       phase_idx, phase_by_dir[direction]))

        self.end_test(gcmd)

        filename = (CSV_DIR + "%s_refine_calibrate-%s.csv"
                    % (self.stepper, time.strftime("%Y%m%d_%H%M%S")))
        csv_header = ["tdx", "dir", "round", "amp", "phase", "residual"]
        self.save_to_csv(filename, results, header=csv_header,
                         format_spec='%.4f')
        gcmd.respond_info(
            "Refine calibration history (%d measurements) saved to %s"
            % (len(results), filename))

        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config\n"
            "file and restart the printer.")

def load_config(config):
    return StepperResonanceTester(config)
