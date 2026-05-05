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
    # progress = pyqtSignal(int)
    
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

            step_current_datetime = datetime.datetime.now()
            current_time = datetime.datetime.now()
            value = 0
            step = 1
            ser_write(b'\xFE')
            locs = self.kwargs['locs']
            while True:
                if force_stop:
                    locs = apply_steps_loop(self.kwargs['conn'], self.kwargs['steps'], self.kwargs['event_loop'])
                    self.signals.progress.emit({"type": "progress", "value": 1000, "locs": locs})
                    ser_write(b'\xEF')
                    break

                if (datetime.datetime.now() - step_current_datetime).total_seconds() > self.args[1]:
                    ser_write(b'\xEF')
                    locs = apply_steps_loop(self.kwargs['conn'], self.kwargs['steps'], self.kwargs['event_loop'])
                    self.signals.progress.emit({"type": "step", "value": step, "locs": locs})
                    value = int(step*1000/self.args[2])
                    step += 1
                    step_current_datetime = datetime.datetime.now()
                    current_time = datetime.datetime.now()
                    if step > self.args[2]:
                        break
                    ser_write(b'\xFE')
                elif (datetime.datetime.now() - current_time).total_seconds() > self.args[0]:
                    value += 1
                    self.signals.progress.emit({"type": "progress", "value": value, "locs": locs})
                    current_time = datetime.datetime.now()    
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
        _sim._log.info(f"[RunProgress] {msg}")
    except Exception:
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
                self._run_btn.setText("Run")
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
        self._conn.close()
        self._window.stop_run()
    
        
    def _on_run_clicked(self):
        _rp_log("button: Run clicked")
        self.start_with_thread()

    def start_with_thread(self):
        self._num_step_loops = int(self._window._line_edits["Loops"].text())
        expose_time = (float(self._window._line_edits["Exposure time (ms)"].text()) +
                       float(self._window._line_edits["Beam delay (ms)"].text())
                       )*int(self._window._line_edits["Loops"].text())*1e-3
        time_step = expose_time/self._num_step_loops
        time_prog_size = expose_time/(1000)
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
        self._progress_bar.setFormat("0/{}".format(self._num_step_loops))
        self._event_loop = asyncio.get_event_loop()

        # -- sim: แจ้ง Control Room ให้อัพเดต MU params และ connect signal --
        try:
            import modules.sim as _sim
            _rp_log(f"sim module found, control_room={_sim.control_room}")
            _ctrl = _sim.control_room
            _ctrl.start_mu_timer(
                exposure_ms=float(self._window._line_edits["Exposure time (ms)"].text()),
                loops=int(self._window._line_edits["Loops"].text())
            )
            # ไม่เรียก _ctrl.reset() ที่นี่ — reset ถูกเรียกใน launch_eudaq() แล้ว
            self._run_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            if _ctrl._beam_active:
                # beam เปิดอยู่แล้ว (กด Beam On ไปก่อน) → เริ่ม worker ทันที
                _rp_log("beam already ON — starting worker immediately")
                self._start_worker()
            else:
                # รอ Control Room กด Beam On ก่อน
                _ctrl.beam_on_signal.connect(self._start_worker)
                _rp_log("waiting for Control Room BEAM ON...")
            return
        except (ImportError, AttributeError) as e:
            _rp_log(f"sim not available ({e}), starting immediately")
        # ── non-sim: เริ่ม worker ทันที ──────────────────────────────────
        self._start_worker()

    def _start_worker(self):
        global force_stop
        force_stop = False
        _rp_log("_start_worker called — starting ProgressWorker thread")
        # เริ่ม MU tracker เมื่อกด Run (ไม่ใช่ตอน Launch)
        try:
            if getattr(self._window, '_mu_tracker', None):
                self._window._mu_tracker.start()
        except Exception as e:
            _rp_log(f"MuTracker start error: {e}")
        expose_time = (float(self._window._line_edits["Exposure time (ms)"].text()) +
                       float(self._window._line_edits["Beam delay (ms)"].text())
                       ) * int(self._window._line_edits["Loops"].text()) * 1e-3
        time_step = expose_time / self._num_step_loops
        time_prog_size = expose_time / 1000
        self._start_time = datetime.datetime.now()
        self._is_running = True
        self._stop_btn.setEnabled(True)
        try:
            self._window._inline_cancel_btn.setEnabled(False)
        except AttributeError:
            pass
        progress_worker = ProgressWorker(time_prog_size, time_step, self._num_step_loops, conn=self._conn,
                                         steps=self._zaber_steps, event_loop=self._event_loop,
            trigger_f_bin=bin(int(self._window._line_edits["Trigger Freq. (Hz)"].text())).lstrip('0b').zfill(16),
            alpide_delay=bin(int(self._window._line_edits["Beam delay (ms)"].text())).lstrip('0b').zfill(8),
            locs=self._locs, ser=self._ser, window=self._window
            )
        progress_worker.signals.progress.connect(self.update_progress)
        progress_worker.signals.finished.connect(self.progress_finish)
        self._threadpool.start(progress_worker)