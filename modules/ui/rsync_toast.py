# modules/ui/rsync_toast.py
# Non-modal progress popup สำหรับ rsync transfer

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QApplication
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


class RsyncToast(QDialog):
    """Non-modal popup แสดงระหว่าง rsync — ปิดเองเมื่อเสร็จ/ล้มเหลว"""

    def __init__(self, filename, dest_host, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sending file")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setModal(False)
        self.setFixedWidth(400)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a2e;
                border: 2px solid #ffd740;
                border-radius: 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(10)

        # title row
        title = QLabel(f"  Sending to {dest_host}")
        title.setStyleSheet("color: #e0e0e0; font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        # filename
        self._file_label = QLabel(filename)
        self._file_label.setStyleSheet("color: #8898a8; font-size: 11px; font-family: monospace;")
        self._file_label.setWordWrap(True)
        layout.addWidget(self._file_label)

        # progress bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate
        self._bar.setFixedHeight(12)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 6px;
                background: #0f3460;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ffd740, stop:1 #ffab40);
            }
        """)
        layout.addWidget(self._bar)

        # status row: % + speed
        self._status = QLabel("กรุณารอ...")
        self._status.setStyleSheet("color: #aaa; font-size: 12px; font-family: monospace;")
        self._status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status)

        self.adjustSize()

    def show_centered(self, parent=None):
        self.show()
        ref = parent or self.parent()
        if ref:
            pg = ref.geometry()
            self.move(pg.center() - self.rect().center())
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move(screen.center() - self.rect().center())
        QApplication.processEvents()

    def update_progress(self, pct, speed):
        """อัพเดต % และ speed — เรียกจาก main thread ผ่าน invokeMethod"""
        self._status.setText(f"{pct}%   {speed}")
        QApplication.processEvents()

    def set_done(self, success=True, detail=""):
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        if success:
            self._bar.setStyleSheet("""
                QProgressBar { border: none; border-radius: 6px; background: #0f3460; }
                QProgressBar::chunk { border-radius: 6px; background: #69f0ae; }
            """)
            self.setStyleSheet("""
                QDialog {
                    background-color: #1a1a2e;
                    border: 2px solid #69f0ae;
                    border-radius: 14px;
                }
            """)
            self._status.setText("✓  Transfer complete")
            self._status.setStyleSheet("color: #69f0ae; font-size: 13px; font-weight: bold;")
        else:
            self._bar.setStyleSheet("""
                QProgressBar { border: none; border-radius: 6px; background: #0f3460; }
                QProgressBar::chunk { border-radius: 6px; background: #ef5350; }
            """)
            self.setStyleSheet("""
                QDialog {
                    background-color: #1a1a2e;
                    border: 2px solid #ef5350;
                    border-radius: 14px;
                }
            """)
            msg = detail[:80] if detail else "Transfer failed"
            self._status.setText(f"✗  {msg}")
            self._status.setStyleSheet("color: #ef5350; font-size: 12px; font-weight: bold;")
        QApplication.processEvents()
        close_ms = 2000 if success else 3000
        QTimer.singleShot(close_ms, self.accept)
