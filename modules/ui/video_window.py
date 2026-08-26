import os
import re
import json
import cv2
import subprocess
import numpy as np
from queue import Queue, Empty
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QListWidget, QGroupBox, QFileDialog,
    QMessageBox, QSizePolicy, QSpinBox, QTextEdit, QCheckBox,
    QStackedWidget,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

# video/ directory sits at the project root
VIDEO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'video',
)

ROI_NAMES = ['mu1_roi', 'mu2_roi', 'mu_rate_roi', 'progress_roi']

ROI_COLORS = {
    'mu1_roi':      (255, 100, 0),
    'mu2_roi':      (255, 160, 0),
    'mu_rate_roi':  (0, 80, 255),
    'progress_roi': (220, 220, 0),
}

CONFIG_PATH = os.path.join(VIDEO_DIR, 'config.json')


def _load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    try:
        os.makedirs(VIDEO_DIR, exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def _load_roi_file(path):
    coords = []
    try:
        with open(path) as f:
            for line in f:
                if 'Point' in line:
                    nums = re.findall(r'\d+', line)
                    if len(nums) >= 2:
                        coords.append((int(nums[-2]), int(nums[-1])))
    except FileNotFoundError:
        pass
    return coords


def _frame_to_pixmap(frame, label_w, label_h):
    """Convert BGR numpy frame to QPixmap scaled to fit label."""
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = QImage(bytes(rgb.data), w, h, 3 * w, QImage.Format_RGB888)
    pix = QPixmap.fromImage(img)
    return pix.scaled(label_w, label_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


# ── Custom clickable QLabel ───────────────────────────────────────────────────

class ClickableLabel(QLabel):
    """QLabel that maps mouse clicks to frame-space coordinates."""
    point_added  = pyqtSignal(int, int)
    right_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet('background:#111; border:1px solid #444;')
        self._scale = 1.0
        self._ox = 0.0
        self._oy = 0.0
        self._fw = 1
        self._fh = 1

    def update_transform(self, frame_w, frame_h):
        lw, lh = self.width(), self.height()
        self._fw, self._fh = frame_w, frame_h
        self._scale = min(lw / frame_w, lh / frame_h)
        self._ox = (lw - frame_w * self._scale) / 2
        self._oy = (lh - frame_h * self._scale) / 2

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            fx = int((event.x() - self._ox) / self._scale)
            fy = int((event.y() - self._oy) / self._scale)
            fx = max(0, min(self._fw - 1, fx))
            fy = max(0, min(self._fh - 1, fy))
            self.point_added.emit(fx, fy)
        elif event.button() == Qt.RightButton:
            self.right_clicked.emit()


# ── CameraThread ──────────────────────────────────────────────────────────────

class CameraThread(QThread):
    frame_ready = pyqtSignal(object)   # np.ndarray
    error       = pyqtSignal(str)

    def __init__(self, source, width=0, height=0):
        super().__init__()
        self.source   = source
        self._width   = width    # 0 = use camera default
        self._height  = height
        self._running = True

    def run(self):
        try:
            src = int(self.source)
        except (ValueError, TypeError):
            src = self.source
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            self.error.emit(f'Cannot open camera: {self.source}')
            return
        if self._width and self._height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        while self._running:
            ret, frame = cap.read()
            if ret:
                self.frame_ready.emit(frame)
            self.msleep(33)
        cap.release()

    def stop(self):
        self._running = False
        self.wait(2000)


# ── TrackingWorker ────────────────────────────────────────────────────────────

class TrackingWorker(QThread):
    log          = pyqtSignal(str)
    data_point   = pyqtSignal(dict)
    loop_complete = pyqtSignal()
    finished     = pyqtSignal(str)     # emits csv path

    def __init__(self, roi_dir, output_csv, rotate):
        super().__init__()
        self.roi_dir     = roi_dir
        self.output_csv  = output_csv
        self.rotate      = rotate
        self._running    = True
        self._queue      = Queue(maxsize=2)
        self.data_log    = []
        self._last_mu1   = None
        self._last_mu2   = None
        self._pending_mu1 = None   # ค่าที่กระโดดขึ้นแต่ยังไม่ยืนยัน (รอเฟรมถัดไป >= ค่านี้)
        self._pending_mu2 = None
        self._last_progress = None
        self._frame_count   = 0

    def feed_frame(self, frame):
        if not self._queue.full():
            self._queue.put_nowait(frame)

    def stop(self):
        self._running = False

    def run(self):
        self.log.emit('Initializing EasyOCR…')
        try:
            import warnings, PIL.Image
            if not hasattr(PIL.Image, 'Resampling'):
                PIL.Image.Resampling = PIL.Image  # Pillow <9.1 compat
            import easyocr
            try:
                import torch
                gpu = torch.cuda.is_available()
            except Exception:
                gpu = False
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                reader = easyocr.Reader(['en'], gpu=gpu)
            # suppress PyTorch pin_memory warning throughout inference
            warnings.filterwarnings(
                'ignore', message='.*pin_memory.*', category=UserWarning)
        except Exception as e:
            self.log.emit(f'EasyOCR error: {e}')
            self.finished.emit('')
            return
        self.log.emit('EasyOCR ready. Waiting for frames…')

        rois = self._load_all_rois()

        while self._running:
            try:
                frame = self._queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                self._frame_count += 1
                if self.rotate:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)

                mu1 = mu2 = mu_rate = progress = None
                # เวลาจริงจากนาฬิกาเครื่อง — เทียบกับ raw file ได้ตรงๆ (ไม่ OCR วันเวลาจากภาพ
                # เพราะ FOV ต่ำ/เบลอ อ่านไม่ได้อยู่แล้ว)
                _now = datetime.now()
                date_text = _now.strftime('%Y-%m-%d')
                time_text = _now.strftime('%H:%M:%S.%f')[:-3]

                if rois.get('mu1_roi'):
                    r = self._ocr_one(reader, frame, rois['mu1_roi'])
                    mu1 = self._validate_mu(r)
                if rois.get('mu2_roi'):
                    r = self._ocr_one(reader, frame, rois['mu2_roi'])
                    mu2 = self._validate_mu(r)
                mu1, mu2 = self._check_mu_pair(mu1, mu2)

                if rois.get('mu_rate_roi'):
                    r = self._ocr_one(reader, frame, rois['mu_rate_roi'])
                    mu_rate = self._validate_mu_rate(r)

                if rois.get('progress_roi'):
                    r = self._ocr_one(reader, frame, rois['progress_roi'])
                    progress, loop_done = self._validate_progress(r)
                    if loop_done:
                        self.log.emit('Loop complete (progress reset detected)')
                        self.loop_complete.emit()

                entry = {
                    'frame':    self._frame_count,
                    'mu1':      mu1,    'mu2':      mu2,
                    'mu_rate':  mu_rate,'progress': progress,
                    'date':     date_text, 'time':  time_text,
                }
                self.data_log.append(entry)
                self.data_point.emit(entry)
                self.log.emit(
                    f'[MU] {self._frame_count}: '
                    f'MU={mu1}/{mu2}  Rate={mu_rate}  Prog={progress}%'
                )
            except Exception as e:
                self.log.emit(f'[OCR] frame {self._frame_count} error (ข้าม): {e}')

        # save CSV
        csv_out = ''
        try:
            if self.data_log:
                import pandas as pd
                df = pd.DataFrame(self.data_log)
                df.to_csv(self.output_csv, index=False)
                self.log.emit(f'CSV saved: {self.output_csv}')
                csv_out = self.output_csv
            else:
                self.log.emit('No data collected.')
        except Exception as e:
            self.log.emit(f'CSV save error: {e}')
        self.finished.emit(csv_out)

    # ── ROI helpers ──────────────────────────────────────────────────────────

    def _save_crop(self, frame, debug_dir, name, coords):
        x1, y1, x2, y2 = self._bbox(coords)
        fh, fw = frame.shape[:2]
        x1, x2 = max(0, x1), min(fw, x2)
        y1, y2 = max(0, y1), min(fh, y2)
        if x2 <= x1 or y2 <= y1:
            self.log.emit(f'{name}: ROI อยู่นอกขอบ frame ({fw}x{fh}), ข้าม')
            return
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return
        path = os.path.join(debug_dir, f'{self._frame_count:04d}_{name}.jpg')
        cv2.imwrite(path, crop)

    def _load_all_rois(self):
        rois = {}
        for name in ROI_NAMES:
            coords = _load_roi_file(os.path.join(self.roi_dir, f'{name}.txt'))
            if coords:
                rois[name] = coords
                self.log.emit(f'Loaded {name}: {len(coords)} points')
            else:
                self.log.emit(f'{name}: not found, skipping')
        return rois

    def _bbox(self, coords):
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        return min(xs), min(ys), max(xs), max(ys)

    def _clip_roi(self, frame, coords):
        x1, y1, x2, y2 = self._bbox(coords)
        fh, fw = frame.shape[:2]
        x1, x2 = max(0, x1), min(fw, x2)
        y1, y2 = max(0, y1), min(fh, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        # resize ให้ height ไม่เกิน 120px — OCR เร็วขึ้นมาก ความแม่นยังดี
        h, w = crop.shape[:2]
        if h > 120:
            scale = 120 / h
            crop = cv2.resize(crop, (int(w * scale), 120), interpolation=cv2.INTER_AREA)
        return crop

    def _ocr_two(self, reader, frame, coords):
        roi = self._clip_roi(frame, coords)
        if roi is None:
            return None, None
        try:
            res = reader.readtext(roi)
            return (res[0][1] if len(res) > 0 else None,
                    res[1][1] if len(res) > 1 else None)
        except Exception:
            return None, None

    def _ocr_one(self, reader, frame, coords):
        roi = self._clip_roi(frame, coords)
        if roi is None:
            return None
        try:
            res = reader.readtext(roi)
            return res[0][1] if res else None
        except Exception:
            return None

    # ── Validation (ported from video/get_mu.py) ─────────────────────────────

    def _to_float(self, text):
        if not text:
            return None
        try:
            return float(re.sub(r'[^\d.]', '', text))
        except ValueError:
            return None

    def _validate_mu(self, text):
        n = self._to_float(text)
        if n is None:
            return None
        if 0 <= n <= 40000:
            return n
        if n > 1000000:
            s = str(int(n))
            if len(s) >= 7:
                try:
                    c = float(s[:2] + s[2:5] + '.' + s[5:7])
                    if 0 <= c <= 40000:
                        return c
                except Exception:
                    pass
        return None

    def _check_mu_pair(self, mu1, mu2):
        # MU สะสมลดไม่ได้จริง — ดักขาลง; ขาขึ้นต้องเห็นเฟรมถัดไป >= candidate ก่อนถึงเชื่อ
        # (กัน OCR misread โดดขึ้นแป๊บเดียวแล้วมาล็อกเป็นค่าจริงถาวรเพราะห้ามลด)
        if mu1 is not None and self._last_mu1 is not None and self._last_mu1 > 0:
            if mu1 < self._last_mu1:
                mu1 = self._last_mu1
                self._pending_mu1 = None
            elif mu1 > self._last_mu1:
                if self._pending_mu1 is not None and mu1 >= self._pending_mu1:
                    self._pending_mu1 = None
                else:
                    self._pending_mu1 = mu1
                    mu1 = self._last_mu1
            else:
                self._pending_mu1 = None
        if mu2 is not None and self._last_mu2 is not None and self._last_mu2 > 0:
            if mu2 < self._last_mu2:
                mu2 = self._last_mu2
                self._pending_mu2 = None
            elif mu2 > self._last_mu2:
                if self._pending_mu2 is not None and mu2 >= self._pending_mu2:
                    self._pending_mu2 = None
                else:
                    self._pending_mu2 = mu2
                    mu2 = self._last_mu2
            else:
                self._pending_mu2 = None
        if mu1 is not None and mu2 is not None and abs(mu1 - mu2) > 500:
            mu1, mu2 = self._last_mu1, self._last_mu2
        if mu1 is not None:
            self._last_mu1 = mu1
        if mu2 is not None:
            self._last_mu2 = mu2
        return mu1, mu2

    def _validate_mu_rate(self, text):
        n = self._to_float(text)
        if not n:
            return None
        if 10000 <= n <= 300000:
            return n
        # OCR อาจอ่าน decimal point เป็น comma/space → "52381.4" → 523814
        if 100000 <= n <= 3000000:
            candidate = n / 10
            if 10000 <= candidate <= 300000:
                return candidate
        return None

    def _validate_progress(self, text):
        """Returns (value, loop_complete)."""
        # loop reset: progress was ≥99% last frame
        if (self._last_progress is not None
                and self._last_progress >= 99):
            self._last_progress = 0
            self._last_mu1 = None
            self._last_mu2 = None
            return 0, True

        if not text:
            return self._last_progress, False

        n = self._to_float(text)
        # OCR บางครั้งอ่าน '.' เป็น space เช่น '69 28%' → ลอง replace space ด้วย '.'
        if (n is None or n > 100) and text:
            alt = re.sub(r'(\d)\s+(\d)', r'\1.\2', text)
            n2 = self._to_float(alt)
            if n2 is not None and 0 <= n2 <= 100:
                n = n2
        if n is None or not (0 <= n <= 100):
            return self._last_progress, False

        # progress ลดกลางลูปไม่ได้จริง (loop reset ถูกจัดการแยกไว้ข้างบนแล้ว) — ดักขาลง
        if self._last_progress is not None and n < self._last_progress:
            return self._last_progress, False

        # reject jumps > 5% upward in one step
        if (self._last_progress is not None
                and n > self._last_progress
                and abs(n - self._last_progress) > 5):
            return self._last_progress, False

        self._last_progress = n
        return n, False

    def _parse_time(self, text):
        if not text:
            return None, None
        month_map = {
            'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
            'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
            'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
        }
        pat = (r'(\d{1,2})[.:,](\d{1,2})[.:,]?(\d{0,2})\s+'
               r'(\d{1,2})\s*[.-]?\s*([A-Za-z]{3})\s*[.-]?\s*(\d{4})')
        m = re.search(pat, text)
        if m:
            h  = m.group(1).zfill(2)
            mi = m.group(2).zfill(2)
            s  = (m.group(3) or '00').zfill(2)
            d  = m.group(4).zfill(2)
            mo = month_map.get(m.group(5).lower(), '01')
            y  = m.group(6)
            return f'{d}/{mo}/{y}', f'{h}:{mi}:{s}'
        return None, None


# ── SSHWorker ─────────────────────────────────────────────────────────────────

class SSHWorker(QThread):
    log      = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, csv_path, ssh_addr, remote_path, password,
                 remote_cmd='', script_path='', video_path=''):
        super().__init__()
        self.csv_path    = csv_path
        self.ssh_addr    = ssh_addr
        self.remote_path = remote_path
        self.password    = password
        self.remote_cmd  = remote_cmd
        self.script_path = script_path   # local path to mu_frame_v2.py
        self.video_path  = video_path    # local path to mu_video_*.mp4 (optional)

    def _scp(self, local, remote_dest, label):
        cmd = ['sshpass', '-p', self.password,
               'scp', '-o', 'StrictHostKeyChecking=no', local, remote_dest]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                self.log.emit(f'SSH: {label} ส่งแล้ว')
            else:
                self.log.emit(f'SSH: SCP error ({label}): {r.stderr.strip()[:200]}')
        except Exception as e:
            self.log.emit(f'SSH: SCP exception ({label}): {e}')

    def run(self):
        if not self.csv_path or not os.path.exists(self.csv_path):
            self.log.emit('SSH: no CSV file to send.')
            self.finished.emit()
            return

        dest_base = f'{self.ssh_addr}:{self.remote_path}'

        # 1. SCP mu_frame_v2.py ไปก่อน (ถ้ามี)
        if self.script_path and os.path.exists(self.script_path):
            self._scp(self.script_path, f'{dest_base}/', 'mu_frame_v2.py')

        # 2. สร้าง csv/ subfolder บน server แล้ว SCP CSV
        csv_remote_dir = f'{self.remote_path}/csv'
        try:
            subprocess.run(
                ['sshpass', '-p', self.password, 'ssh', self.ssh_addr,
                 '-o', 'StrictHostKeyChecking=no',
                 f'mkdir -p {csv_remote_dir}'],
                capture_output=True, timeout=15)
        except Exception:
            pass
        self._scp(self.csv_path, f'{self.ssh_addr}:{csv_remote_dir}/', 'CSV')

        # 3. Run remote command (track_csv.py)
        if self.remote_cmd.strip():
            self.log.emit('SSH: กำลังสร้างกราฟ…')
            ssh_cmd = ['sshpass', '-p', self.password,
                       'ssh', self.ssh_addr, '-o', 'StrictHostKeyChecking=no',
                       self.remote_cmd]
            try:
                r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=300)
                if r.stdout:
                    self.log.emit(f'SSH: {r.stdout.strip()[:400]}')
                if r.returncode != 0:
                    self.log.emit(f'SSH error: {r.stderr.strip()[:200]}')
            except Exception as e:
                self.log.emit(f'SSH exception: {e}')

        # 4. Video → SCP + รัน ocr_video.py บนเซิร์ฟเวอร์ (GPU) — best-effort,
        #    ไม่ให้ error ตรงนี้กระทบผลลัพธ์ CSV/กราฟที่ได้ไปแล้วข้างบน
        if self.video_path and os.path.exists(self.video_path):
            try:
                video_remote_dir = f'{self.remote_path}/video'
                subprocess.run(
                    ['sshpass', '-p', self.password, 'ssh', self.ssh_addr,
                     '-o', 'StrictHostKeyChecking=no',
                     f'mkdir -p {video_remote_dir}'],
                    capture_output=True, timeout=15)
                self._scp(self.video_path, f'{self.ssh_addr}:{video_remote_dir}/', 'video')

                local_ocr_script = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(
                        os.path.abspath(__file__)))),
                    'ocr_video.py')
                if os.path.exists(local_ocr_script):
                    self._scp(local_ocr_script, f'{dest_base}/', 'ocr_video.py')
                    remote_video = f'{video_remote_dir}/{os.path.basename(self.video_path)}'
                    ocr_cmd = f'~/sutpct-env/bin/python3 {self.remote_path}/ocr_video.py {remote_video}'
                    self.log.emit('SSH: กำลังรัน OCR วิดีโอบนเซิร์ฟเวอร์ (GPU)…')
                    r = subprocess.run(
                        ['sshpass', '-p', self.password, 'ssh', self.ssh_addr,
                         '-o', 'StrictHostKeyChecking=no', ocr_cmd],
                        capture_output=True, text=True, timeout=600)
                    if r.returncode == 0:
                        self.log.emit('SSH: OCR วิดีโอเสร็จแล้ว (ผลลัพธ์อยู่บนเซิร์ฟเวอร์ในโฟลเดอร์ video/)')
                    else:
                        self.log.emit(f'SSH: OCR วิดีโอ error: {r.stderr.strip()[:200]}')
            except Exception as e:
                self.log.emit(f'SSH: video OCR exception: {e}')

        self.finished.emit()


