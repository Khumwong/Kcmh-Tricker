import re
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QProgressBar, QPushButton, QApplication,
                              QPlainTextEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal

_DAQ_RE = re.compile(r'DAQ-[0-9A-Fa-f]+')


class FirmwareToast(QDialog):
    """Modal popup แสดงระหว่าง firmware install — ปิดเองเมื่อเสร็จ

    มี Cancel + hard timeout เพราะถ้าบอร์ด ALPIDE ไม่ re-enumerate กลับมา
    alpide-daq-program จะค้างใน select() รอ udev event ตลอดกาล
    """

    cancelled = pyqtSignal()   # ผู้ใช้กด Cancel / Esc
    timed_out = pyqtSignal()   # เกิน timeout

    def __init__(self, parent=None, fake=False):
        super().__init__(parent)
        self._fake = fake
        self.setWindowTitle("Firmware Installation")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setModal(True)
        self.setFixedWidth(500)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a2e;
                border: 2px solid #2ed573;
                border-radius: 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("  Installing ALPIDE Firmware")
        title.setStyleSheet("color: #e0e0e0; font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(12)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar {
                border: none; border-radius: 6px; background: #0f3460;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2ed573, stop:1 #17c0eb);
            }
        """)
        layout.addWidget(self._bar)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFixedHeight(200)
        self._output.setStyleSheet("""
            QPlainTextEdit {
                background: #0a0a1a;
                color: #88cc88;
                font-size: 10px;
                font-family: monospace;
                border: none;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        layout.addWidget(self._output)

        self._status = QLabel("กรุณารอ อย่าถอด USB..." if not fake else "Simulating firmware install...")
        self._status.setStyleSheet("color: #888; font-size: 12px;")
        self._status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status)

        footer = QHBoxLayout()
        footer.setSpacing(10)

        self._elapsed_lbl = QLabel("")
        self._elapsed_lbl.setStyleSheet("color: #666; font-size: 11px; font-family: monospace;")
        footer.addWidget(self._elapsed_lbl)
        footer.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                color: #ddd; background: #2a2a4a; border: 1px solid #44446a;
                border-radius: 6px; padding: 5px 18px; font-size: 12px;
            }
            QPushButton:hover { background: #ff4757; border-color: #ff4757; }
            QPushButton:disabled { color: #555; background: #1f1f38; border-color: #2a2a4a; }
        """)
        self._cancel_btn.clicked.connect(self._on_cancel)
        footer.addWidget(self._cancel_btn)

        layout.addLayout(footer)

        self._daq_lines = {}  # daq_id -> latest line

        self._elapsed = 0
        self._timeout_s = 0
        self._aborted = None      # None | "cancel" | "timeout"
        self._done = False

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

        self.adjustSize()

    @pyqtSlot(str)
    def append_line(self, line):
        if '\r' in line:
            line = line.split('\r')[-1]
        line = line.strip()
        if not line:
            return

        m = _DAQ_RE.search(line)
        if m:
            daq_id = m.group(0)
            self._daq_lines[daq_id] = line
            self._output.setPlainText('\n'.join(self._daq_lines[k] for k in sorted(self._daq_lines)))
        else:
            self._output.appendPlainText(line)
            if not self._aborted:
                self._status.setText(line[:70])

        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())
        QApplication.processEvents()

    def start_timeout(self, seconds):
        """เริ่มนับเวลา — เกิน seconds แล้วยังไม่จบ ให้ถือว่าค้าง"""
        self._timeout_s = int(seconds)
        self._elapsed = 0
        self._on_tick()
        self._tick.start()

    def _on_tick(self):
        if self._done:
            return
        self._elapsed += 1
        left = self._timeout_s - self._elapsed
        if self._timeout_s and left <= 0:
            self._tick.stop()
            self._aborted = "timeout"
            self._cancel_btn.setEnabled(False)
            self._elapsed_lbl.setText("timed out")
            self._elapsed_lbl.setStyleSheet(
                "color: #ff4757; font-size: 11px; font-family: monospace;")
            self.timed_out.emit()
            QTimer.singleShot(4000, self._force_close)
            return
        txt = f"{self._elapsed // 60:d}:{self._elapsed % 60:02d}"
        # เตือนเมื่อเหลือน้อยกว่า 30 วิ
        if self._timeout_s and left <= 30:
            txt += f"   timeout in {left}s"
            self._elapsed_lbl.setStyleSheet(
                "color: #ffa502; font-size: 11px; font-family: monospace;")
        self._elapsed_lbl.setText(txt)

    def _on_cancel(self):
        if self._done or self._aborted:
            return
        self._tick.stop()
        self._aborted = "cancel"
        self._cancel_btn.setEnabled(False)
        self._status.setText("กำลังยกเลิก...")
        self.cancelled.emit()
        QTimer.singleShot(4000, self._force_close)

    def keyPressEvent(self, event):
        # Esc ต้องไปทางเดียวกับ Cancel เพื่อให้ subprocess ถูกฆ่า ไม่ใช่แค่ปิด dialog
        if event.key() == Qt.Key_Escape:
            self._on_cancel()
            return
        super().keyPressEvent(event)

    def show_centered(self, parent=None):
        self.show()
        if parent:
            pg = parent.geometry()
            self.move(pg.center() - self.rect().center())
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move(screen.center() - self.rect().center())
        QApplication.processEvents()

    def _force_close(self):
        """เผื่อ worker ไม่ยอม report กลับมาหลังโดนฆ่า — ปิด dialog เองอยู่ดี"""
        if not self._done:
            self.set_done(False)

    def set_done(self, success=True):
        if self._done:
            return
        self._done = True
        self._tick.stop()
        self._cancel_btn.setEnabled(False)
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        if self._aborted:
            self._bar.setStyleSheet("""
                QProgressBar { border: none; border-radius: 6px; background: #0f3460; }
                QProgressBar::chunk { border-radius: 6px; background: #ffa502; }
            """)
            if self._aborted == "timeout":
                self._status.setText(
                    f"⏱  Timed out after {self._timeout_s}s — บอร์ดไม่ re-enumerate กลับมา")
            else:
                self._status.setText("✗  ยกเลิกแล้ว")
            self._status.setStyleSheet("color: #ffa502; font-size: 13px; font-weight: bold;")
            QApplication.processEvents()
            QTimer.singleShot(2500, self.reject)
            return
        if success:
            self._bar.setStyleSheet("""
                QProgressBar { border: none; border-radius: 6px; background: #0f3460; }
                QProgressBar::chunk { border-radius: 6px; background: #2ed573; }
            """)
            self._status.setText("✓  Firmware installed successfully")
            self._status.setStyleSheet("color: #2ed573; font-size: 13px; font-weight: bold;")
        else:
            self._bar.setStyleSheet("""
                QProgressBar { border: none; border-radius: 6px; background: #0f3460; }
                QProgressBar::chunk { border-radius: 6px; background: #ff4757; }
            """)
            self._status.setText("✗  Installation failed")
            self._status.setStyleSheet("color: #ff4757; font-size: 13px; font-weight: bold;")
        QApplication.processEvents()
        QTimer.singleShot(2000, self.accept)
