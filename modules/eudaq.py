# modules/eudaq.py
import subprocess
import os
import signal
from os import path
import time


VCASNS = ["54", "55", "56", "56", "57", "55"]
VCASN2S = ["66", "67", "68", "68", "69", "67"]

SERIALS = [
    "DAQ-000904250102082C",
    "DAQ-000904250102061F",
    "DAQ-0009042501141327",
    "DAQ-0009042501141214",
    "DAQ-0009042501020714",
    "DAQ-0009042501141325"
        ]
EUDAQ_DIR = "/home/kobdaj/eudaq2/user/ITS3/misc/"

def gen_its3_ini(num_alpides):
    alpide_names = [f"ALPIDE_plane_{i}" for i in range(num_alpides)]
    with open(path.join(EUDAQ_DIR, 'ITS3_auto_gen.ini'), 'w') as f:
        f.write("[RunControl]\n")
        f.write(f"dataproducers  = {','.join(alpide_names)}\n")
        f.write("loggers     = \n")
        f.write("collectors  = dc\n")
        f.write("configs     = ITS3-align-planes-Vbb0-gen.conf\n")
        f.write("\n")
        f.write("[DataCollector.dc]\n")
        f.write(f"dataproducers  = {','.join(alpide_names)}\n")
        f.write("\n")

        for i in range(num_alpides):
            f.write(f"[Producer.ALPIDE_plane_{i}]\n")
            f.write(f"serial      = {SERIALS[i]}\n")
            f.write(f"plane       = {i}\n")
            f.write(f"triggermode = {'primary' if i == 0 else 'replica'}\n")
            f.write("\n") 

def gen_its3_conf(num_alpides, num_evt, strobe_length, i_threshold, outpath):
    alpide_names = [f"ALPIDE_plane_{i}" for i in range(num_alpides)]
    with open(path.join(EUDAQ_DIR, 'ITS3-align-planes-Vbb0-gen.conf'), 'w') as f:
        f.write("[RunControl]\n")
        f.write("EUDAQ_CTRL_PRODUCER_LAST_START = ALPIDE_plane_0\n")
        f.write("EUDAQ_CTRL_PRODUCER_FIRST_STOP = ALPIDE_plane_0\n")
        f.write(f"NEVENTS    = {num_evt}\n")
        f.write("\n")

        for i in range(num_alpides):
            f.write(f"[Producer.ALPIDE_plane_{i}]\n")
            # if i == 0:
            #     f.write(f"fixedbusy     = 80000\n")
            #     f.write(f"minspacing    =  8000\n")
            f.write("EUDAQ_DC      = dc\n")
            f.write(f"EUDAQ_ID      = {i}\n")
            f.write("CHIPID        = 16\n")
            f.write("VCLIP         = 0\n")
            f.write("IDB           = 29\n")
            f.write(f"STROBE_LENGTH = {strobe_length}\n")
            f.write(f"ITHR          = {i_threshold}\n")
            f.write(f"VCASN         = {VCASNS[i]}\n")
            f.write(f"VCASN2        = {VCASN2S[i]}\n")
            f.write("\n")

        f.write(f"[DataCollector.dc]\n")
        f.write(f"EUDAQ_FW = native\n")
        # output path — raw files go in <outpath>/raw/ to mirror the server layout
        #out_path = '/home/directory'
        raw_dir = path.join(outpath, 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        f.write(f"EUDAQ_FW_PATTERN = {path.join(raw_dir, 'run$6R_$12D$X')}\n")

def _wait(seconds, pump, until=None):
    """Sleep up to `seconds`, but keep the Qt event loop turning if `pump` is given
    (pass QApplication.processEvents) so the embedded terminal keeps polling and the
    UI does not freeze during the stop sequence. Returns early once `until()` is true."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if until is not None and until():
            return
        if pump is not None:
            try:
                pump()
            except Exception:
                pass
        time.sleep(0.05 if pump is not None else 0.1)


_EUDAQ_PROCS = ('ITS3RunControl.py', 'ALPIDEProducer.py', 'ITS3DataCollector.py')


def _pkill_eudaq():
    """Reap any EUDAQ python process that outlived its tmux pane — orphan producers
    hold the ALPIDE USB and make the next run's DataCollector hang at RUNNING."""
    for name in _EUDAQ_PROCS:
        subprocess.run(['pkill', '-9', '-f', name], capture_output=True)


def stop(pid, pump=None, until_done=None):
    _wait(3, pump)                                         # settle before 'T'
    subprocess.run(['tmux', 'send-keys', '-t', 'ITS3', 'T'])
    # wait for RunControl to reach TERMINATED (files are closed by then). It
    # self-times-out at 13 s on a slow DataCollector (ITS3RunControl.wait_replicas)
    # and then Terminate() needs ~2 s to propagate — allow 18 s, cut short as soon
    # as the terminal has frozen on the TERMINATED frame.
    _wait(2, pump)
    _wait(18, pump, until=until_done)
    subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'], capture_output=True)
    time.sleep(0.3)
    _pkill_eudaq()
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        pass

def default_run(qt_args, outpath):
    start_sh = "ITS3start_auto.sh"
    start_sh_gen = "ITS3start_auto_gen.sh"
    with open(path.join(EUDAQ_DIR, start_sh), 'r') as f:
        lines = f.readlines()
    with open(path.join(EUDAQ_DIR, start_sh_gen), 'w') as f:
        for line in lines:
            if "{num_alpides}" in line:
                f.write(line.replace("{num_alpides}", qt_args["num_alpides"].text()))
            else:
                f.write(f"{line}")
    eudaq_dir = EUDAQ_DIR
    # a lingering session from the previous run makes ITS3start's `tmux new-session`
    # fail (the script then exits and no producers start); orphan producers hold the
    # ALPIDE USB so the new DataCollector hangs at RUNNING. Start from a clean slate.
    subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'], capture_output=True)
    _pkill_eudaq()
    time.sleep(0.5)
    gen_its3_ini(int(qt_args["num_alpides"].text()))
    gen_its3_conf(int(qt_args["num_alpides"].text()), int(qt_args["num_events"].text()), int(qt_args["strobe"].text()),
                   int(qt_args["ithr"].text()), outpath)
    # clear rc.log ก่อน start ใหม่ เพื่อไม่ให้ poll เจอ log เก่า
    rc_log = path.join(EUDAQ_DIR, "rc.log")
    try:
        open(rc_log, 'w').close()
    except Exception:
        pass
    # รัน startup script แบบ headless (script จะสร้าง tmux session ITS3 เอง)
    command = f"cd {eudaq_dir} && bash ./{start_sh_gen}"
    process = subprocess.Popen(['bash', '-c', command])
    return process.pid
    
_ALPIDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'alpide')

