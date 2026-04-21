# modules/sim.py
# Simulation mode — patches all hardware modules so the app runs without devices.
# Usage: python3 main.py --sim

import asyncio
import os
import logging
from datetime import datetime

# ---------------------------------------------------------------------------
# Sim logger — เขียน log ไปที่ output/sim/sim_YYYYMMDD_HHMMSS.log
# ---------------------------------------------------------------------------

def _make_sim_logger():
    sim_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "sim")
    os.makedirs(sim_dir, exist_ok=True)
    log_path = os.path.join(sim_dir, datetime.now().strftime("sim_%Y%m%d_%H%M%S.log"))

    logger = logging.getLogger("sim")
    logger.setLevel(logging.DEBUG)

    # file handler
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                                      datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)

    # console handler (แสดงใน terminal ด้วย)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[SIM] %(message)s"))
    logger.addHandler(ch)

    logger.info(f"Sim log started → {log_path}")
    return logger, log_path

_log, sim_log_path = _make_sim_logger()

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_originals   = {}   # เก็บ original functions ก่อน patch
main_window  = None  # reference ถึง MyWindow (set จาก main.py)
control_room = None  # reference ถึง ControlRoomWindow (set จาก main.py)


# ---------------------------------------------------------------------------
# Mock Zaber objects
# ---------------------------------------------------------------------------

class _MockAxis:
    def __init__(self, positions, idx):
        self._positions = positions
        self._idx = idx

    def get_position(self, unit=None):
        return self._positions[self._idx]

    def home_async(self):
        self._positions[self._idx] = 0.0
        return _noop()

    def move_absolute_async(self, pos, unit=None):
        self._positions[self._idx] = float(pos)
        return _noop()

    def move_relative(self, step, unit=None):
        self._positions[self._idx] += float(step)

    def move_relative_async(self, step, unit=None):
        self._positions[self._idx] += float(step)
        return _noop()


class _MockDevice:
    def __init__(self, positions, idx):
        self._positions = positions
        self._idx = idx

    def identify(self):
        pass

    def get_axis(self, n):
        return _MockAxis(self._positions, self._idx)


class MockZaberConnection:
    """Fake Zaber connection ที่ simulate X/Y/R motor stages"""
    def __init__(self):
        self._positions = [0.0, 0.0, 0.0]

    def get_device(self, idx):
        return _MockDevice(self._positions, idx - 1)

    def close(self):
        pass


async def _noop_coro():
    pass


def _noop():
    return _noop_coro()


# Shared mock connection (keeps position state across calls)
_mock_conn = MockZaberConnection()


# ---------------------------------------------------------------------------
# Mock serial
# ---------------------------------------------------------------------------