# ── SettingsPage ──────────────────────────────────────────────────────────────

class SettingsPage(QWidget):
    launched = pyqtSignal(str, bool)   # camera_source, rotate

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cam_thread     = None
        self._current_frame  = None   # frozen frame for ROI drawing
        self._points         = []
        self._rotate         = False
        self._build_ui()
        self._refresh_roi_status()
        self._apply_config()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── Camera bar ──────────────────────────────────────────────────────
        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel('Camera Source:'))
        self._src_edit = QLineEdit('0')
        self._src_edit.setFixedWidth(80)
        cam_row.addWidget(self._src_edit)

        cam_row.addWidget(QLabel('Resolution:'))
        self._res_combo = QComboBox()
        self._res_combo.addItems([
            'Default', '1280×720', '1920×1080', '2560×1440', '3840×2160'])
        self._res_combo.setFixedWidth(130)
        cam_row.addWidget(self._res_combo)

        self._rotate_check = QCheckBox('Rotate 180°')
        self._rotate_check.stateChanged.connect(self._on_rotate_changed)
        cam_row.addWidget(self._rotate_check)

        self._btn_connect = QPushButton('Connect')
        self._btn_connect.clicked.connect(self._connect_camera)
        cam_row.addWidget(self._btn_connect)

        self._btn_freeze = QPushButton('Freeze')
        self._btn_freeze.clicked.connect(self._freeze_camera)
        self._btn_freeze.setEnabled(False)
        cam_row.addWidget(self._btn_freeze)

        cam_row.addStretch()
        root.addLayout(cam_row)

        # ── Main row ────────────────────────────────────────────────────────
        main_row = QHBoxLayout()

        preview_box = QGroupBox(
            'Live Preview  —  Connect → aim camera → Freeze → click to add ROI points')
        pl = QVBoxLayout(preview_box)
        self._frame_label = ClickableLabel()
        self._frame_label.setMinimumSize(640, 420)
        self._frame_label.point_added.connect(self._on_point_added)
        self._frame_label.right_clicked.connect(self._reset_roi)
        pl.addWidget(self._frame_label)
        main_row.addWidget(preview_box, 3)

        # right panel
        right = QVBoxLayout()

        roi_box = QGroupBox('ROI Setup')
        rl = QVBoxLayout(roi_box)
        rl.addWidget(QLabel('ROI Type:'))
        self._roi_combo = QComboBox()
        self._roi_combo.addItems(ROI_NAMES)
        self._roi_combo.currentIndexChanged.connect(self._reset_roi)
        rl.addWidget(self._roi_combo)
        rl.addWidget(QLabel('Points (click up to 4):'))
        self._points_list = QListWidget()
        self._points_list.setMaximumHeight(100)
        rl.addWidget(self._points_list)

        btn_row = QHBoxLayout()
        btn_reset = QPushButton('Reset')
        btn_reset.clicked.connect(self._reset_roi)
        btn_row.addWidget(btn_reset)
        self._btn_save_roi = QPushButton('Save ROI')
        self._btn_save_roi.clicked.connect(self._save_roi)
        self._btn_save_roi.setStyleSheet('background:#2e7d32; color:#fff;')
        btn_row.addWidget(self._btn_save_roi)
        rl.addLayout(btn_row)
        right.addWidget(roi_box)

        status_box = QGroupBox('Saved ROIs')
        sl = QVBoxLayout(status_box)
        sl.setSpacing(4)
        self._roi_status = {}
        for name in ROI_NAMES:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            lbl = QLabel(f'✗  {name}')
            lbl.setStyleSheet('color:#888; font-size:12px;')
            del_btn = QPushButton('✕')
            del_btn.setFixedSize(22, 22)
            del_btn.setStyleSheet(
                'QPushButton { background:#c62828; color:#fff; border:none;'
                ' border-radius:3px; font-size:10px; font-weight:bold; }'
                'QPushButton:hover { background:#e53935; }'
                'QPushButton:disabled { background:#333; color:#555; }')
            del_btn.setEnabled(False)
            del_btn.clicked.connect(lambda checked, n=name: self._delete_roi(n))
            row_l.addWidget(lbl, 1)
            row_l.addWidget(del_btn)
            sl.addWidget(row_w)
            self._roi_status[name] = (lbl, del_btn)
        right.addWidget(status_box)
        right.addStretch()

        self._btn_preview = QPushButton('Preview ROIs')
        self._btn_preview.setMinimumHeight(36)
        self._btn_preview.setStyleSheet(
            'background:#37474f; color:#cfd8dc; font-weight:bold; font-size:13px;'
            ' border-radius:6px;')
        self._btn_preview.clicked.connect(self._preview_rois)
        right.addWidget(self._btn_preview)

        self._btn_debug_crop = QPushButton('Save Debug Crops')
        self._btn_debug_crop.setMinimumHeight(36)
        self._btn_debug_crop.setStyleSheet(
            'background:#4a148c; color:#e1bee7; font-weight:bold; font-size:13px;'
            ' border-radius:6px;')
        self._btn_debug_crop.clicked.connect(self._save_debug_crops)
        right.addWidget(self._btn_debug_crop)

        self._btn_launch = QPushButton('Ready  →')
        self._btn_launch.setMinimumHeight(42)
        self._btn_launch.setStyleSheet(
            'background:#1565c0; color:#fff; font-weight:bold; font-size:14px;')
        self._btn_launch.clicked.connect(self._on_launch)
        right.addWidget(self._btn_launch)

        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setFixedWidth(260)
        main_row.addWidget(right_w)
        root.addLayout(main_row)

    def _apply_config(self):
        cfg = _load_config()
        if 'camera_source' in cfg:
            self._src_edit.setText(str(cfg['camera_source']))
        if cfg.get('rotate_180'):
            self._rotate_check.setChecked(True)
        res = cfg.get('resolution', 'Default')
        idx = self._res_combo.findText(res)
        if idx >= 0:
            self._res_combo.setCurrentIndex(idx)

    def _get_resolution(self):
        """Returns (width, height) from combo, or (0, 0) for Default."""
        txt = self._res_combo.currentText()
        if txt == 'Default':
            return 0, 0
        try:
            w, h = txt.replace('×', 'x').split('x')
            return int(w), int(h)
        except Exception:
            return 0, 0

    # ── Camera ──────────────────────────────────────────────────────────────

    def _connect_camera(self):
        src = self._src_edit.text().strip()
        try:
            src_val = int(src)
        except ValueError:
            src_val = src

        # auto-scan if integer index fails
        if isinstance(src_val, int):
            import cv2 as _cv2
            found = None
            for idx in range(src_val, src_val + 5):
                cap = _cv2.VideoCapture(idx)
                if cap.isOpened():
                    cap.release()
                    found = idx
                    break
                cap.release()
            if found is None:
                QMessageBox.critical(self, 'Error', 'Cannot open camera')
                return
            if found != src_val:
                self._src_edit.setText(str(found))
            src_val = found

        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None
        w, h = self._get_resolution()
        self._cam_thread = CameraThread(src_val, width=w, height=h)
        self._cam_thread.frame_ready.connect(self._on_live_frame)
        self._cam_thread.error.connect(
            lambda msg: QMessageBox.critical(self, 'Error', msg))
        self._cam_thread.start()
        self._btn_connect.setEnabled(False)
        self._btn_freeze.setEnabled(True)

    def _freeze_camera(self):
        """Stop live feed, keep last frame frozen for ROI drawing."""
        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None
        self._btn_freeze.setEnabled(False)
        self._btn_connect.setEnabled(True)

    def _stop_camera(self):
        """Full stop — called on Launch or window close."""
        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None

    def _on_live_frame(self, frame):
        if self._rotate:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        self._current_frame = frame
        self._show_frame()

    def _on_rotate_changed(self, state):
        self._rotate = bool(state)
        if self._current_frame is not None:
            self._show_frame()

    # ── Drawing ─────────────────────────────────────────────────────────────

    def _show_frame(self):
        if self._current_frame is None:
            return
        display = self._current_frame.copy()

        # Draw all saved ROI polygons from files
        for name in ROI_NAMES:
            coords = _load_roi_file(os.path.join(VIDEO_DIR, f'{name}.txt'))
            if not coords:
                continue
            color = ROI_COLORS.get(name, (200, 200, 200))
            n = len(coords)
            for i in range(n):
                cv2.line(display, coords[i], coords[(i + 1) % n], color, 2)
            x0, y0 = coords[0]
            label = name.replace('_roi', '')
            cv2.putText(display, label, (x0, max(y0 - 6, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # Draw current in-progress points (white/green)
        pts = self._points
        for i, (x, y) in enumerate(pts):
            cv2.circle(display, (x, y), 6, (0, 220, 0), -1)
            if i > 0:
                cv2.line(display, pts[i - 1], (x, y), (0, 220, 0), 2)
        if len(pts) == 4:
            cv2.line(display, pts[3], pts[0], (0, 220, 0), 2)

        h, w = display.shape[:2]
        self._frame_label.update_transform(w, h)
        lw, lh = self._frame_label.width(), self._frame_label.height()
        self._frame_label.setPixmap(_frame_to_pixmap(display, lw, lh))

    def _on_point_added(self, fx, fy):
        if self._current_frame is None:
            return
        if len(self._points) >= 4:
            return
        self._points.append((fx, fy))
        self._points_list.addItem(f'Point {len(self._points)}: ({fx}, {fy})')
        self._show_frame()

    def _reset_roi(self):
        self._points = []
        self._points_list.clear()
        self._show_frame()

    # ── ROI save ────────────────────────────────────────────────────────────

    def _save_roi(self):
        if len(self._points) < 2:
            QMessageBox.warning(self, 'Warning', 'Need at least 2 points.')
            return
        name  = self._roi_combo.currentText()
        fpath = os.path.join(VIDEO_DIR, f'{name}.txt')
        os.makedirs(VIDEO_DIR, exist_ok=True)
        with open(fpath, 'w') as f:
            f.write('ROI Points:\n')
            for i, (x, y) in enumerate(self._points):
                f.write(f'Point {i + 1}: {x}, {y}\n')
            f.write(f'\nTotal points: {len(self._points)}\n')
        self._refresh_roi_status()
        self._reset_roi()

    def _refresh_roi_status(self):
        for name in ROI_NAMES:
            exists = os.path.exists(os.path.join(VIDEO_DIR, f'{name}.txt'))
            lbl, del_btn = self._roi_status[name]
            if exists:
                lbl.setText(f'✓  {name}')
                lbl.setStyleSheet('color:#66bb6a; font-size:12px;')
                del_btn.setEnabled(True)
            else:
                lbl.setText(f'✗  {name}')
                lbl.setStyleSheet('color:#888; font-size:12px;')
                del_btn.setEnabled(False)

    def _delete_roi(self, name):
        fpath = os.path.join(VIDEO_DIR, f'{name}.txt')
        try:
            os.remove(fpath)
        except FileNotFoundError:
            pass
        self._refresh_roi_status()
        self._show_frame()

    def _preview_rois(self):
        """Freeze camera if live, redraw frame with all saved ROI overlays."""
        if self._cam_thread:
            self._freeze_camera()
        if self._current_frame is None:
            QMessageBox.information(self, 'Preview ROIs',
                'กด Connect ก่อน แล้วกด Freeze เพื่อหยุด frame\n'
                'จากนั้นกด Preview ROIs เพื่อดู ROI ที่บันทึกไว้')
            return
        self._show_frame()

    def _save_debug_crops(self):
        if self._current_frame is None:
            QMessageBox.warning(self, 'Debug Crops',
                'กด Connect ก่อน แล้วกด Freeze เพื่อหยุด frame')
            return
        debug_dir = os.path.join(VIDEO_DIR, 'debug')
        os.makedirs(debug_dir, exist_ok=True)
        saved = []
        for name in ROI_NAMES:
            coords = _load_roi_file(os.path.join(VIDEO_DIR, f'{name}.txt'))
            if not coords:
                continue
            xs = [p[0] for p in coords]
            ys = [p[1] for p in coords]
            x1, x2 = max(0, min(xs)), min(self._current_frame.shape[1], max(xs))
            y1, y2 = max(0, min(ys)), min(self._current_frame.shape[0], max(ys))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = self._current_frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            path = os.path.join(debug_dir, f'{name}.jpg')
            cv2.imwrite(path, crop)
            saved.append(name)
        if saved:
            QMessageBox.information(self, 'Debug Crops',
                f'Saved {len(saved)} crops:\n' + '\n'.join(saved) +
                f'\n\nFolder:\n{debug_dir}')
        else:
            QMessageBox.warning(self, 'Debug Crops',
                'ไม่มี ROI ที่บันทึกไว้ หรือ ROI อยู่นอก frame')

    # ── Launch ──────────────────────────────────────────────────────────────

    def _on_launch(self):
        src    = self._src_edit.text().strip()
        rotate = self._rotate_check.isChecked()

        roi_lines = []
        for name in ROI_NAMES:
            exists = os.path.exists(os.path.join(VIDEO_DIR, f'{name}.txt'))
            roi_lines.append(f"{'✓' if exists else '✗'}  {name}")

        msg = (
            f"Camera source : {src}\n"
            f"Rotate 180°   : {'Yes' if rotate else 'No'}\n"
            f"\nROI files:\n" + '\n'.join(roi_lines)
        )
        dlg = QMessageBox(self)
        dlg.setWindowTitle('ยืนยันการบันทึก')
        dlg.setText('บันทึกการตั้งค่าต่อไปนี้และปิดหน้าต่าง?')
        dlg.setDetailedText(msg)
        dlg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        dlg.setDefaultButton(QMessageBox.Ok)
        # expand details by default so user sees without clicking
        for btn in dlg.buttons():
            if dlg.buttonRole(btn) == QMessageBox.ActionRole:
                btn.click()
                break
        if dlg.exec_() != QMessageBox.Ok:
            return

        cfg = _load_config()
        cfg['camera_source'] = src
        cfg['rotate_180']    = rotate
        cfg['resolution']    = self._res_combo.currentText()
        _save_config(cfg)
        self._stop_camera()
        self.launched.emit(src, rotate)

    def refresh_status(self):
        self._refresh_roi_status()


# ── MuTracker — used by run.py to track during a beam run ────────────────────

_FRAME_INTERVAL = 3   # feed OCR every N camera frames
_REC_CROP_W, _REC_CROP_H = 320, 80   # size per ROI strip in recorded video

class MuTracker:
    """Headless camera + OCR tracker. Call start() when run begins, stop() when done."""

    def __init__(self, output_dir, ssh_addr='', ssh_path='', ssh_pass='',
                 log_fn=None, data_fn=None):
        self._output_dir = output_dir
        self._ssh_addr   = ssh_addr
        self._ssh_path   = ssh_path
        self._ssh_pass   = ssh_pass
        self._log        = log_fn or (lambda msg: None)
        self._data_fn    = data_fn  # called with each data dict in real-time
        self._cam_thread   = None
        self._track_worker = None
        self._ssh_worker   = None
        self._frame_count  = 0
        self._video_writer = None
        self._video_path   = None
        self._rec_rois     = {}
        self._rotate       = False
        cfg = _load_config()
        src = cfg.get('camera_source', 0)
        try:
            self._source = int(src)
        except (ValueError, TypeError):
            self._source = src
        self._rotate = bool(cfg.get('rotate_180', False))
        res = cfg.get('resolution', 'Default')
        try:
            w, h = res.replace('×', 'x').split('x')
            self._cam_w, self._cam_h = int(w), int(h)
        except Exception:
            self._cam_w, self._cam_h = 0, 0

    def _roi_files_exist(self):
        return any(
            os.path.exists(os.path.join(VIDEO_DIR, f'{n}.txt'))
            for n in ROI_NAMES
        )

    def _log_both(self, msg):
        print(f'[MuTracker] {msg}')
        self._log(msg)

    def prepare(self):
        """Pre-init EasyOCR ตั้งแต่ตอน Launch — เรียกก่อน start()"""
        if not self._roi_files_exist():
            self._log_both('no ROI files found — skip prepare')
            return
        cap = cv2.VideoCapture(self._source)
        ok  = cap.isOpened()
        cap.release()
        if not ok:
            self._log_both(f'camera {self._source!r} not available — skip prepare')
            return

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_dir  = os.path.join(self._output_dir, 'csv')
        self._csv_path = os.path.join(csv_dir, f'mu_tracking_{ts}.csv')
        os.makedirs(csv_dir, exist_ok=True)

        self._track_worker = TrackingWorker(VIDEO_DIR, self._csv_path, self._rotate)
        self._track_worker.log.connect(self._log_both)
        self._track_worker.finished.connect(self._on_finished)
        if self._data_fn:
            self._track_worker.data_point.connect(self._data_fn)
        self._track_worker.start()
        self._log_both('EasyOCR กำลัง init (pre-warm)…')

    def start(self):
        """เริ่ม camera และป้อน frame — เรียกตอนกด Run"""
        if not self._roi_files_exist():
            self._log_both('no ROI files found — skipping')
            return

        # ถ้า prepare() ยังไม่ถูกเรียก หรือ worker ตายไปแล้ว → เริ่มใหม่
        if not getattr(self, '_track_worker', None) or not self._track_worker.isRunning():
            self._log_both('OCR ยังไม่ ready — กำลัง init ใหม่…')
            self.prepare()
            if not self._track_worker or not self._track_worker.isRunning():
                return

        self._frame_count = 0
        self._cam_thread  = CameraThread(self._source,
                                         width=self._cam_w, height=self._cam_h)
        self._cam_thread.frame_ready.connect(self._on_frame)
        self._cam_thread.error.connect(self._log_both)
        self._cam_thread.start()
        self._start_recording()
        self._log_both(f'camera เริ่มแล้ว → บันทึกไปที่ {self._csv_path}')

    def _start_recording(self):
        self._rec_rois = {}
        for name in ROI_NAMES:
            coords = _load_roi_file(os.path.join(VIDEO_DIR, f'{name}.txt'))
            if coords:
                self._rec_rois[name] = coords
        if not self._rec_rois:
            return
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        vid_dir = os.path.join(self._output_dir, 'csv')
        os.makedirs(vid_dir, exist_ok=True)
        self._video_path = os.path.join(vid_dir, f'mu_video_{ts}.mp4')
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        h = _REC_CROP_H * len(ROI_NAMES)
        self._video_writer = cv2.VideoWriter(
            self._video_path, fourcc, 30.0, (_REC_CROP_W, h))
        self._log_both(f'video recording → {self._video_path}')

    def _write_video_frame(self, frame):
        if not self._video_writer or not self._video_writer.isOpened():
            return
        strips = []
        for name in ROI_NAMES:
            coords = self._rec_rois.get(name)
            if coords:
                xs = [p[0] for p in coords]
                ys = [p[1] for p in coords]
                x1 = max(0, min(xs)); x2 = min(frame.shape[1], max(xs))
                y1 = max(0, min(ys)); y2 = min(frame.shape[0], max(ys))
                if x2 > x1 and y2 > y1:
                    crop = frame[y1:y2, x1:x2]
                    strips.append(cv2.resize(crop, (_REC_CROP_W, _REC_CROP_H)))
                    continue
            strips.append(np.zeros((_REC_CROP_H, _REC_CROP_W, 3), dtype=np.uint8))
        self._video_writer.write(np.vstack(strips))

    def stop(self):
        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None
        if self._video_writer:
            self._video_writer.release()
            self._video_writer = None
            self._log_both(f'video saved → {self._video_path}')
        if self._track_worker and self._track_worker.isRunning():
            self._track_worker.stop()

    def _on_frame(self, frame):
        self._frame_count += 1
        if (self._track_worker and self._track_worker.isRunning()
                and self._frame_count % _FRAME_INTERVAL == 0):
            self._track_worker.feed_frame(frame.copy())
        self._write_video_frame(frame)

    def _on_finished(self, csv_path):
        self._log_both(f'MU Tracker: CSV saved → {csv_path}')
        if not csv_path:
            return
        if not (self._ssh_addr and self._ssh_path and self._ssh_pass):
            missing = []
            if not self._ssh_addr:
                missing.append('SSH address')
            if not self._ssh_path:
                missing.append('remote path')
            if not self._ssh_pass:
                missing.append('SSH password')
            self._log_both(f'MU Tracker: ข้าม SSH — ไม่มี {", ".join(missing)}')
            return

        csv_filename  = os.path.basename(csv_path)
        remote_csv    = f'{self._ssh_path}/csv/{csv_filename}'
        remote_mu     = f'{self._ssh_path}/mu_rate'
        remote_script = f'{self._ssh_path}/mu_vs_frame.py'
        remote_cmd    = (
            f'mkdir -p {remote_mu} && '
            f'~/sutpct-env/bin/python3 {remote_script} {remote_csv} {remote_mu}'
        )
        local_script  = os.path.join(VIDEO_DIR, 'mu_vs_frame.py')

        self._log_both('MU Tracker: กำลัง SCP CSV → server…')
        self._ssh_worker = SSHWorker(
            csv_path, self._ssh_addr, self._ssh_path, self._ssh_pass,
            remote_cmd=remote_cmd, script_path=local_script,
            video_path=self._video_path)
        self._ssh_worker.log.connect(self._log_both)
        self._ssh_worker.finished.connect(self._on_ssh_done)
        self._ssh_worker.start()

    def _on_ssh_done(self):
        self._log_both('MU Tracker: SSH transfer เสร็จแล้ว')


# ── VideoWindow — ROI setup only ──────────────────────────────────────────────

class VideoWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle('Camera ROI Setup')
        self.resize(960, 640)

        self._settings_page = SettingsPage()
        self._settings_page.launched.connect(self.close)   # Ready → just close

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._settings_page)

    def closeEvent(self, event):
        self._settings_page._stop_camera()
        event.accept()