class _FirmwareWorker(object):
    """รัน alpide-daq-program ใน QThread — emit line_ready / finished"""
    def __new__(cls, fx3, fpga):
        from PyQt5.QtCore import QThread, pyqtSignal

        class _Worker(QThread):
            line_ready = pyqtSignal(str)
            finished_ok = pyqtSignal(bool)

            def __init__(self, fx3, fpga):
                super().__init__()
                self._fx3 = fx3
                self._fpga = fpga
                self._proc = None
                self._cancelled = False
                self.success = False
                self.timed_out = False

            def run(self):
                try:
                    self._proc = subprocess.Popen(
                        ["alpide-daq-program", f"--fx3={self._fx3}", f"--fpga={self._fpga}", "--all"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                    )
                except Exception as e:
                    self.line_ready.emit(f"ERROR: {e}")
                    self.finished_ok.emit(False)
                    return
                # เผื่อโดน cancel ก่อน Popen จะเสร็จ
                if self._cancelled:
                    self._kill()
                for line in self._proc.stdout:
                    self.line_ready.emit(line.rstrip())
                self._proc.wait()
                self.success = self._proc.returncode == 0 and not self._cancelled
                self.finished_ok.emit(self.success)

            def _kill(self):
                p = self._proc
                if p is None or p.poll() is not None:
                    return
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()

            def cancel(self, timed_out=False):
                """ฆ่า alpide-daq-program — ถ้าไม่ฆ่ามันจะเหลือเป็น orphan
                ค้างใน select() รอ udev event ตลอดกาล (เรียกจาก main thread ได้)"""
                if self._cancelled:
                    return
                self._cancelled = True
                self.timed_out = timed_out
                self._kill()

        return _Worker(fx3, fpga)

FIRMWARE_TIMEOUT_S = 180


def install_firmware_auto(parent_widget=None, timeout_s=FIRMWARE_TIMEOUT_S):
    from PyQt5.QtWidgets import QMessageBox
    from modules.ui.firmware_toast import FirmwareToast

    fx3  = os.path.join(_ALPIDE_DIR, 'fx3.img')
    fpga = os.path.join(_ALPIDE_DIR, 'fpga-v1.0.0.bit')

    missing = [f for f in [fx3, fpga] if not os.path.isfile(f)]
    if missing:
        QMessageBox.warning(
            parent_widget,
            "Firmware Files Not Found",
            "Firmware files missing:\n" + "\n".join(missing) + "\n\n"
            f"Copy fx3.img and fpga-v1.0.0.bit to:\n{_ALPIDE_DIR}"
        )
        return False

    toast = FirmwareToast(parent=parent_widget)
    worker = _FirmwareWorker(fx3, fpga)
    worker.line_ready.connect(toast.append_line)
    worker.finished_ok.connect(toast.set_done)
    toast.cancelled.connect(lambda: worker.cancel())
    toast.timed_out.connect(lambda: worker.cancel(timed_out=True))

    worker.start()
    toast.start_timeout(timeout_s)
    toast.show_centered(parent_widget)
    toast.exec()

    # กัน orphan ทุกทาง — ถ้า dialog ปิดไปโดย proc ยังไม่ตาย
    worker.cancel()
    worker.wait(5000)

    if worker.timed_out:
        QMessageBox.warning(
            parent_widget,
            "Firmware Install Timed Out",
            f"ALPIDE firmware install ไม่จบภายใน {timeout_s} วินาที\n\n"
            "บอร์ด DAQ น่าจะไม่ re-enumerate กลับมาหลังโหลด fx3.img\n"
            "ลองถอดไฟ USB hub + บอร์ด DAQ แล้วเสียบใหม่ จากนั้นเช็คด้วย:\n"
            "    lsusb | grep -E \"04b4|1556\"\n\n"
            "ควรเห็นบอร์ดครบ 6 ตัวก่อนลองใหม่"
        )
    return worker.success

def monitor(filepath):
    std_exc = "/home/kobdaj/eudaq2/bin/StdEventMonitor"
    command = f'gnome-terminal -- bash -c "{std_exc} -d {filepath}; exec bash"'
    process = subprocess.Popen(command, shell=True)
