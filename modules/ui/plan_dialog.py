import csv
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
    QMessageBox, QLabel
)
from PyQt5.QtCore import Qt

PLAN_COLUMNS = [
    "run", "label", "mode",
    "start_x", "start_y", "start_r",
    "num_alpides", "num_events", "strobe", "ithr",
    "energy", "MU", "current",
    "Exposure time (ms)", "Beam delay (ms)", "Beam on delay (ms)", "Beam off delay (ms)", "Loops",
    "Trigger Freq. (Hz)", "X step (mm)", "Y step (mm)", "R step (degree)",
    "qa_pos_x", "qa_pos_y", "qa_pos_r",
    "vel_x", "vel_y", "vel_r",
]

PLAN_DEFAULTS = {
    "run": "", "label": "", "mode": "treatment",
    "start_x": "0", "start_y": "0", "start_r": "0",
    "num_alpides": "6", "num_events": "30000", "strobe": "100", "ithr": "60",
    "energy": "200", "MU": "1000", "current": "10",
    "Exposure time (ms)": "1000", "Beam delay (ms)": "200",
    "Beam on delay (ms)": "200", "Beam off delay (ms)": "200", "Loops": "1",
    "Trigger Freq. (Hz)": "9500", "X step (mm)": "0",
    "Y step (mm)": "0", "R step (degree)": "0",
    "qa_pos_x": "", "qa_pos_y": "", "qa_pos_r": "",
    "vel_x": "0", "vel_y": "0", "vel_r": "0",
}

_BTN_STYLE = """
    QPushButton {
        font-size: 12px; background: #e8edf5; border: 1px solid #bcc8d8;
        border-radius: 5px; padding: 4px 12px; color: #1e3a5f;
    }
    QPushButton:hover { background: #d0dce8; }
"""
_BTN_PRIMARY_STYLE = """
    QPushButton {
        font-size: 13px; font-weight: bold; background: #1565C0;
        color: #fff; border: none; border-radius: 5px; padding: 4px 16px;
    }
    QPushButton:hover { background: #1976D2; }
"""


class CreatePlanDialog(QDialog):
    def __init__(self, current_fields=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Plan")
        self.setMinimumSize(1200, 460)
        self._current_fields = current_fields or {}
        self.saved_path = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── toolbar ──────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        btn_add    = QPushButton("+ Add Row")
        btn_remove = QPushButton("- Remove Row")
        btn_import = QPushButton("Import from current fields")
        btn_add.clicked.connect(self._add_row)
        btn_remove.clicked.connect(self._remove_row)
        btn_import.clicked.connect(self._import_current)
        for b in [btn_add, btn_remove, btn_import]:
            b.setFixedHeight(30)
            b.setStyleSheet(_BTN_STYLE)
        toolbar.addWidget(btn_add)
        toolbar.addWidget(btn_remove)
        toolbar.addWidget(btn_import)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── table ─────────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(PLAN_COLUMNS))
        self._table.setHorizontalHeaderLabels(PLAN_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(False)
        _col_notes = {
            "mode":            "ระบุ mode: \"treatment\" หรือ \"qa\"",
            "X step (mm)":     "Treatment mode only — ห้ามกรอกใน QA",
            "Y step (mm)":     "Treatment mode only — ห้ามกรอกใน QA",
            "R step (degree)": "Treatment mode only — ห้ามกรอกใน QA",
            "Loops":           "Treatment mode only — QA บังคับเป็น 1",
            "vel_x":           "QA mode only — ความเร็ว X (mm/s)",
            "vel_y":           "QA mode only — ความเร็ว Y (mm/s)",
            "vel_r":           "QA mode only — ความเร็ว R (°/s)",
        }
        for col, name in enumerate(PLAN_COLUMNS):
            if name in _col_notes:
                self._table.horizontalHeaderItem(col).setToolTip(_col_notes[name])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget {
                font-size: 12px; gridline-color: #dde5ef;
            }
            QHeaderView::section {
                background-color: #1e3a5f; color: #fff; font-weight: bold;
                font-size: 11px; padding: 4px; border: none;
            }
            QTableWidget::item:selected { background-color: #bbdefb; color: #1e2d3d; }
        """)
        layout.addWidget(self._table)

        # ── footer ────────────────────────────────────────────────────────
        footer = QHBoxLayout()
        btn_save   = QPushButton("Save CSV")
        btn_cancel = QPushButton("Cancel")
        btn_save.clicked.connect(self._save_csv)
        btn_cancel.clicked.connect(self.reject)
        btn_save.setFixedHeight(32)
        btn_cancel.setFixedHeight(32)
        btn_save.setStyleSheet(_BTN_PRIMARY_STYLE)
        btn_cancel.setStyleSheet(_BTN_STYLE)
        footer.addStretch()
        footer.addWidget(btn_save)
        footer.addWidget(btn_cancel)
        layout.addLayout(footer)

        self._add_row()

    # ── row helpers ───────────────────────────────────────────────────────

    def _add_row(self):
        row = self._table.rowCount()
        self._table.insertRow(row)
        defaults = dict(PLAN_DEFAULTS)
        defaults["run"] = str(row + 1)
        for col, key in enumerate(PLAN_COLUMNS):
            item = QTableWidgetItem(defaults.get(key, ""))
            item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, col, item)

    def _remove_row(self):
        rows = sorted(
            set(i.row() for i in self._table.selectedItems()), reverse=True
        )
        for r in rows:
            self._table.removeRow(r)
        for r in range(self._table.rowCount()):
            self._table.item(r, 0).setText(str(r + 1))

    def _import_current(self):
        row = self._table.rowCount()
        self._table.insertRow(row)
        defaults = dict(PLAN_DEFAULTS)
        defaults["run"] = str(row + 1)
        for col, key in enumerate(PLAN_COLUMNS):
            val = self._current_fields.get(key, defaults.get(key, ""))
            item = QTableWidgetItem(str(val))
            item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, col, item)

    def _save_csv(self):
        if self._table.rowCount() == 0:
            QMessageBox.warning(self, "Empty Plan",
                                "Add at least one run before saving.")
            return
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        fname, _ = QFileDialog.getSaveFileName(
            self, "Save Plan", "", "CSV Files (*.csv)", options=options
        )
        if not fname:
            return
        if not fname.endswith(".csv"):
            fname += ".csv"
        with open(fname, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(PLAN_COLUMNS)
            for r in range(self._table.rowCount()):
                writer.writerow([
                    (self._table.item(r, c).text()
                     if self._table.item(r, c) else "")
                    for c in range(len(PLAN_COLUMNS))
                ])
        self.saved_path = fname
        QMessageBox.information(self, "Saved", f"Plan saved:\n{fname}")
        self.accept()
