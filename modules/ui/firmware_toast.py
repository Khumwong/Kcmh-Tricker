# modules/ui/firmware_toast.py
# Modal progress dialog สำหรับ firmware installation

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QApplication
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


class FirmwareToast(QDialog):
    """Modal popup แสดงระหว่าง firmware install — ปิดเองเมื่อเสร็จ"""

    def __init__(self, parent=None, fake=False):
        super().__init__(parent)
        self._fake = fake
        self.setWindowTitle("Firmware Installation")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setModal(True)
        self.setFixedWidth(380)
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

        # icon + title
        title = QLabel("  Installing ALPIDE Firmware")
        title.setStyleSheet("color: #e0e0e0; font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

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
                    stop:0 #2ed573, stop:1 #17c0eb);
            }
        """)
        layout.addWidget(self._bar)

        # status text
        self._status = QLabel("กรุณารอ อย่าถอด USB..." if not fake else "Simulating firmware install...")
        self._status.setStyleSheet("color: #888; font-size: 12px;")
        self._status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status)

        self.adjustSize()

    def show_centered(self, parent=None):
        """แสดง popup ตรงกลางหน้าจอ"""
        self.show()
        if parent:
            pg = parent.geometry()
            self.move(pg.center() - self.rect().center())
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move(screen.center() - self.rect().center())
        QApplication.processEvents()

    def set_done(self, success=True):
        """เปลี่ยนเป็น Done แล้วปิดเองใน 2 วินาที"""
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
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