class _MockSerial:
    """Fake serial port — silently discards writes"""
    def __init__(self, *args, **kwargs):
        pass

    def write(self, data):
        _log.info(f"FPGA write: 0x{data.hex().upper()}")

    def close(self):
        _log.debug("FPGA serial closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Patch function
# ---------------------------------------------------------------------------

def apply_sim():
    """Monkey-patch all hardware modules to run in simulation mode."""
    import serial
    import modules.serial_connect as sc
    import modules.fpga.connect as fpga
    import modules.alpide as alpide
    import modules.zaber.connect as zaber_connect
    import modules.zaber.motion as motion
    import modules.eudaq as eudaq

    # -- save originals (first call only) ------------------------------------
    if not _originals:
        import modules.window as _w
        import modules.ui.run as _r
        import modules.ui.phantom as _p
        import modules.ui.run_progress as _rp
        import main as _m
        _originals.update({
            'serial.Serial':                serial.Serial,
            'sc.get_port':                  sc.get_port,
            'fpga.check_connection':        fpga.check_connection,
            'alpide.found_daqs':            alpide.found_daqs,
            'alpide.is_programmed':         alpide.is_programmed,
            'zaber_connect.connect':        zaber_connect.connect,
            'motion.get_current_locations': motion.get_current_locations,
            'motion.to_home':               motion.to_home,
            'motion.apply_move':            motion.apply_move,
            'motion.apply_step':            motion.apply_step,
            'motion.apply_steps':           motion.apply_steps,
            'motion.apply_steps_loop':      motion.apply_steps_loop,
            'eudaq.default_run':            eudaq.default_run,
            'eudaq.stop':                   eudaq.stop,
            'eudaq.install_firware':        eudaq.install_firware,
            'eudaq.monitor':                eudaq.monitor,
            'eudaq.gen_its3_ini':           eudaq.gen_its3_ini,
            'eudaq.gen_its3_conf':          eudaq.gen_its3_conf,
            'RunWidget.enable_beam':        _r.RunWidget.enable_beam,
            'rp.apply_steps_loop':          _rp.apply_steps_loop,
            'rp.get_current_locations':     _rp.get_current_locations,
        })
        for _mod, _key in [(_w, 'w.get_port'), (_r, 'r.get_port'), (_p, 'p.get_port'),
                            (_rp, 'rp.get_port'), (_m, 'm.get_port')]:
            if hasattr(_mod, 'get_port'):
                _originals[_key] = getattr(_mod, 'get_port')

    # -- serial port detection -----------------------------------------------
    # patch ทั้ง module หลัก และทุก module ที่ทำ "from ... import get_port" ไปแล้ว
    _fake_port = lambda device: f"/dev/ttyUSB_SIM_{device}"
    sc.get_port = _fake_port

    import modules.window as _window_mod
    import modules.ui.run as _run_mod
    import modules.ui.phantom as _ph_mod
    import modules.ui.run_progress as _rp_mod
    import main as _main_mod
    for _mod in (_window_mod, _run_mod, _ph_mod, _rp_mod, _main_mod):
        if hasattr(_mod, "get_port"):
            setattr(_mod, "get_port", _fake_port)

    # -- FPGA ----------------------------------------------------------------
    fpga.check_connection = lambda port: False  # เริ่มต้นเป็น False → ปุ่ม FPGA แดง

    # -- ALPIDE --------------------------------------------------------------
    alpide.found_daqs = lambda: False   # เริ่มต้นเป็น False → ปุ่ม ALPIDE แดง
    alpide.is_programmed = lambda: True

    # -- serial.Serial (used in enable_beam / main cleanup) ------------------
    serial.Serial = _MockSerial

    # -- Zaber connection ----------------------------------------------------
    # เริ่มต้นให้ raise error → check_zaber() คืน False → ปุ่ม Zaber แดง
    def _zaber_disconnected(port):
        raise ConnectionError("Zaber not connected (sim)")
    zaber_connect.connect = _zaber_disconnected

    # -- Zaber motion --------------------------------------------------------
    def _get_loc(conn):
        return tuple(conn.get_device(i + 1).get_axis(1).get_position() for i in range(3))

    def _to_home(conn):
        for i in range(3):
            conn._positions[i] = 0.0
        loc = _get_loc(conn)
        _log.info(f"Zaber home → X={loc[0]:.2f} mm  Y={loc[1]:.2f} mm  R={loc[2]:.2f}°")

    def _apply_move(conn, loc):
        for i, v in enumerate(loc):
            conn._positions[i] = float(v)
        result = _get_loc(conn)
        _log.info(f"Zaber move_absolute → X={result[0]:.2f} mm  Y={result[1]:.2f} mm  R={result[2]:.2f}°")
        return result

    def _apply_step(conn, axis, step):
        axis_name = ["X", "Y", "R"][axis]
        unit = "mm" if axis < 2 else "°"
        conn._positions[axis] += float(step)
        result = _get_loc(conn)
        _log.info(f"Zaber step {axis_name}{step:+.2f}{unit} → X={result[0]:.2f} mm  Y={result[1]:.2f} mm  R={result[2]:.2f}°")
        return result

    def _apply_steps(conn, steps):
        for i, s in enumerate(steps):
            conn._positions[i] += float(s)
        result = _get_loc(conn)
        _log.info(f"Zaber steps {[f'{s:+.2f}' for s in steps]} → X={result[0]:.2f} mm  Y={result[1]:.2f} mm  R={result[2]:.2f}°")
        return result

    motion.get_current_locations = _get_loc
    motion.to_home = _to_home
    motion.apply_move = _apply_move
    motion.apply_step = _apply_step
    motion.apply_steps = _apply_steps
    motion.apply_steps_loop = lambda conn, steps, loop: _apply_steps(conn, steps)

    # -- EUDAQ ---------------------------------------------------------------
    _SIM_SERIALS = [
        "DAQ-000904250102082C",
        "DAQ-000904250102061F",
        "DAQ-0009042501141327",
        "DAQ-0009042501141214",
        "DAQ-0009042501020714",
        "DAQ-0009042501141325",
    ]

    def _sim_default_run(qt_args, outpath):
        import os
        import shutil
        import subprocess
        p = {k: v.text() for k, v in qt_args.items()}
        num_alpides = int(p['num_alpides'])
        _log.info("=" * 50)
        _log.info("RUN START")
        _log.info(f"  Output path      : {outpath}")
        _log.info(f"  ALPIDEs          : {p['num_alpides']}")
        _log.info(f"  Events           : {p['num_events']}")
        _log.info(f"  STROBE           : {p['strobe']}")
        _log.info(f"  I Threshold      : {p['ithr']}")
        _log.info(f"  Energy           : {p['energy']} MeV")
        _log.info(f"  MU               : {p['MU']}")
        _log.info(f"  Current          : {p['current']} nA")
        _log.info(f"  Trigger Freq.    : {p['Trigger Freq. (Hz)']} Hz")
        _log.info(f"  Exposure time    : {p['Exposure time (ms)']} ms")
        _log.info(f"  Beam delay       : {p['Beam delay (ms)']} ms")
        _log.info(f"  Loops            : {p['Loops']}")
        _log.info(f"  X step           : {p['X step (mm)']} mm")
        _log.info(f"  Y step           : {p['Y step (mm)']} mm")
        _log.info(f"  R step           : {p['R step (degree)']} degree")
        total_s = (float(p['Exposure time (ms)']) + float(p['Beam delay (ms)'])) * int(p['Loops']) / 1000
        mu_per_loop = float(p['MU']) / int(p['Loops']) if int(p['Loops']) > 0 else 0
        _log.info(f"  --- Calculated ---")
        _log.info(f"  MU/loop          : {mu_per_loop:.1f}")
        _log.info(f"  Est. total time  : {total_s:.1f} s")
        _log.info("=" * 50)
        os.makedirs(outpath, exist_ok=True)
        fname = os.path.join(outpath, datetime.now().strftime("sim_run_%Y%m%d_%H%M%S.raw"))
        sample = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "sim", "sample.raw")
        if os.path.isfile(sample):
            shutil.copy(sample, fname)
            _log.info(f"Copied sample.raw → {os.path.basename(fname)}")
        else:
            open(fname, "w").close()
            _log.warning("sample.raw not found — created empty file instead")
        # อัพเดต mtime เป็นปัจจุบัน เพื่อให้ get_new_outfile() หาเจอ
        os.utime(fname, None)

        # ── สร้าง tmux session ให้ตรงกับ ITS3start.py:setup_tmux() ─────────────
        sim_script = "/tmp/alpide_sim.py"
        with open(sim_script, "w") as f:
            f.write(
                "import sys, time, random\n"
                "plane  = int(sys.argv[1])\n"
                "serial = sys.argv[2]\n"
                "print(f'[SIM] ALPIDE_plane_{plane} ({serial}) — READY', flush=True)\n"
                "print(f'[SIM] Connecting to {serial}...', flush=True)\n"
                "time.sleep(0.5)\n"
                "print(f'[SIM] ALPIDE_plane_{plane} Connected OK', flush=True)\n"
                "print(f'[SIM] Waiting for Run Control...', flush=True)\n"
                "n = 0\n"
                "try:\n"
                "    while True:\n"
                "        time.sleep(1)\n"
                "        n += random.randint(100, 500)\n"
                "        print(f'[SIM] ALPIDE_plane_{plane} RUNNING — Events: {n}', flush=True)\n"
                "except KeyboardInterrupt:\n"
                "    print(f'[SIM] ALPIDE_plane_{plane} STOPPED', flush=True)\n"
            )

        subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'], capture_output=True)

        # เขียน Run Control sim script (แสดง RUNNING banner + table เหมือน ITS3RunControl.py)
        rc_script = "/tmp/sim_rc.py"
        with open(rc_script, "w") as f:
            f.write(
                "import sys, time, random\n"
                "num_alpides = int(sys.argv[1]) if len(sys.argv) > 1 else 6\n"
                "events = [0] * num_alpides\n"
                "RESET = '\\033[0m'\n"
                "BOLD  = '\\033[1m'\n"
                "GREEN = '\\033[32m'\n"
                "YELLOW= '\\033[33m'\n"
                "CYAN  = '\\033[36m'\n"
                "BG_GW = '\\033[42;37;1m'\n"
                "def render(tick):\n"
                "    arrows = '>>' if tick % 2 == 0 else '  '\n"
                "    print('\\033[2J\\033[H', end='', flush=True)\n"
                "    print(f'{BG_GW}   RUNNING {arrows}   {RESET}')\n"
                "    print()\n"
                "    hdr = f\"{'ALPIDE_plane':<20}  {'STATE':>5}  {'DATA EVT':>10}  {'STRT':>4}  {'CUR':>4}  MESSAGE\"\n"
                "    print(f'{BOLD}{YELLOW}{hdr}{RESET}')\n"
                "    print('\\u2500' * 65)\n"
                "    for i in range(num_alpides):\n"
                "        events[i] += random.randint(100, 500)\n"
                "        print(f'{CYAN}ALPIDE_plane_{i:<7}{RESET}  {\"1\":>5}  {GREEN}{str(events[i]):>10}{RESET}  {\"1\":>4}  {\"1\":>4}  Started')\n"
                "    print(flush=True)\n"
                "try:\n"
                "    render(0)\n"
                "    tick = 0\n"
                "    while True:\n"
                "        time.sleep(1)\n"
                "        tick += 1\n"
                "        render(tick)\n"
                "except KeyboardInterrupt:\n"
                "    pass\n"
            )

        # window "rc" — Run Control  (เหมือน ITS3start.py)
        subprocess.run(['tmux', 'new-session', '-d', '-s', 'ITS3', '-n', 'rc'])
        subprocess.run(['tmux', 'set-option', '-t', 'ITS3', 'pane-border-status', 'top'])
        subprocess.run(['tmux', 'set-option', '-t', 'ITS3', 'pane-border-format',
                        '#P: #{pane_title} (#{pane_pid})'])
        subprocess.run(['tmux', 'select-pane', '-t', 'ITS3:rc', '-T', 'Run Control'])
        subprocess.run(['tmux', 'send-keys', '-t', 'ITS3:rc',
                        f'python3 {rc_script} {num_alpides}', 'Enter'])

        # window "rp" — REF producers (ALPIDE), tiled, 1 pane/sensor  (เหมือน ITS3start.py)
        subprocess.run(['tmux', 'new-window', '-t', 'ITS3', '-n', 'rp'])
        for i in range(1, num_alpides):
            subprocess.run(['tmux', 'split-window', '-t', 'ITS3:rp', '-v'])
            subprocess.run(['tmux', 'select-layout', '-t', 'ITS3:rp', 'tiled'])
        for i in range(num_alpides):
            serial = _SIM_SERIALS[i] if i < len(_SIM_SERIALS) else f"DAQ-SIM{i:04d}"
            subprocess.run(['tmux', 'select-pane', '-t', f'ITS3:rp.{i}',
                            '-T', f'Producer ALPIDE {i}'])
            subprocess.run(['tmux', 'send-keys', '-t', f'ITS3:rp.{i}',
                            f'python3 {sim_script} {i} {serial}', 'Enter'])

        # window "dp" — DUT producers (ว่างในเซ็ตอัพ KCMH)  (เหมือน ITS3start.py)
        subprocess.run(['tmux', 'new-window', '-t', 'ITS3', '-n', 'dp'])

        # window "sp" — Status producers (ว่างในเซ็ตอัพ KCMH)  (เหมือน ITS3start.py)
        subprocess.run(['tmux', 'new-window', '-t', 'ITS3', '-n', 'sp'])

        # window "dc" — Data Collector  (เหมือน ITS3start.py)
        subprocess.run(['tmux', 'new-window', '-t', 'ITS3', '-n', 'dc'])
        subprocess.run(['tmux', 'select-pane', '-t', 'ITS3:dc', '-T', 'Data Collector'])
        subprocess.run(['tmux', 'send-keys', '-t', 'ITS3:dc',
                        "echo '[SIM] ITS3 Data Collector';"
                        "echo '[SIM] Listening for producers...';"
                        "while true; do sleep 60; done",
                        'Enter'])

        # window "log" — EUDAQ Log  (เหมือน ITS3start.py)
        subprocess.run(['tmux', 'new-window', '-t', 'ITS3', '-n', 'log'])
        subprocess.run(['tmux', 'select-pane', '-t', 'ITS3:log', '-T', 'EUDAQ Log'])
        subprocess.run(['tmux', 'send-keys', '-t', 'ITS3:log',
                        "echo '[SIM] euCliLogger -n log -a 55000';"
                        "echo '[SIM] Logger started';"
                        "while true; do sleep 60; done",
                        'Enter'])

        # window "perf" — htop  (เหมือน ITS3start.py)
        subprocess.run(['tmux', 'new-window', '-t', 'ITS3', '-n', 'perf'])
        subprocess.run(['tmux', 'select-pane', '-t', 'ITS3:perf', '-T', 'Performance'])
        subprocess.run(['tmux', 'send-keys', '-t', 'ITS3:perf', 'htop', 'Enter'])

        # เลือก window "rc" ก่อน attach (เหมือน ITS3start.py ที่ switch-client ไปที่ rc)
        subprocess.run(['tmux', 'select-window', '-t', 'ITS3:rc'])

        _log.info("[SIM] tmux ITS3 created — embedded terminal will poll via capture-pane")
        return 0

    def _sim_stop(pid):
        import subprocess
        _log.info(f"EUDAQ run STOP  (pid={pid})")
        subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'], capture_output=True)

    eudaq.default_run = _sim_default_run
    eudaq.stop = _sim_stop
    eudaq.install_firware = lambda: _log.info("Install firmware")
    eudaq.monitor = lambda filepath: _log.info(f"Monitor: {filepath}")
    eudaq.gen_its3_ini = lambda *a, **kw: None
    eudaq.gen_its3_conf = lambda *a, **kw: None

    # -- Auto-enable run controls in sim mode --------------------------------
    import modules.ui.run as _run_mod

    def _sim_enable_beam(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QMessageBox
        if self._enable_checkbox.isChecked():
            if not (self._window._alpide_connect and self._window._zaber_connect and self._window._fpga_connect):
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Warning)
                msg.setText("Not all devices connected")
                msg.setInformativeText("Please connect ALPIDE, Zaber, and FPGA before enabling.")
                msg.setWindowTitle("Warning")
                msg.exec_()
                self._enable_checkbox.setChecked(False)
                return
        self._ser = _MockSerial()
        self._kill_beam_btn.setChecked(False)
        self._stop_auto_kill_sequence()
        if self._enable_checkbox.checkState() == Qt.Checked:
            _log.info("Beam ENABLED")
            has_rsync = bool(self._rsync_addr_edit.text().strip() and self._rsync_path_edit.text().strip())
            self._kill_beam_btn.setEnabled(has_rsync)
            self._launch_eudaq_default.setEnabled(has_rsync)
            if not has_rsync:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Warning)
                msg.setText("rsync destination is empty")
                msg.setInformativeText("Please fill in SSH address and remote path, then click Connect.")
                msg.setWindowTitle("Warning")
                msg.exec_()
            self._window.running(True)
        else:
            from PyQt5.QtWidgets import QMessageBox
            beam_dialog = QMessageBox()
            beam_dialog.setIcon(QMessageBox.Warning)
            beam_dialog.setText("Beam status before disabling?")
            beam_dialog.setInformativeText("กด 'Kill beam' ถ้า beam ยังค้างอยู่\nกด 'Beam หมดแล้ว' ถ้า beam หมดแล้ว")
            beam_dialog.setWindowTitle("Beam check")
            kill_btn = beam_dialog.addButton("Kill beam", QMessageBox.DestructiveRole)
            kill_btn.setStyleSheet("background-color: #c62828; color: white; font-weight: bold; padding: 6px 16px;")
            done_btn = beam_dialog.addButton("Continue", QMessageBox.AcceptRole)
            done_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 16px;")
            cancel_btn = beam_dialog.addButton("Cancel", QMessageBox.RejectRole)
            cancel_btn.setStyleSheet("background-color: #f9a825; color: white; font-weight: bold; padding: 6px 16px;")
            beam_dialog.exec_()
            clicked = beam_dialog.clickedButton()
            if clicked == kill_btn:
                if self._ser:
                    self._ser.write(b'\xFE')
                import modules.sim as _sim_ref
                _cr = _sim_ref.control_room
                if _cr is not None:
                    def _do_disable():
                        try:
                            _cr.beam_off_signal.disconnect(_do_disable)
                        except TypeError:
                            pass
                        _log.info("Beam DISABLED")
                        self._stop_auto_kill_sequence()
                        self._kill_beam_btn.setEnabled(False)
                        self._launch_eudaq_default.setEnabled(False)
                        self._ser = None
                        self._window.running(False)
                    _cr.beam_off_signal.connect(_do_disable)
                    _cr.start_residual_delivery()
                    return
            elif clicked == done_btn:
                pass
            else:
                self._enable_checkbox.blockSignals(True)
                self._enable_checkbox.setChecked(True)
                self._enable_checkbox.blockSignals(False)
                return
            _log.info("Beam DISABLED")
            self._stop_auto_kill_sequence()
            self._kill_beam_btn.setEnabled(False)
            self._launch_eudaq_default.setEnabled(False)
            self._ser = None
            self._window.running(False)

    _run_mod.RunWidget.enable_beam = _sim_enable_beam

    # -- run_progress patches ------------------------------------------------
    # 1) apply_steps_loop / get_current_locations ถูก import โดยตรง → patch namespace
    import modules.ui.run_progress as _rp_mod
    _rp_mod.apply_steps_loop = lambda conn, steps, loop: _apply_steps(conn, steps)
    _rp_mod.get_current_locations = _get_loc

    # 2) closeEvent เรียก tmux → kill session เหมือน mode ปกติ
    def _sim_close_event(self, event):
        import subprocess
        _log.info("RunProgress closed — killing tmux ITS3")
        subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'], capture_output=True)

    _rp_mod.RunProgress.closeEvent = _sim_close_event

    _log.info("=" * 40)
    _log.info("SIM MODE — ไม่ต้องต่ออุปกรณ์จริง")
    _log.info("=" * 40)


