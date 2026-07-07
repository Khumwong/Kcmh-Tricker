from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton
)
from PyQt5.QtCore import Qt


class _QACompleteDialog(QDialog):
    def __init__(self, parent, file_name, loops, elapsed_s, energy, mu, num_alpides):
        super().__init__(parent)
        self.setWindowTitle("QA Acquisition Complete")
        self.setModal(True)
        self.setFixedWidth(360)
        self.setStyleSheet("""
            QDialog { background: #0d1a2e; }
            QLabel  { color: #e0e8f4; border: none; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon_lbl = QLabel("✓")
        icon_lbl.setStyleSheet("color: #00e676; font-size: 26px; font-weight: bold;")
        title_lbl = QLabel("QA Acquisition Complete")
        title_lbl.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold;")
        header.addWidget(icon_lbl)
        header.addWidget(title_lbl)
        header.addStretch()
        layout.addLayout(header)

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("QFrame { background: rgba(255,255,255,0.12); border: none; }")
        layout.addWidget(div)
        layout.addSpacing(4)

        _m, _s = divmod(elapsed_s, 60)
        details = [
            ("File",     file_name or "—"),
            ("Loops",    str(loops)),
            ("Elapsed",  f"{int(_m):02d}:{_s:04.1f} s"),
            ("Energy",   f"{energy} MeV"),
            ("MU",       str(mu)),
            ("ALPIDEs",  str(num_alpides)),
        ]
        for key, val in details:
            row = QHBoxLayout()
            row.setSpacing(12)
            k = QLabel(key)
            k.setFixedWidth(65)
            k.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 12px;")
            v = QLabel(val)
            v.setStyleSheet("color: #cfe2f3; font-size: 12px; font-weight: 500;")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(k)
            row.addWidget(v)
            row.addStretch()
            layout.addLayout(row)

        layout.addSpacing(12)

        ok_btn = QPushButton("OK — Ready to run")
        ok_btn.setFixedHeight(38)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet("""
            QPushButton {
                background: #1a4a6e;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover { background: #2471a3; }
        """)
        ok_btn.clicked.connect(self.accept)
        layout.addWidget(ok_btn)

        self.adjustSize()
        if parent:
            geo = self.geometry()
            pg = parent.geometry()
            self.move(pg.center() - geo.center())
