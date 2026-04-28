import re
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QProgressBar,
                              QApplication, QPlainTextEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot

_DAQ_RE = re.compile(r'DAQ-[0-9A-Fa-f]+')


class FirmwareToast(QDialog):
    """Modal popup แสดงระหว่าง firmware install — ปิดเองเมื่อเสร็จ"""

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

        self._daq_lines = {}  # daq_id -> latest line

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
            self._status.setText(line[:70])

        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())
        QApplication.processEvents()

    def show_centered(self, parent=None):
        self.show()
        if parent:
            pg = parent.geometry()
            self.move(pg.center() - self.rect().center())
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move(screen.center() - self.rect().center())
        QApplication.processEvents()

    def set_done(self, success=True):
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