# ---------------------------------------------------------------------------
# Hardware mode — restore real hardware (beam ยัง sim ผ่าน Control Room)
# ---------------------------------------------------------------------------

def apply_hw_mode():
    """Restore real hardware connections — beam stays simulated via Control Room."""
    if not _originals:
        _log.warning("apply_hw_mode: no originals saved")
        return

    import serial
    import modules.serial_connect as sc
    import modules.fpga.connect as fpga
    import modules.alpide as alpide
    import modules.zaber.connect as zaber_connect
    import modules.zaber.motion as motion
    import modules.eudaq as eudaq
    import modules.ui.run as _run_mod
    import modules.ui.run_progress as _rp_mod
    import modules.window as _window_mod
    import modules.ui.phantom as _ph_mod
    import main as _main_mod

    serial.Serial                       = _originals['serial.Serial']
    sc.get_port                         = _originals['sc.get_port']
    fpga.check_connection               = _originals['fpga.check_connection']
    alpide.found_daqs                   = _originals['alpide.found_daqs']
    alpide.is_programmed                = _originals['alpide.is_programmed']
    zaber_connect.connect               = _originals['zaber_connect.connect']
    motion.get_current_locations        = _originals['motion.get_current_locations']
    motion.to_home                      = _originals['motion.to_home']
    motion.apply_move                   = _originals['motion.apply_move']
    motion.apply_step                   = _originals['motion.apply_step']
    motion.apply_steps                  = _originals['motion.apply_steps']
    motion.apply_steps_loop             = _originals['motion.apply_steps_loop']
    eudaq.default_run                   = _originals['eudaq.default_run']
    eudaq.stop                          = _originals['eudaq.stop']
    eudaq.install_firware               = _originals['eudaq.install_firware']
    eudaq.monitor                       = _originals['eudaq.monitor']
    eudaq.gen_its3_ini                  = _originals['eudaq.gen_its3_ini']
    eudaq.gen_its3_conf                 = _originals['eudaq.gen_its3_conf']
    _run_mod.RunWidget.enable_beam      = _originals['RunWidget.enable_beam']
    _rp_mod.apply_steps_loop            = _originals['rp.apply_steps_loop']
    _rp_mod.get_current_locations       = _originals['rp.get_current_locations']

    for _mod, _key in [(_window_mod, 'w.get_port'), (_run_mod, 'r.get_port'),
                        (_ph_mod, 'p.get_port'), (_rp_mod, 'rp.get_port'),
                        (_main_mod, 'm.get_port')]:
        if _key in _originals:
            setattr(_mod, 'get_port', _originals[_key])

    _log.info("=" * 40)
    _log.info("HW MODE — ต่ออุปกรณ์จริง (beam ยัง sim)")
    _log.info("=" * 40)

    if main_window is not None:
        main_window.init_connect_devices()


def apply_sim_mode():
    """Re-apply all mocks (กลับมา full sim)."""
    apply_sim()
    _log.info("=" * 40)
    _log.info("SIM MODE — กลับมา mock ทุกอย่าง")
    _log.info("=" * 40)
    if main_window is not None:
        main_window.init_connect_devices()
