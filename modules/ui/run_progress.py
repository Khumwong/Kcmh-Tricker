from PyQt5.QtWidgets import (
    QWidget, QPushButton, QLineEdit, QApplication, QMainWindow,
    QVBoxLayout, QHBoxLayout, QFrame, QSpacerItem, QSizePolicy,
    QMessageBox, QFileDialog, QProgressBar,
    QLabel, QAction, qApp
    )
from PyQt5.QtCore import Qt, QRect, QRunnable, QObject, pyqtSlot, pyqtSignal, QThreadPool
from PyQt5.QtGui import QIcon
import sys, traceback
# from modules.window import MyWindow
import modules.zaber.connect as zaber_connect
from modules.serial_connect import get_port
from modules.zaber.motion import (apply_steps,
                                  apply_steps_loop,
                                  apply_steps_loop_vel,
                                  get_current_locations
                                  )
import serial
import math
import time
import asyncio
import datetime
import subprocess

force_stop = False
baudrate = 115200
parity = serial.PARITY_NONE
bytesize = serial.EIGHTBITS
stopbits = serial.STOPBITS_ONE

class WorkerSignals(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(dict)
    error = pyqtSignal(tuple)
    step_started = pyqtSignal(float)  # duration_s — emitted on main thread via signal
    
class ProgressWorker(QRunnable):
    def __init__(self, *args, **kwargs):
        super(ProgressWorker, self).__init__()
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        
        # self.kwargs['progress_callback'] = self.signals.progress
            
    @pyqtSlot()
    def run(self):
        try:
            # trigger_f_bin = self.kwargs['trigger_f_bin']
            # trigger_f_byte_list = [int(trigger_f_bin[:-8], 2).to_bytes(1, 'big'), int(trigger_f_bin[-8:], 2).to_bytes(1, 'big')]
            # alpide_delay = self.kwargs['alpide_delay']
            # alpide_delay_byte = int(alpide_delay, 2).to_bytes(1, 'big')
            # ser = serial.Serial(port=get_port("fpga"), baudrate=baudrate, parity=parity,
            #                 bytesize=bytesize, stopbits=stopbits, timeout=1)
            # byte_start_list = [b'\x00', b'\x01', b'\x00', b'\x00', b'\x00', b'\x00', alpide_delay_byte, trigger_f_byte_list[0],
            #         trigger_f_byte_list[1]]
            # byte_start_list = [b'\x01', b'\x00', b'\x00', b'\x00', b'\x00', alpide_delay_byte, trigger_f_byte_list[0],
            #         trigger_f_byte_list[1]]
            # for b in byte_start_list:
            #     self.kwargs['ser'].write(b)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.kwargs['event_loop'] = loop
            def ser_write(b):
                if self.kwargs['ser'] is None:
                    return
                try:
                    self.kwargs['ser'].write(b)
                except Exception:
                    try:
                        self.kwargs['ser'].close()
                    except Exception:
                        pass
                    for _ in range(5):
                        try:
                            self.kwargs['ser'] = serial.Serial(
                                port=get_port("fpga"), baudrate=baudrate,
                                parity=parity, bytesize=bytesize, stopbits=stopbits, timeout=1)
                            self.kwargs['ser'].write(b)
                            # sync กลับไปที่ RunWidget._ser เพื่อให้ kill_beam_action ใช้ port ใหม่ได้
                            self.kwargs['window']._ser = self.kwargs['ser']
                            break
                        except Exception:
                            time.sleep(0.5)

            def log_gate(state):
                try:
                    w = self.kwargs.get('window')
                    if w is not None:
                        w.log_gate_event(state, locs[0], locs[1], locs[2])
                except Exception:
                    pass

            step_current_datetime = datetime.datetime.now()
            value = 0
            step = 1
            locs = self.kwargs['locs']
            ser_write(b'\xFE')
            log_gate("OPEN")
            self.signals.step_started.emit(self.args[1])
            while True:
                time.sleep(0.05)
                _has_conn = self.kwargs['conn'] is not None
                if force_stop:
                    if _has_conn:
                        _vels = self.kwargs.get('velocities')
                        if _vels:
                            locs = apply_steps_loop_vel(self.kwargs['conn'], self.kwargs['steps'], _vels, self.kwargs['event_loop'])
                        else:
                            locs = apply_steps_loop(self.kwargs['conn'], self.kwargs['steps'], self.kwargs['event_loop'])
                    _sig = {"type": "progress", "value": 1000}
                    if _has_conn:
                        _sig['locs'] = locs
                    self.signals.progress.emit(_sig)
                    ser_write(b'\xEF')
                    log_gate("CLOSE")
                    break

                elapsed = (datetime.datetime.now() - step_current_datetime).total_seconds()
                if elapsed > self.args[1]:
                    ser_write(b'\xEF')
                    log_gate("CLOSE")
                    if _has_conn:
                        _vels = self.kwargs.get('velocities')
                        if _vels:
                            locs = apply_steps_loop_vel(self.kwargs['conn'], self.kwargs['steps'], _vels, self.kwargs['event_loop'])
                        else:
                            locs = apply_steps_loop(self.kwargs['conn'], self.kwargs['steps'], self.kwargs['event_loop'])
                    _sig = {"type": "step", "value": step}
                    if _has_conn:
                        _sig['locs'] = locs
                    self.signals.progress.emit(_sig)
                    step += 1
                    step_current_datetime = datetime.datetime.now()
                    if step > self.args[2]:
                        break
                    ser_write(b'\xFE')
                    log_gate("OPEN")
                    self.signals.step_started.emit(self.args[1])
                else:
                    new_val = int(((step - 1) + elapsed / self.args[1]) / self.args[2] * 1000)
                    if new_val != value:
                        value = new_val
                        _sig = {"type": "progress", "value": value}
                        if _has_conn:
                            _sig['locs'] = locs
                        self.signals.progress.emit(_sig)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        finally:
            self.signals.finished.emit()
            
# class StepWorker(QRunnable):
#     def __init__(self, *args, **kwargs):
#         super(StepWorker, self).__init__()
#         self.args = args
#         self.kwargs = kwargs
#         self.signals = WorkerSignals()
        
#     @pyqtSlot()
#     def run(self):
#         try:
#             current_time = datetime.datetime.now()
#             value = 0
#             while True:
#                 if value == self.args[1]:
#                     break
#                 if (datetime.datetime.now() - current_time).total_seconds() > self.args[0]:
#                     value += 1
#                     self.signals.progress.emit(value)     
#                     current_time = datetime.datetime.now()          
#         except:
#             traceback.print_exc()
#             exctype, value = sys.exc_info()[:2]
#             self.signals.error.emit((exctype, value, traceback.format_exc()))
#         finally:
#             self.signals.finished.emit()

def _rp_log(msg):
    try:
        import modules.sim as _sim
        if _sim._log is not None:
            _sim._log.info(f"[RunProgress] {msg}")
            return
    except Exception:
        pass
    print(f"[RunProgress] {msg}")

class RunProgress(QObject):
    """Run controller — ไม่มี dialog ของตัวเอง ใช้ widgets ที่ส่งมาจาก run.py"""
    def __init__(self, window, progress_bar, run_btn, stop_btn, ph_locs):
        super().__init__()
        _rp_log("__init__")
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        self._window = window
        self._ser = window._ser
        self._is_running = True
        self._threadpool = QThreadPool()
        # widgets live in run.py's progress section
        self._progress_bar = progress_bar
        self._run_btn = run_btn
        self._stop_btn = stop_btn
        self._ph_locs = ph_locs
        # reset state
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat('')
        self._run_btn.setEnabled(False)
        self._run_btn.setText("Waiting for ITS3...")
        self._stop_btn.setEnabled(False)
        # disconnect old connections before re-connecting
        try:
            self._run_btn.clicked.disconnect()
        except TypeError:
            pass
        try:
            self._stop_btn.clicked.disconnect()
        except TypeError:
            pass
        self._run_btn.clicked.connect(self._on_run_clicked)
        self._stop_btn.clicked.connect(self.force_stop)
        # poll rc.log รอ ITS3 พร้อม
        from PyQt5.QtCore import QTimer as _QTimer
        import os as _os
        self._rc_log_path = _os.path.expanduser("~/eudaq2/user/ITS3/misc/rc.log")
        self._rc_poll_timer = _QTimer()
        self._rc_poll_timer.setInterval(500)
        self._rc_poll_timer.timeout.connect(self._poll_its3_ready)
        self._rc_poll_timer.start()
        _rp_log("__init__ done")

    def _poll_its3_ready(self):
        import os as _os
        try:
            if not _os.path.exists(self._rc_log_path):
                return
            with open(self._rc_log_path, "r", errors="replace") as f:
                content = f.read()
            if "StartRun" in content:
                self._rc_poll_timer.stop()
                self._run_btn.setEnabled(True)
                _qa = getattr(getattr(self._window, '_window', None), '_qa_mode', False)
                self._run_btn.setText("Start Acquisition" if _qa else "Run")
                from PyQt5.QtWidgets import QApplication as _QApp
                _QApp.beep()
                try:
                    self._window._window._run_widget._show_toast(
                        "ITS3 Ready ✓", "Run can now be started")
                except Exception:
                    pass
        except Exception:
            pass
            
    def force_stop(self):
        global force_stop
        _rp_log("button: Stop pressed")
        force_stop = True
        # ถ้ายังรอ beam_on_signal อยู่ (worker ยังไม่เริ่ม) ให้ยกเลิกทันที
        _ctrl = getattr(self, '_waiting_ctrl', None)
        if _ctrl is not None:
            try:
                _ctrl.beam_on_signal.disconnect(self._start_worker)
            except Exception:
                pass
            self._waiting_ctrl = None
            self._is_running = False
            if self._conn is not None:
                self._conn.close()
            self._window.stop_run()
        
    def update_progress(self, value):
        if value['type'] == 'step':
            step = min(value['value'], self._num_step_loops)
            self._progress_bar.setFormat("{}/{}".format(step, self._num_step_loops))
            self._progress_bar.setValue(int(step * 1000 / self._num_step_loops))
            # force ITS3 snapshot at end of each loop
            try:
                self._window._terminal_widget.force_snapshot()
            except Exception:
                pass
            # sync MU ใน Control Room ตาม loop ที่เสร็จแล้ว
            try:
                import modules.sim as _sim
                _sim.control_room.set_mu_by_step(step, self._num_step_loops)
            except (ImportError, AttributeError):
                pass
        else:
            self._progress_bar.setValue(value['value'])
        if 'locs' in value:
            self._window._window._run_widget.set_ph_loc_full(
                ["{:.2f}".format(l) for l in value['locs']])
            self._locs = value['locs']
            self._ph_locs[0].setText("X: " + self._window._ph_x_label.text() + " mm")
            self._ph_locs[1].setText("Y: " + self._window._ph_y_label.text() + " mm")
            self._ph_locs[2].setText("R: " + self._window._ph_r_label.text() + " degree")
    
    def progress_finish(self):
        global force_stop
        force_stop = False
        self._is_running = False
        if self._conn is not None:
            try:
                locs = get_current_locations(self._conn)
                self._window._window._run_widget.set_ph_loc_full(
                    [f"{locs[0]:.2f}", f"{locs[1]:.2f}", f"{locs[2]:.2f}"])
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
        self._window.stop_run()

    def _on_step_started(self, duration_s):
        try:
            import modules.sound as _sound
            import os
            _SOUND_DIR = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sound")
            _sound.play(os.path.join(_SOUND_DIR, "kill-beam.mp4"),
                        stop_after_ms=int(duration_s * 1000))
        except Exception:
            pass

    def _on_run_clicked(self):
        _rp_log("button: Run clicked")
        self._run_btn.setEnabled(False)
        self.start_with_thread()

    def start_with_thread(self):
        self._num_step_loops = int(self._window._line_edits["Loops"].text())
        expose_time = (float(self._window._line_edits["Exposure time (ms)"].text()) +
                       float(self._window._line_edits["Beam delay (ms)"].text())
                       )*int(self._window._line_edits["Loops"].text())*1e-3
        time_step = expose_time/self._num_step_loops
        time_prog_size = expose_time/(1000)
        _qa_mode = getattr(getattr(self._window, '_window', None), '_qa_mode', False)
        if _qa_mode:
            self._zaber_steps = [0.0, 0.0, 0.0]
            self._conn = None
            self._locs = [0.0, 0.0, 0.0]
        else:
            self._zaber_steps = [
                float(self._window._line_edits["X step (mm)"].text()),
                float(self._window._line_edits["Y step (mm)"].text()),
                float(self._window._line_edits["R step (degree)"].text())
            ]
            self._conn = zaber_connect.connect(get_port("zaber"))
            self._locs = [
                float(self._window._ph_x_label.text()),
                float(self._window._ph_y_label.text()),
                float(self._window._ph_r_label.text())
            ]
            self._zaber_velocities = None  # Treatment mode ใช้ max speed เสมอ
        self._progress_bar.setFormat("0/{}".format(self._num_step_loops))
        self._event_loop = asyncio.get_event_loop()

        _qa_mode = getattr(getattr(self._window, '_window', None), '_qa_mode', False)

        # -- sim + Treatment: แจ้ง Control Room และรอ Beam ON --
        if not _qa_mode:
            try:
                import modules.sim as _sim
                if _sim._log is not None and _sim.control_room is not None:
                    _ctrl = _sim.control_room
                    _ctrl.start_mu_timer(
                        exposure_ms=float(self._window._line_edits["Exposure time (ms)"].text()),
                        loops=int(self._window._line_edits["Loops"].text())
                    )
                    self._run_btn.setEnabled(False)
                    self._stop_btn.setEnabled(True)
                    if _ctrl._beam_active:
                        _rp_log("beam already ON — starting worker immediately")
                        self._start_worker()
                    else:
                        self._waiting_ctrl = _ctrl
                        _ctrl.beam_on_signal.connect(self._start_worker)
                        _rp_log("waiting for Control Room BEAM ON...")
                    return
            except (ImportError, AttributeError):
                pass

        # ── QA mode หรือ non-sim Treatment: เริ่ม worker ทันที ──────────
        self._start_worker()

    def _start_worker(self):
        global force_stop
        force_stop = False
        from datetime import datetime as _dt
        _launch_t = getattr(self._window, '_launch_time', None)
        _elapsed = f"{time.monotonic() - _launch_t:.2f}s" if _launch_t else "?"
        print(f"[RUN START] {_dt.now().strftime('%H:%M:%S.%f')[:-3]}  (+{_elapsed} from Launch Default)")
        self._window._acq_start_time = time.monotonic()
        _rp_log("_start_worker called — starting ProgressWorker thread")
        # เริ่ม velocity (ถ้าตั้งค่าไว้) พร้อมกับ acquisition
        try:
            self._window._vel_start_run()
        except Exception as e:
            _rp_log(f"vel_start_run error: {e}")
        # เริ่ม MU tracker เมื่อกด Run (ไม่ใช่ตอน Launch)
        try:
            if getattr(self._window, '_mu_tracker', None):
                self._window._mu_tracker.start()
        except Exception as e:
            _rp_log(f"MuTracker start error: {e}")
        expose_time = (float(self._window._line_edits["Exposure time (ms)"].text()) +
                       float(self._window._line_edits["Beam delay (ms)"].text())
                       ) * int(self._window._line_edits["Loops"].text()) * 1e-3
        _qa = self._window._window._qa_mode
        # QA with an actual velocity sweep: run until the stage reaches the target
        # (force_stop set by _vel_start_run). QA static / Treatment: time-based stop.
        def _fnum(w):
            try:
                return float(w.text() or 0)
            except (ValueError, AttributeError):
                return 0.0
        _qa_sweep = _qa and any(
            _fnum(vw) > 0 and pw.text().strip() != ""
            for vw, pw in ((self._window._vel_x_edit, self._window._qa_pos_x_edit),
                           (self._window._vel_y_edit, self._window._qa_pos_y_edit),
                           (self._window._vel_r_edit, self._window._qa_pos_r_edit))
        )
        if _qa_sweep:
            time_step = 86400.0
            time_prog_size = 86400.0
        elif _qa:
            # QA static: one continuous acquisition window of (exp+delay)*Loops,
            # not Loops chopped windows — no pointless gate toggling / sound retrigger
            self._num_step_loops = 1
            self._progress_bar.setFormat("0/1")
            time_step = expose_time
            time_prog_size = expose_time
        else:
            time_step = expose_time / self._num_step_loops
            time_prog_size = expose_time / 1000
        self._start_time = datetime.datetime.now()
        # FPGA gate (\xFE) fires for real starting here, not at Launch — anchor
        # the gating log's clock to this moment.
        self._window._run_start_epoch = time.time()
        self._is_running = True
        self._stop_btn.setEnabled(True)
        try:
            self._window._inline_cancel_btn.setEnabled(False)
        except AttributeError:
            pass
        progress_worker = ProgressWorker(time_prog_size, time_step, self._num_step_loops, conn=self._conn,
                                         steps=self._zaber_steps, velocities=getattr(self, '_zaber_velocities', None),
                                         event_loop=self._event_loop,
            trigger_f_bin=bin(int(self._window._line_edits["Trigger Freq. (Hz)"].text())).lstrip('0b').zfill(16),
            alpide_delay=bin(int(self._window._line_edits["Beam delay (ms)"].text())).lstrip('0b').zfill(8),
            locs=self._locs, ser=self._ser, window=self._window
            )
        progress_worker.signals.progress.connect(self.update_progress)
        progress_worker.signals.finished.connect(self.progress_finish)
        progress_worker.signals.step_started.connect(self._on_step_started)
        self._threadpool.start(progress_worker)