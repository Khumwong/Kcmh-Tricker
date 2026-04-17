# modules/ui/run.py
from PyQt5.QtWidgets import (
    QWidget, QPushButton, QLineEdit, QApplication, QMainWindow,
    QVBoxLayout, QHBoxLayout, QFrame, QSpacerItem, QSizePolicy,
    QMessageBox, QFileDialog, QCheckBox, QInputDialog,
    QLabel, QAction, qApp, QDialog, QGridLayout, QPlainTextEdit, QProgressBar, QToolButton,
    QScrollArea
    )
from PyQt5.QtCore import Qt, QRect, QSize, QMetaObject, Q_ARG, QTimer
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtGui import QIcon
from modules import eudaq
from modules.ui.rootwidget import RootWidget
from modules.ui.run_progress import RunProgress
from modules.serial_connect import get_port
import serial
import modules.zaber.connect as zaber_connect
import modules.zaber.motion as motion
import json
import os
from os import path
import subprocess
import modules.alpide as alpide
import usb
import time
import threading
import sys
import io
import psutil
from datetime import datetime

_ssh_password = None  # cached for session lifetime only


class _TeeWriter:
    """Write to both the original stdout and a StringIO buffer simultaneously."""
    def __init__(self, original, buffer):
        self._original = original
        self._buffer = buffer
    def write(self, s):
        self._original.write(s)
        self._buffer.write(s)
    def flush(self):
        self._original.flush()
        self._buffer.flush()
    def fileno(self):
        return self._original.fileno()


class EmbeddedTerminal(QWidget):
    """Poll tmux capture-pane และแสดงผลใน QPlainTextEdit — ไม่มี popup window."""

    POLL_MS = 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._refresh)
        self._last_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._display = QPlainTextEdit()
        self._display.setReadOnly(True)
        self._display.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d1a2e;
                color: #c8d8e8;
                font-family: 'Monospace', monospace;
                font-size: 10pt;
                border: none;
                padding: 4px;
                selection-background-color: #1e5080;
            }
        """)
        layout.addWidget(self._display)

    def launch(self, session_name: str = "ITS3", delay_ms: int = 1500):
        self._session = session_name
        self._display.setPlainText("")
        QTimer.singleShot(delay_ms, self._timer.start)

    def _refresh(self):
        result = subprocess.run(
            ['tmux', 'capture-pane', '-p', '-t', self._session],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return
        text = result.stdout
        if text == self._last_text:
            return
        self._last_text = text
        sb = self._display.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        self._display.setPlainText(text)
        if at_bottom:
            sb.setValue(sb.maximum())

    def terminate(self):
        self._timer.stop()
        self._session = None
        self._last_text = ""
        self._display.setPlainText("")

class RunWidget(QWidget):
    def __init__(self, window):
        super(RunWidget, self).__init__()
        self._ser = None
        self._window = window
        self._run_type = 0
        self._pid = None
        self._w = None
        self._opened_file = None
        self._first_file = None
        self._program_log_buffer = None
        self._run_stats_start = None
        self._checks = [0, 0]
        self._connection_icons = [QIcon('./images/link-break-2.svg'), 
                                  QIcon('./images/link-2.svg')]
        self._connect_styles = [
        """
            QPushButton {
                color: #ffcdd2;
                font-size: 14px;
                background-color: #c62828;
                border: none;
                border-radius: 6px;
                padding: 5px 14px;
            }
            QPushButton:hover {
                background-color: #e53935;
            }
        """,
        """
            QPushButton {
                color: #ffffff;
                font-size: 14px;
                background-color: #2e7d32;
                border: none;
                border-radius: 6px;
                padding: 5px 14px;
            }
            QPushButton:hover {
                background-color: #388e3c;
            }
        """,
        ]
        self._firmware_label = QLabel("● Firmware Installed")
        self._firmware_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rsync_header_label = QLabel("rsync: —")
        self._rsync_header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rsync_header_label.setFixedHeight(36)
        self._rsync_header_label.setVisible(True)
        self._rsync_header_label.setStyleSheet(
            "QLabel { font-size: 11px; font-weight: bold; background: transparent; border: none; "
            "padding: 3px 10px; font-family: monospace; color: rgba(255,255,255,0.35); }"
        )
        self._connection = {"alpide": QPushButton(" ALPIDE"),
                            "zaber": QPushButton(" Zaber"),
                            "fpga": QPushButton(" FPGA")}
        self._connection["alpide"].clicked.connect(lambda x: self.check_connection("alpide"))
        self._connection["fpga"].clicked.connect(lambda x: self.check_connection("fpga"))
        self._connection["zaber"].clicked.connect(lambda x: self.check_connection("zaber"))
        for v in self._connection.values():
            v.setCursor(Qt.CursorShape.PointingHandCursor)
            v.setIconSize(QSize(20, 20))
            v.setFixedWidth(150)
        self.check_connections()
    # for conn_name, is_conn in zip(["ALPIDE", "Zaber", "FPGA"], 
        #                      [self._window._alpide_connect, self._window._zaber_connect,
        #                       self._window._fpga_connect]):
        #     conn_layout = QHBoxLayout()
        #     conn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        #     conn_layout.addWidget(self._connection_icons[1] if is_conn else self._connection_icons[0])
        #     conn_label = QLabel(conn_name)
        #     conn_label.setStyleSheet("""
        #     QLabel{
        #         font-size: 24px;
        #     }
        #                              """)
        #     conn_icon_label = QLabel()
        #     conn_icon_label.setIcon
        #     conn_layout.addWidget()

        self._config_path = path.join(os.getcwd(), 'config.json')
        default_outpath = path.join(os.getcwd(), 'output')
        default_rsync_address = ''
        default_rsync_path = ''
        try:
            with open(self._config_path, 'r') as f:
                _cfg = json.load(f)
                default_outpath = _cfg.get('outpath', default_outpath)
                default_rsync_address = _cfg.get('rsync_address', '')
                default_rsync_path = _cfg.get('rsync_path', '')
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        self._outpath_label = QLabel(default_outpath)
        self._outpath_btn = QPushButton("output")
        self._outpath_btn.clicked.connect(self.chooseOutpath)
        self._rsync_addr_edit = QLineEdit(default_rsync_address)
        self._rsync_addr_edit.setPlaceholderText("user@host")
        self._rsync_path_edit = QLineEdit(default_rsync_path)
        self._rsync_path_edit.setPlaceholderText("/path/to/folder")
        self._rsync_connect_btn = QPushButton("Connect")
        self._rsync_connect_btn.clicked.connect(self._rsync_connect)
        self._rsync_status_label = QLabel("")
        self._rsync_status_label.setStyleSheet("QLabel{ font-size: 12px; color: #8898a8; font-family: monospace; }")
        self._rsync_toast = None
        self._current_file = None
        self._launch_eudaq_default = QPushButton("Launch default")
        self._launch_eudaq_default.setEnabled(False)
        self._kill_beam_btn = QPushButton("Kill beam")
        self._kill_beam_btn.setCheckable(True)
        self._kill_beam_btn.setEnabled(False)
        self._kill_beam_btn.clicked.connect(self.kill_beam_action)
        self._gate_checkbox = QCheckBox()
        # self._gate_checkbox.setText("Open Gate")
        # self._gate_checkbox.setStyleSheet("""
        # QCheckBox{
        #     font-size: 24px;
        # }
        # QCheckBox::indicator{
        #     width: 40px;
        #     height: 40px;
        # }
        #                                   """)
        # self._gate_checkbox.stateChanged.connect(lambda x: self.beam_action(1))
        self._enable_checkbox = QCheckBox()
        self._enable_checkbox.setText("Enable")
        self._enable_checkbox.setStyleSheet("""
        QCheckBox {
            font-size: 13px;
            color: #1e2d3d;
            spacing: 6px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 2px solid #bcc8d8;
            border-radius: 3px;
            background-color: #ffffff;
        }
        QCheckBox::indicator:checked {
            background-color: #1565C0;
            border-color: #1565C0;
        }
        QCheckBox::indicator:hover {
            border-color: #1565C0;
        }
        """)
        self._enable_checkbox.stateChanged.connect(self.enable_beam)
        self._enable_checkbox.setToolTip("Enable KCMH proton beam")
        self._launch_eudaq_default.clicked.connect(self.launch_eudaq)
        # self._kill_beam_btn.clicked.connect(lambda kind: self.launch_eudaq("auto"))
        self._kill_beam_btn.setFixedHeight(40)
        self._launch_eudaq_default.setFixedHeight(40)
        # self._launch_eudaq_default.setDisabled(True)
        self._launch_eudaq_default.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                background-color: #1565C0;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 36px;
                min-width: 160px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #bcc8d8;
                color: #8898a8;
            }
        """)
        self._kill_beam_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                background-color: #c62828;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 36px;
                min-width: 160px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            QPushButton:checked {
                background-color: #8e0000;
            }
            QPushButton:disabled {
                background-color: #bcc8d8;
                color: #8898a8;
            }
        """)
        self._line_edits = {
            "num_alpides": QLineEdit(),
            "num_events": QLineEdit(),
            "strobe": QLineEdit(),
            "ithr": QLineEdit(),
            "energy": QLineEdit(),
            "MU": QLineEdit(),
            "current": QLineEdit(),
            "Exposure time (ms)": QLineEdit(),
            "Beam delay (ms)": QLineEdit(),
            "Loops": QLineEdit(),
            "Trigger Freq. (Hz)": QLineEdit(),
            "X step (mm)": QLineEdit(),
            "Y step (mm)": QLineEdit(),
            "R step (degree)": QLineEdit()
        }
                         
        _field_defaults = {
            "num_alpides": "6", "num_events": "30000", "strobe": "100",
            "ithr": "60", "energy": "200", "MU": "1000", "current": "10",
            "Exposure time (ms)": "1000", "Beam delay (ms)": "200", "Loops": "1",
            "Trigger Freq. (Hz)": "9500", "X step (mm)": "0",
            "Y step (mm)": "0", "R step (degree)": "0",
        }
        _field_tooltips = {
            "num_alpides": "Number of ALPIDEs to do the test: 1 - 6",
            "num_events": "The total number of events to collect data",
            "strobe": "The STROBE length used for the telescope: 100 - 500",
            "ithr": "The threshold of all ALPIDEs: 1 - 400",
            "energy": "The energy used in the test: 70 - 220",
            "MU": "The monitor unit used for the test: 10 - 10000",
            "current": "The current used for KCMH beam: 4 - 300",
            "Exposure time (ms)": "The total exposure time used for the test: 1 - 100000",
            "Beam delay (ms)": "The delay beam hit event between phantom translations: 0 - 255",
            "Loops": "The loop of radiation: must be less than exposure time",
            "Trigger Freq. (Hz)": "The trigger frequency: 1 - 95000",
            "X step (mm)": "", "Y step (mm)": "", "R step (degree)": "",
        }
        # โหลดค่าล่าสุดจาก config ถ้ามี
        try:
            with open(self._config_path, 'r') as f:
                _saved_fields = json.load(f).get('fields', {})
        except (FileNotFoundError, json.JSONDecodeError):
            _saved_fields = {}
        for k, v in self._line_edits.items():
            v.setText(_saved_fields.get(k, _field_defaults.get(k, "")))
            if _field_tooltips.get(k):
                v.setToolTip(_field_tooltips[k])
        for k, v in self._line_edits.items():
            v.editingFinished.connect(lambda x=k: self.validate_fields(x))
            v.editingFinished.connect(self._save_fields)
            v.setFixedSize(150, 30)
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.setStyleSheet("""
                QLineEdit {
                    font-size: 14px;
                    font-weight: bold;
                    font-family: monospace;
                    background-color: #f4f7fb;
                    color: #1565C0;
                    border: 1px solid #90caf9;
                    border-radius: 5px;
                    padding: 2px 6px;
                    selection-background-color: #bbdefb;
                }
                QLineEdit:focus {
                    border: 1px solid #1565C0;
                    background-color: #eaf2ff;
                }
                QLineEdit:disabled {
                    background-color: #e8edf5;
                    color: #8898a8;
                    border-color: #c8d4e0;
                }
            """)
        # self._line_edits["num_alpides"].setToolTip("Number of alpide (1 - 6)")
        # self._line_edits["num_events"].setToolTip("")
        # self._line_edits["strobe"].setToolTip("")
        # self._line_edits["ithr"].setToolTip("")
        # self._line_edits["energy"].setToolTip("")
        # self._line_edits["MU"].setToolTip("")
        # self._line_edits["current"].setToolTip("")
        # self._line_edits["Exposure time (ms)"].setToolTip("")
        # self._line_edits["Beam delay (ms)"].setToolTip("")
        # self._line_edits["Loops"].setToolTip("")
        # self._line_edits["Trigger Freq. (Hz)"].setToolTip("")
        # self._line_edits["X step (mm)"].setToolTip("")
        # self._line_edits["Y step (mm)"].setToolTip("")
        # self._line_edits["R step (degree)"].setToolTip("")
        self._top_widget = QFrame()
        self._bottom_widget = QFrame()

        # ── Notification history ─────────────────────────────────────────
        self._notifications = []   # list of dicts {time, title, message, icon_color}
        self._unread_count = 0
        self._notif_panel = None   # created lazily

        # Bell button
        self._bell_btn = QPushButton("🔔")
        self._bell_btn.setFixedSize(36, 36)
        self._bell_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bell_btn.setToolTip("Notification history")
        self._bell_btn.setStyleSheet("""
            QPushButton {
                font-size: 17px;
                background-color: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 7px;
                color: #ffffff;
            }
            QPushButton:hover { background-color: rgba(255,255,255,0.18); }
            QPushButton:pressed { background-color: rgba(255,255,255,0.06); }
        """)
        self._bell_btn.clicked.connect(self._toggle_notification_panel)

        # Badge label (positioned as sibling inside a container QFrame)
        self._bell_badge = QLabel("")
        self._bell_badge.setAlignment(Qt.AlignCenter)
        self._bell_badge.setFixedSize(16, 16)
        self._bell_badge.setVisible(False)
        self._bell_badge.setStyleSheet("""
            QLabel {
                background-color: #ff4757;
                color: #ffffff;
                font-size: 9px;
                font-weight: bold;
                border-radius: 8px;
                border: 1px solid #1e3a5f;
            }
        """)
        self.init_ui()
        # poll firmware status ทุก 2 วินาที
        self._firmware_timer = QTimer(self)
        self._firmware_timer.setInterval(2000)
        self._firmware_timer.timeout.connect(self._update_firmware_label)
        self._firmware_timer.start()

    def init_ui(self):

        # ── shared style constants ──────────────────────────────────────
        CARD_STYLE = """
            QFrame {
                background-color: #ffffff;
                border: 1px solid #c0cfe0;
                border-radius: 8px;
            }
            QLabel { border: none; color: #1e2d3d; }
        """
        INNER_CELL_STYLE = """
            QFrame {
                border: 1px solid #b8c8d8;
                border-radius: 6px;
                background-color: #f0f4f8;
            }
            QLabel { border: none; }
        """
        SECTION_LABEL_STYLE = """
            QLabel {
                font-weight: bold;
                font-size: 13px;
                color: #ffffff;
                background: transparent;
                border: none;
                letter-spacing: 0.5px;
                padding: 0px 4px;
            }
        """
        FIELD_LABEL_STYLE = "QLabel { font-size: 12px; font-weight: 600; color: #2c4158; }"

        def make_separator():
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet("QFrame { background-color: #c0cfe0; border: none; }")
            return sep

        def make_section_header(title_text):
            """Returns a QFrame acting as a navy header bar."""
            header = QFrame()
            header.setStyleSheet("""
                QFrame {
                    background-color: #1e3a5f;
                    border-radius: 6px 6px 0px 0px;
                    border: none;
                }
                QLabel { border: none; }
            """)
            header.setFixedHeight(32)
            h_layout = QHBoxLayout(header)
            h_layout.setContentsMargins(12, 0, 12, 0)
            lbl = QLabel(title_text)
            lbl.setStyleSheet(SECTION_LABEL_STYLE)
            h_layout.addWidget(lbl)
            h_layout.addStretch(1)
            return header

        def make_field_cell(label_text, line_edit_widget):
            cell = QFrame()
            cell.setStyleSheet(INNER_CELL_STYLE)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(8, 6, 8, 6)
            cell_layout.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedHeight(22)
            lbl.setStyleSheet(FIELD_LABEL_STYLE)
            edit_row = QHBoxLayout()
            edit_row.addStretch()
            edit_row.addWidget(line_edit_widget)
            edit_row.addStretch()
            cell_layout.addWidget(lbl)
            cell_layout.addLayout(edit_row)
            return cell

        # ================================================================
        # HEADER  —  self._top_widget
        # ================================================================
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(12)
        for btn in self._connection.values():
            btn.setFixedHeight(36)
            header_layout.addWidget(btn)
        header_layout.addStretch(1)

        # bordered status box — firmware | rsync
        self._firmware_label.setFixedHeight(36)
        status_box = QFrame()
        status_box.setStyleSheet("""
            QFrame#statusBox {
                background-color: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.22);
                border-radius: 7px;
            }
            QLabel { border: none; }
        """)
        status_box.setObjectName("statusBox")
        status_box_layout = QHBoxLayout(status_box)
        status_box_layout.setContentsMargins(4, 0, 4, 0)
        status_box_layout.setSpacing(0)
        sep_v = QFrame()
        sep_v.setFrameShape(QFrame.VLine)
        sep_v.setFixedWidth(1)
        sep_v.setStyleSheet("QFrame { background-color: rgba(255,255,255,0.2); border: none; }")
        status_box_layout.addWidget(self._firmware_label)
        status_box_layout.addWidget(sep_v)
        status_box_layout.addWidget(self._rsync_header_label)
        header_layout.addWidget(status_box)

        # Bell button container (button + overlaid badge)
        bell_wrap = QFrame()
        bell_wrap.setFixedSize(44, 38)
        bell_wrap.setStyleSheet("QFrame { background: transparent; border: none; }")
        self._bell_btn.setParent(bell_wrap)
        self._bell_btn.setGeometry(0, 1, 36, 36)
        self._bell_badge.setParent(bell_wrap)
        self._bell_badge.setGeometry(24, 0, 16, 16)
        self._bell_badge.raise_()
        header_layout.addWidget(bell_wrap)

        self._top_widget.setStyleSheet("""
            QFrame {
                background-color: #1e3a5f;
                border-bottom: 1px solid #162d4a;
                border-radius: 0px;
            }
        """)
        self._top_widget.setFixedHeight(58)
        self._top_widget.setLayout(header_layout)

        # ================================================================
        # BODY  —  left panel (3) + right panel (7)
        # ================================================================
        body_widget = QWidget()
        body_widget.setStyleSheet("QWidget { background-color: #eef2f7; }")
        body_layout = QHBoxLayout(body_widget)
        body_layout.setContentsMargins(12, 10, 12, 10)
        body_layout.setSpacing(12)

        # ── LEFT PANEL ──────────────────────────────────────────────────
        left_panel = QWidget()
        left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # ── Phantom Control card ────────────────────────────────────────
        self._phantom_card = QFrame()
        self._phantom_card.setStyleSheet(CARD_STYLE)
        self._phantom_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        ph_card_layout = QVBoxLayout(self._phantom_card)
        ph_card_layout.setContentsMargins(0, 0, 0, 8)
        ph_card_layout.setSpacing(0)
        ph_card_layout.addWidget(make_section_header("Phantom Control"))

        ph_inner = QWidget()
        ph_inner_layout = QVBoxLayout(ph_inner)
        ph_inner_layout.setContentsMargins(10, 6, 10, 8)
        ph_inner_layout.setSpacing(4)

        # hidden compat labels — run_progress reads .text()
        self._ph_x_label = QLabel(self._window.orig_loc[0])
        self._ph_y_label = QLabel(self._window.orig_loc[1])
        self._ph_r_label = QLabel(self._window.orig_loc[2])
        for lbl in [self._ph_x_label, self._ph_y_label, self._ph_r_label]:
            lbl.setVisible(False)
            ph_inner_layout.addWidget(lbl)

        # hidden step edits — default "1", used by _ph_step()
        self._x_step_edit = QLineEdit("1")
        self._y_step_edit = QLineEdit("1")
        self._r_step_edit = QLineEdit("1")
        for e in [self._x_step_edit, self._y_step_edit, self._r_step_edit]:
            e.setVisible(False)

        # Go to edit inputs
        self._ph_x_edit_ctrl = QLineEdit(self._window.orig_loc[0])
        self._ph_y_edit_ctrl = QLineEdit(self._window.orig_loc[1])
        self._ph_r_edit_ctrl = QLineEdit(self._window.orig_loc[2])
        self._ph_x_edit_ctrl.textChanged.connect(lambda: self._ph_change_line_edit(0))
        self._ph_y_edit_ctrl.textChanged.connect(lambda: self._ph_change_line_edit(1))
        self._ph_r_edit_ctrl.textChanged.connect(lambda: self._ph_change_line_edit(2))

        _axis_lbl_style = "QLabel { font-size: 12px; font-weight: bold; color: #1e2d3d; border: none; min-width: 14px; }"
        _unit_lbl_style = "QLabel { font-size: 11px; color: #4a6078; border: none; }"
        _section_lbl_style = "QLabel { font-size: 11px; font-weight: bold; color: #4a6078; border: none; text-transform: uppercase; letter-spacing: 1px; }"
        _disp_style = ("QLabel { font-size: 13px; font-weight: bold; font-family: monospace;"
                       " color: #1565C0; background: #f4f7fb; border: 1px solid #dde5ef;"
                       " border-radius: 5px; padding: 3px 8px; min-width: 64px; }")
        _edit_style = ("QLineEdit { font-size: 12px; font-weight: bold; font-family: monospace;"
                       " border: 1px solid #90caf9; border-radius: 5px; padding: 3px 6px; min-width: 64px; }"
                       "QLineEdit:focus { border-color: #1565C0; }")
        _ph_action_style = """
            QPushButton { font-size: 11px; font-weight: bold; border-radius: 5px;
                padding: 4px 0px; color: #ffffff; border: none; background: #1565C0; }
            QPushButton:hover { background: #1976D2; }
            QPushButton:disabled { background: #bcc8d8; color: #8898a8; }
        """

        # display labels (realtime, updated by set_ph_loc_full)
        _disp_x = QLabel(self._window.orig_loc[0])
        _disp_y = QLabel(self._window.orig_loc[1])
        _disp_r = QLabel(self._window.orig_loc[2])
        self._ph_disp_labels = [_disp_x, _disp_y, _disp_r]
        for lbl in self._ph_disp_labels:
            lbl.setStyleSheet(_disp_style)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for e in [self._ph_x_edit_ctrl, self._ph_y_edit_ctrl, self._ph_r_edit_ctrl]:
            e.setFixedHeight(28)
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e.setStyleSheet(_edit_style)

        # ── grid body: Current | Go to | Buttons ────────────────────────
        from PyQt5.QtWidgets import QGridLayout
        ph_grid = QGridLayout()
        ph_grid.setSpacing(6)
        ph_grid.setColumnStretch(2, 1)  # disp stretch
        ph_grid.setColumnStretch(6, 1)  # edit stretch

        # headers row 0
        cur_hdr = QLabel("Current"); cur_hdr.setStyleSheet(_section_lbl_style)
        goto_hdr = QLabel("Go to");  goto_hdr.setStyleSheet(_section_lbl_style)
        ph_grid.addWidget(cur_hdr,  0, 0, 1, 4)
        ph_grid.addWidget(goto_hdr, 0, 5, 1, 3)

        # vertical separator spanning all data rows
        vsep = QFrame(); vsep.setFrameShape(QFrame.VLine)
        vsep.setStyleSheet("QFrame { background: #dde5ef; border: none; }")
        ph_grid.addWidget(vsep, 0, 4, 4, 1)

        axes_cfg = [
            ("X", _disp_x, self._ph_x_edit_ctrl, "mm"),
            ("Y", _disp_y, self._ph_y_edit_ctrl, "mm"),
            ("R", _disp_r, self._ph_r_edit_ctrl, "°"),
        ]
        btn_slots = [
            ("Home",   lambda: self._ph_locate("home")),
            ("Center", lambda: self._ph_locate("center")),
            ("Apply",  self._ph_apply),
        ]
        self._ph_apply_btn = QPushButton("Apply")

        for i, (axis, disp_lbl, edit, unit) in enumerate(axes_cfg):
            row = i + 1
            # Current side
            a_cur = QLabel(axis); a_cur.setStyleSheet(_axis_lbl_style); a_cur.setFixedWidth(14)
            u_cur = QLabel(unit); u_cur.setStyleSheet(_unit_lbl_style)
            ph_grid.addWidget(a_cur,    row, 0)
            ph_grid.addWidget(disp_lbl, row, 1)
            ph_grid.addWidget(u_cur,    row, 2)
            ph_grid.addWidget(QLabel(), row, 3)  # spacer

            # Go to side
            a_go = QLabel(axis); a_go.setStyleSheet(_axis_lbl_style); a_go.setFixedWidth(14)
            u_go = QLabel(unit); u_go.setStyleSheet(_unit_lbl_style)
            ph_grid.addWidget(a_go,  row, 5)
            ph_grid.addWidget(edit,  row, 6)
            ph_grid.addWidget(u_go,  row, 7)

            # Action button column
            label, slot = btn_slots[i]
            b = QPushButton(label)
            b.setStyleSheet(_ph_action_style)
            b.setFixedWidth(62)
            b.clicked.connect(slot)
            ph_grid.addWidget(b, row, 8)
            if label == "Apply":
                self._ph_apply_btn = b
                b.setEnabled(False)

        ph_body = QHBoxLayout()
        ph_body.addLayout(ph_grid)

        ph_inner_layout.addLayout(ph_body)
        ph_card_layout.addWidget(ph_inner)
        left_layout.addWidget(self._phantom_card)

        # Terminal panel — embed xterm/tmux ITS3 หลัง launch
        self._terminal_widget = EmbeddedTerminal(self)
        self._terminal_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._terminal_widget.setStyleSheet("""
            QWidget {
                background-color: #0d1a2e;
                border: 1px solid #2a3f58;
                border-radius: 6px;
            }
        """)
        left_layout.addWidget(self._terminal_widget, 1)

        # ── RIGHT PANEL ─────────────────────────────────────────────────
        right_panel = QWidget()
        right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # Output card
        outpath_card = QFrame()
        outpath_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #c0cfe0;
                border-radius: 8px;
            }
            QLabel { border: none; font-size: 12px; font-weight: 600; color: #2c4158; font-family: monospace; }
            QPushButton {
                font-size: 12px; background-color: #e8edf5; color: #1e3a5f;
                border: 1px solid #bcc8d8; border-radius: 5px; padding: 3px 10px;
            }
            QPushButton:hover { background-color: #d0dce8; color: #1e2d3d; }
        """)
        outpath_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outpath_card_layout = QVBoxLayout(outpath_card)
        outpath_card_layout.setContentsMargins(0, 0, 0, 8)
        outpath_card_layout.setSpacing(0)
        outpath_card_layout.addWidget(make_section_header("Output"))

        self._outpath_btn.setFixedWidth(120)
        self._outpath_btn.setFixedHeight(26)
        self._outpath_btn.setIcon(QIcon("./images/folder-open.svg"))
        outpath_row = QHBoxLayout()
        outpath_row.setSpacing(8)
        outpath_row.addWidget(self._outpath_label, 1)
        outpath_row.addWidget(self._outpath_btn)
        outpath_card_layout.addLayout(outpath_row)

        self._rsync_connect_btn.setFixedWidth(120)
        self._rsync_connect_btn.setFixedHeight(26)
        self._rsync_connect_btn.setIcon(QIcon("./images/link-2.svg"))
        rsync_addr_row = QHBoxLayout()
        rsync_addr_row.setSpacing(8)
        rsync_addr_row.addWidget(QLabel("SSH:"), 0)
        rsync_addr_row.addWidget(self._rsync_addr_edit, 1)
        rsync_addr_row.addWidget(QLabel("Path:"), 0)
        rsync_addr_row.addWidget(self._rsync_path_edit, 1)
        rsync_addr_row.addWidget(self._rsync_connect_btn)
        outpath_card_layout.addLayout(rsync_addr_row)


        right_layout.addWidget(outpath_card)

        # Controller card
        ctrl_card = QFrame()
        ctrl_card.setStyleSheet(CARD_STYLE)
        ctrl_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        ctrl_card_layout = QVBoxLayout(ctrl_card)
        ctrl_card_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_card_layout.setSpacing(0)

        ctrl_card_layout.addWidget(make_section_header("Controller"))

        ctrl_grid = QGridLayout()
        ctrl_grid.setSpacing(8)
        ctrl_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        ctrl_field_names = ["Exposure time (ms)", "Beam delay (ms)", "Loops", "Trigger Freq. (Hz)",
                            "X step (mm)", "Y step (mm)", "R step (degree)"]
        ctrl_keys = list(self._line_edits.keys())[7:]
        for idx, (display, key) in enumerate(zip(ctrl_field_names, ctrl_keys)):
            row, col = divmod(idx, 4)
            ctrl_grid.addWidget(make_field_cell(display, self._line_edits[key]), row, col)

        # Enable checkbox in slot (1, 3)
        cb_container = QFrame()
        cb_container.setStyleSheet(INNER_CELL_STYLE)
        cb_inner = QVBoxLayout(cb_container)
        cb_inner.setContentsMargins(8, 6, 8, 6)
        cb_inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb_inner.addWidget(self._enable_checkbox)
        ctrl_grid.addWidget(cb_container, 1, 3)

        ctrl_inner = QWidget()
        ctrl_inner_layout = QVBoxLayout(ctrl_inner)
        ctrl_inner_layout.setContentsMargins(10, 8, 10, 8)
        ctrl_inner_layout.addLayout(ctrl_grid)
        ctrl_card_layout.addWidget(ctrl_inner)
        right_layout.addWidget(ctrl_card, 1)

        # EUDAQ card
        eudaq_card = QFrame()
        eudaq_card.setStyleSheet(CARD_STYLE)
        eudaq_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        eudaq_card_layout = QVBoxLayout(eudaq_card)
        eudaq_card_layout.setContentsMargins(0, 0, 0, 0)
        eudaq_card_layout.setSpacing(0)

        eudaq_card_layout.addWidget(make_section_header("EUDAQ"))

        eudaq_grid = QGridLayout()
        eudaq_grid.setSpacing(8)
        eudaq_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        eudaq_field_names = ["# ALPIDEs", "Events", "STROBE", "I Threshold",
                             "Energy (MeV)", "MU", "Current (nA)"]
        eudaq_keys = list(self._line_edits.keys())[:7]
        for idx, (display, key) in enumerate(zip(eudaq_field_names, eudaq_keys)):
            row, col = divmod(idx, 4)
            eudaq_grid.addWidget(make_field_cell(display, self._line_edits[key]), row, col)

        eudaq_inner = QWidget()
        eudaq_inner_layout = QVBoxLayout(eudaq_inner)
        eudaq_inner_layout.setContentsMargins(10, 8, 10, 8)
        eudaq_inner_layout.addLayout(eudaq_grid)
        eudaq_card_layout.addWidget(eudaq_inner)
        right_layout.addWidget(eudaq_card, 1)

        # assemble body — Controller+EUDAQ ซ้าย(7), Output+Phantom+Terminal ขวา(3)
        body_layout.addWidget(right_panel, 7)
        body_layout.addWidget(left_panel, 3)

        # ================================================================
        # FOOTER  —  self._bottom_widget
        # ================================================================
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(20, 10, 20, 10)
        footer_layout.setSpacing(24)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._launch_eudaq_default)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._kill_beam_btn)
        footer_layout.addStretch(1)

        self._bottom_widget.setStyleSheet("""
            QFrame {
                background-color: #f0f4f8;
                border-top: 1px solid #c0cfe0;
                border-radius: 0px;
            }
        """)
        self._bottom_widget.setFixedHeight(62)
        self._bottom_widget.setLayout(footer_layout)

        # ================================================================
        # ROOT LAYOUT
        # ================================================================
        self._progress_section = self._build_progress_section()
        self._progress_section.setMaximumHeight(0)  # collapse without hiding — window won't resize

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._top_widget, 0)
        main_layout.addWidget(body_widget, 1)
        main_layout.addWidget(self._progress_section, 0)
        main_layout.addWidget(self._bottom_widget, 0)
        self.setLayout(main_layout)
    
    # ------------------------------------------------------------------ #
    #  Inline progress section                                            #
    # ------------------------------------------------------------------ #
    def _build_progress_section(self):
        section = QFrame()
        section.setStyleSheet("""
            QFrame { background-color: #0d1a2e; border-top: 1px solid #1e3a5f; }
        """)
        outer = QVBoxLayout(section)
        outer.setContentsMargins(20, 10, 20, 10)
        outer.setSpacing(8)

        # progress bar
        self._inline_progress_bar = QProgressBar()
        self._inline_progress_bar.setMaximum(1000)
        self._inline_progress_bar.setFixedHeight(32)
        self._inline_progress_bar.setFormat('')
        self._inline_progress_bar.setStyleSheet("""
            QProgressBar {
                color: #e8f4fd; border: 1px solid rgba(33,150,243,0.6);
                border-radius: 8px; background-color: #071020;
                text-align: center; font-size: 14px; font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1565C0, stop:1 #42a5f5);
                border-radius: 6px;
            }
        """)
        outer.addWidget(self._inline_progress_bar)

        # position + buttons row
        row = QHBoxLayout()
        row.setSpacing(16)

        loc_style = "QLabel { font-size: 13px; color: #00e676; font-family: monospace; font-weight: bold; }"
        self._inline_ph_locs = [QLabel("X: — mm"), QLabel("Y: — mm"), QLabel("R: — deg")]
        for lbl in self._inline_ph_locs:
            lbl.setStyleSheet(loc_style)
            row.addWidget(lbl)

        row.addStretch(1)

        btn_style = """
            QPushButton {
                font-size: 13px; font-weight: bold; border-radius: 6px;
                padding: 5px 24px; color: #e8f4fd; border: none;
            }
            QPushButton:disabled { background-color: #1a2a40; color: #446080; }
        """
        self._inline_run_btn = QPushButton("Run")
        self._inline_run_btn.setStyleSheet(
            btn_style + "QPushButton { background-color: #1565C0; } QPushButton:hover { background-color: #1976D2; }")
        self._inline_stop_btn = QPushButton("Stop")
        self._inline_stop_btn.setStyleSheet(
            btn_style + "QPushButton { background-color: #b71c1c; } QPushButton:hover { background-color: #d32f2f; }")
        row.addWidget(self._inline_run_btn)
        row.addWidget(self._inline_stop_btn)

        outer.addLayout(row)
        return section

    def _show_progress_section(self):
        # sync position labels with current phantom position
        self._inline_ph_locs[0].setText("X: " + self._ph_x_label.text() + " mm")
        self._inline_ph_locs[1].setText("Y: " + self._ph_y_label.text() + " mm")
        self._inline_ph_locs[2].setText("R: " + self._ph_r_label.text() + " deg")
        self._progress_section.setMaximumHeight(16777215)  # expand to natural height

    def _hide_progress_section(self):
        self._progress_section.setMaximumHeight(0)  # collapse to 0 — window stays same size
        self._inline_progress_bar.setValue(0)
        self._inline_progress_bar.setFormat('')

    # ------------------------------------------------------------------ #
    #  Phantom control methods                                             #
    # ------------------------------------------------------------------ #
    def _ph_step(self, axis, direction):
        step_edits = [self._x_step_edit, self._y_step_edit, self._r_step_edit]
        pos_edits  = [self._ph_x_edit_ctrl, self._ph_y_edit_ctrl, self._ph_r_edit_ctrl]
        limits     = [(0, 150), (0, 40), None]
        try:
            step = float(step_edits[axis].text())
            if limits[axis] is not None:
                cur = float(pos_edits[axis].text())
                lo, hi = limits[axis]
                if not (lo <= cur + step * direction <= hi):
                    QMessageBox.information(self, "Motion information",
                                            ["X", "Y", "R"][axis] + " axis is at limit.")
                    return
            conn = zaber_connect.connect(get_port("zaber"))
            motion.apply_step(conn, axis, direction * step)
            loc = motion.get_current_locations(conn)
            conn.close()
            self.set_ph_loc_full(["{:.2f}".format(l) for l in loc])
        except Exception as e:
            QMessageBox.critical(self, "Connection issue",
                                 f"Fail to connect Zaber.\n{e}")

    def _ph_locate(self, loc):
        if loc == "home":
            self._ph_x_edit_ctrl.setText("0")
            self._ph_y_edit_ctrl.setText("0")
            self._ph_r_edit_ctrl.setText("0")
        else:  # center
            self._ph_x_edit_ctrl.setText("99.0")
            self._ph_y_edit_ctrl.setText("0")
            self._ph_r_edit_ctrl.setText("0")
        self._ph_check_apply()

    def _ph_apply(self):
        self._ph_apply_btn.setEnabled(False)
        try:
            conn = zaber_connect.connect(get_port("zaber"))
            motion.apply_move(conn, (
                float(self._ph_x_edit_ctrl.text()),
                float(self._ph_y_edit_ctrl.text()),
                float(self._ph_r_edit_ctrl.text())
            ))
            loc = motion.get_current_locations(conn)
            conn.close()
            self.set_ph_loc_full(["{:.2f}".format(l) for l in loc])
        except Exception as e:
            QMessageBox.critical(self, "Connection issue",
                                 f"Fail to connect Zaber.\n{e}")

    def _ph_clear(self):
        loc = self._window.orig_loc
        self._ph_x_edit_ctrl.setText(loc[0])
        self._ph_y_edit_ctrl.setText(loc[1])
        self._ph_r_edit_ctrl.setText(loc[2])

    def _ph_change_line_edit(self, axis):
        self._ph_check_apply()

    def _ph_check_apply(self):
        try:
            float(self._ph_x_edit_ctrl.text())
            float(self._ph_y_edit_ctrl.text())
            float(self._ph_r_edit_ctrl.text())
            self._ph_apply_btn.setEnabled(True)
        except ValueError:
            self._ph_apply_btn.setEnabled(False)

    def set_ph_loc_full(self, loc):
        """อัพเดต Current position labels เท่านั้น — ไม่แตะ Go to inputs"""
        self._window.orig_loc = loc
        self._ph_x_label.setText(loc[0])
        self._ph_y_label.setText(loc[1])
        self._ph_r_label.setText(loc[2])
        if hasattr(self, '_ph_disp_labels'):
            for lbl, val in zip(self._ph_disp_labels, loc):
                lbl.setText(val)

    def open_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        fileName, _ = QFileDialog.getOpenFileName(self,"QFileDialog.getOpenFileName()", "","EDAQ Files (*.edaq)", options=options)
        if fileName:
            with open(fileName, 'r') as f:
                jsonData = json.load(f)
                for kdata in jsonData.keys():
                    self._line_edits[kdata].setText(str(jsonData[kdata]))
            self._opened_file = fileName
    
    def save_file(self, saveas=False):
        try:
            num_alpides = int(self._line_edits["num_alpides"].text())
            num_events = int(self._line_edits["num_events"].text())
            strobe_length = int(self._line_edits["strobe"].text())
            i_threshold = int(self._line_edits["ithr"].text())
            energy = int(self._line_edits["energy"].text())
            MU = int(self._line_edits["MU"].text())
            current = int(self._line_edits["current"].text())
            options = QFileDialog.Options()
            options |= QFileDialog.DontUseNativeDialog
            if (not saveas and self._opened_file) or (saveas and not self.open_file):
                data_dict = {}
                for k, v in self._line_edits.items():
                    data_dict[k] = int(v.text())
                with open(self._opened_file, 'w') as f:
                    json.dump(data_dict, f)
            else:
                fileName, _ = QFileDialog.getSaveFileName(self,"QFileDialog.getSaveFileName()", "","EDAQ Files (*.edaq)", options=options)
                if not fileName:
                    return
                real_file_name = fileName.split('/')[-1]
                is_edaq_file = "edaq" == real_file_name.split('.')[-1]
                data_dict = {}
                for k, v in self._line_edits.items():
                    data_dict[k] = int(v.text())
                write_file_name = fileName if is_edaq_file else "/" + path.join('', *fileName.split('/')[:-1], real_file_name + ".edaq")
                with open(write_file_name, 'w') as f:
                    json.dump(data_dict, f)
        except:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText("Error")
            msg.setInformativeText('Invalid input feild')
            msg.setWindowTitle("Error")
            msg.exec_()
    
    def viewRecentRaw(self):
        if not self._current_file:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText("Error")
            msg.setInformativeText('No resent RAW output')
            msg.setWindowTitle("Error")
            msg.exec_()
        else:
            eudaq.monitor(self._current_file)

    def viewRawFile(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        fileName, _ = QFileDialog.getOpenFileName(self,"QFileDialog.getOpenFileName()", self._outpath_label.text(),"RAW Files (*.raw)", options=options)
        if fileName:
            eudaq.monitor(fileName)
    
    def exportToRoot(self):
        self._exp_root_dialog = RootWidget(self)
        self._exp_root_dialog.exec_()
        """if self._w is None:
            self._w = RootWidget()
        self._w.show()"""

    def _set_rsync_status(self, text, color):
        self._rsync_status_label.setText(text)
        self._rsync_status_label.setStyleSheet(f"QLabel{{ font-size: 12px; color: {color}; font-family: monospace; }}")
        _base = "QLabel { font-size: 11px; font-weight: bold; background: transparent; border: none; padding: 3px 10px; font-family: monospace; }"
        if not text:
            self._rsync_header_label.setText("rsync: —")
            self._rsync_header_label.setStyleSheet(_base + "QLabel { color: rgba(255,255,255,0.35); }")
        else:
            self._rsync_header_label.setText(text)
            self._rsync_header_label.setStyleSheet(_base + f"QLabel {{ color: {color}; }}")

    @pyqtSlot(str, str)
    def _set_rsync_status_slot(self, text, color):
        self._set_rsync_status(text, color)

    @pyqtSlot(str, str)
    def _notify_rsync_slot(self, kind, detail):
        if kind == "ok":
            self._show_toast("rsync done ✓", detail)
        else:
            self._show_toast("rsync failed ✗", detail, icon="✗", icon_color="#ef5350")

    @pyqtSlot(str, str)
    def _monitor_done_slot(self, kind, detail):
        if kind == "ok":
            self._show_toast("monitor done ✓", detail)
        else:
            self._show_toast("monitor failed ✗", detail, icon="✗", icon_color="#ef5350")

    @pyqtSlot(str, str)
    def _rsync_progress_slot(self, pct, speed):
        if self._rsync_toast:
            self._rsync_toast.update_progress(pct, speed)

    @pyqtSlot(str, str)
    def _rsync_toast_done_slot(self, kind, detail):
        if self._rsync_toast:
            self._rsync_toast.set_done(success=(kind == "ok"), detail=detail)
            self._rsync_toast = None

    def _rsync_connect(self):
        addr = self._rsync_addr_edit.text().strip()
        rpath = self._rsync_path_edit.text().strip()
        if not addr or not rpath:
            QMessageBox.warning(self, "rsync", "Please fill in SSH address and remote path.")
            return
        pwd, ok = QInputDialog.getText(
            self, "SSH Password",
            f"Password for {addr}:\n(leave blank to use SSH key)",
            QLineEdit.Password
        )
        if not ok:
            return
        password = pwd if pwd.strip() else None
        self._set_rsync_status("connecting...", "#ffd740")
        _pwd_ssh_opts = [
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'PreferredAuthentications=keyboard-interactive,password',
            '-o', 'PubkeyAuthentication=no',
        ]
        _key_ssh_opts = ['-o', 'StrictHostKeyChecking=no']

        def _do_test():
            mkdir_cmd = f'mkdir -p "{rpath}/raw" "{rpath}/root" "{rpath}/scripts" "{rpath}/log"'
            if password:
                result = subprocess.run(
                    ['sshpass', '-p', password, 'ssh'] + _pwd_ssh_opts + [addr, mkdir_cmd],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            else:
                result = subprocess.run(
                    ['ssh'] + _key_ssh_opts + [addr, mkdir_cmd],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            err = result.stderr.decode(errors='replace').strip()
            if result.returncode != 0:
                QMetaObject.invokeMethod(self, "_rsync_connect_failed_slot",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, err))
                return
            import os as _os
            _proj_root = _os.path.normpath(
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..')
            )
            _scripts_to_upload = [
                _os.path.join(_proj_root, 'StdEventMonitor_fast.py'),
                _os.path.join(_proj_root, 'run_with_stats.py'),
            ]
            _script_dest = f"{addr}:{rpath}/scripts/"
            if password:
                rsync_result = subprocess.run(
                    ['sshpass', '-p', password, 'rsync', '-az',
                     '-e', 'ssh ' + ' '.join(_pwd_ssh_opts)]
                    + _scripts_to_upload + [_script_dest],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            else:
                rsync_result = subprocess.run(
                    ['rsync', '-az'] + _scripts_to_upload + [_script_dest],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            if rsync_result.returncode != 0:
                err = rsync_result.stderr.decode(errors='replace').strip()
                QMetaObject.invokeMethod(self, "_rsync_connect_failed_slot",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, f"Script upload failed: {err}"))
                return
            global _ssh_password
            _ssh_password = password
            try:
                with open(self._config_path, 'r') as f:
                    _cfg = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                _cfg = {}
            _cfg['rsync_address'] = addr
            _cfg['rsync_path'] = rpath
            with open(self._config_path, 'w') as f:
                json.dump(_cfg, f)
            QMetaObject.invokeMethod(self, "_rsync_connected_slot", Qt.ConnectionType.QueuedConnection)

        threading.Thread(target=_do_test, daemon=True).start()

    @pyqtSlot()
    def _rsync_connected_slot(self):
        self._set_rsync_status("rsync connected", "#69f0ae")

    @pyqtSlot(str)
    def _rsync_connect_failed_slot(self, err):
        global _ssh_password
        _ssh_password = None
        self._set_rsync_status("", "")
        self._show_toast("rsync connection failed", err[:200], icon="✗", icon_color="#ef5350")

    def chooseOutpath(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        options |= QFileDialog.ShowDirsOnly
        dirName = QFileDialog.getExistingDirectory(self,"QFileDialog.getExistingDirectory()", self._outpath_label.text(), options=options)
        if dirName:
            self._outpath_label.setText(dirName)
            try:
                with open(self._config_path, 'r') as f:
                    _cfg = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                _cfg = {}
            _cfg['outpath'] = dirName
            with open(self._config_path, 'w') as f:
                json.dump(_cfg, f)
    
    def initUI(self):
        main_layout = QVBoxLayout()
        top_layout = QVBoxLayout()
        sub_top_layout = QHBoxLayout()
        sub_top_layout.addWidget(QWidget(), 1)
        sub_top_layout.addWidget(self._firmware_label, 1)
        sub_top_layout.addWidget(QWidget(), 1)
        top_layout.addLayout(sub_top_layout)
        self._top_widget.setLayout(top_layout)

        outpath_outer_layout2 = QVBoxLayout()
        outpath_widget = QFrame()
        outpath_widget.setStyleSheet("""
            QFrame{
                border: 2px dotted rgba(0, 0, 0, 0.1);
                border-radius: 10px;
            }
            QLabel{
                border: 0px;
                font-size: 20px
            }
            QPushButton {
                font-size: 20px
            }
                                 """)
        self._outpath_btn.setFixedWidth(150)
        outpath_btn_icon = QIcon("./images/folder-open.svg")
        self._outpath_btn.setIcon(outpath_btn_icon)
        outpath_layout = QHBoxLayout()
        outpath_layout.addWidget(self._outpath_label)
        outpath_layout.addWidget(self._outpath_btn)
        outpath_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rsync_addr_layout2 = QHBoxLayout()
        self._rsync_connect_btn.setFixedWidth(150)
        self._rsync_connect_btn.setIcon(QIcon("./images/link-2.svg"))
        rsync_addr_layout2.addWidget(QLabel("SSH:"))
        rsync_addr_layout2.addWidget(self._rsync_addr_edit, 1)
        rsync_addr_layout2.addWidget(QLabel("Path:"))
        rsync_addr_layout2.addWidget(self._rsync_path_edit, 1)
        rsync_addr_layout2.addWidget(self._rsync_connect_btn)
        rsync_addr_layout2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outpath_outer_layout2.addLayout(outpath_layout)
        outpath_outer_layout2.addLayout(rsync_addr_layout2)
        self._rsync_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outpath_outer_layout2.addWidget(self._rsync_status_label)
        outpath_widget.setLayout(outpath_outer_layout2)

        bottom_layout = QVBoxLayout()
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame{
                border: 2px dotted rgba(0, 0, 0, 0.1);
                border-radius: 10px;
            }
            QLabel{
                border: 0px;
            }
                                 """)

        subsub_bottom_edit_layout = QHBoxLayout()
        l_names = ["Number of ALPIDEs", "Number of events", "STROBE length", "I Threshold"]
        for l_name, le_name in zip(l_names, list(self._line_edits.keys())[:4]):
            subsubsub_bottom_edit_layout = QVBoxLayout()
            widget = QFrame()
            widget.setStyleSheet("""
                QFrame {
                    border: 1px solid rgba(33, 150, 243, 0.2);
                    border-radius: 6px;
                    background-color: #091828;
                }
                QLabel { border: none; }
            """)
            edit_lable = QLabel(l_name)
            edit_lable.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit_lable.setFixedHeight(25)
            edit_lable.setStyleSheet("""QLabel {
                    font-size: 13px;
                    color: #90b4d4;
                }""")
            subsubsub_bottom_edit_layout.addWidget(QWidget(), 1)
            subsubsub_bottom_edit_layout.addWidget(edit_lable)
            edit_layout = QHBoxLayout()
            edit_layout.addStretch()
            edit_layout.addWidget(self._line_edits[le_name])
            edit_layout.addStretch()
            subsubsub_bottom_edit_layout.addLayout(edit_layout)
            subsubsub_bottom_edit_layout.addWidget(QWidget(), 4)
            widget.setLayout(subsubsub_bottom_edit_layout)
            subsub_bottom_edit_layout.addWidget(widget)


        widget_temp = QWidget()
        widget_temp.setLayout(subsub_bottom_edit_layout)
        bottom_layout.addWidget(widget_temp, 2)

        subsub_bottom_edit_layout = QHBoxLayout()
        l_names = ["Energy (MeV)", "MU", "Current (nA)"]
        for l_name, le_name in zip(l_names, list(self._line_edits.keys())[4:]):
            widget = QFrame()
            widget.setStyleSheet("""
                QFrame{
                    border: 2px dotted rgba(0, 0, 0, 0.1);
                    border-radius: 10px;
                }
                QLabel{
                    border: 0px;
                }
                                 """)
            subsubsub_bottom_edit_layout = QVBoxLayout()
            edit_lable = QLabel(l_name)
            edit_lable.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit_lable.setFixedHeight(25)
            edit_lable.setStyleSheet("""QLabel{
                    font-size: 20px;
                }""")
            subsubsub_bottom_edit_layout.addWidget(QWidget(), 1)
            subsubsub_bottom_edit_layout.addWidget(edit_lable)
            edit_layout = QHBoxLayout()
            edit_layout.addStretch()
            edit_layout.addWidget(self._line_edits[le_name])
            edit_layout.addStretch()
            subsubsub_bottom_edit_layout.addLayout(edit_layout)
            subsubsub_bottom_edit_layout.addWidget(QWidget(), 4)
            widget.setLayout(subsubsub_bottom_edit_layout)
            subsub_bottom_edit_layout.addWidget(widget)


        widget_temp = QWidget()
        widget_temp.setLayout(subsub_bottom_edit_layout)
        bottom_layout.addWidget(widget_temp, 2)

        run_btn_layout = QHBoxLayout()
        run_btn_layout.addWidget(QWidget(), 1)
        run_btn_layout.addWidget(self._launch_eudaq_default, 1)
        run_btn_layout.addWidget(QWidget(), 1)
        run_btn_layout.addWidget(self._kill_beam_btn, 1)
        run_btn_layout.addWidget(QWidget(), 1)
        # self._kill_beam_btn.setEnabled(False)
        # bottom_layout.addLayout(run_btn_layout, 1)
        widget_temp = QWidget()
        widget_temp.setLayout(run_btn_layout)
        bottom_layout.addWidget(widget_temp, 1)

        self._bottom_widget.setLayout(bottom_layout)
        main_layout.addWidget(self._top_widget, 1)
        main_layout.addWidget(outpath_widget, 1)
        main_layout.addWidget(self._bottom_widget, 2)
        self.setLayout(main_layout)
        # self._main_widget.setLayout(main_layout)
    
    def _update_firmware_label(self):
        _base = "QLabel { font-size: 12px; font-weight: bold; background: transparent; border: none; padding: 3px 10px; font-family: monospace; }"
        if not self._window._alpide_connect:
            self._firmware_label.setText("● No DAQ found")
            self._firmware_label.setStyleSheet(_base + "QLabel { color: #ef5350; }")
        elif not alpide.is_programmed():
            self._firmware_label.setText("⟳ Firmware Installing")
            self._firmware_label.setStyleSheet(_base + "QLabel { color: #ffd740; }")
        else:
            self._firmware_label.setText("● Firmware Installed")
            self._firmware_label.setStyleSheet(_base + "QLabel { color: #a5d6a7; }")
        # alpide_dir = "/home/santa/alpide-daq-software"
        # command_alpide = "alpide-daq-program --fx3={}/tmp/fx3.img --fpga={}/tmp/fpga-v1.0.0.bit --all"\
        #     .format(alpide_dir, alpide_dir)
        # command = f'gnome-terminal -- bash -c "cd {alpide_dir} && {command_alpide}; exec bash"'
        # process = subprocess.Popen(command_alpide, shell=True, stdout=subprocess.PIPE)
        # out, err = process.communicate()
        # out_lines = out.decode('utf-8').splitlines()
        # if out_lines[0] == "No unprogrammed FX3 device found. Skipping FX3 programming step." or\
        #     out_lines[1] == "No programmed FX3 device found. Skipping FPGA programming step.":
        #         print("XXXX")
    
    def clear_for_new(self):
        for line_edit in self._line_edits.values():
            line_edit.setText("")

    def launch_eudaq(self):
        self.check_connection('alpide')
        self.check_connection('fpga')
        connections = [
            self._window._alpide_connect,
            self.check_zaber_nohome(),
            self._window._zaber_connect,
            alpide.is_programmed()
            ]
        if not all(connections):
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            if connections[-1] == False:
                fail_dialog.setText("Unprogrammed DAQs.")
                fail_dialog.setWindowTitle("DAQs issue")
                fail_dialog.setDetailedText("Please program DAQs.")
            else:
                fail_dialog.setText("Fail to connect devices.")
                fail_dialog.setWindowTitle("Connection issue")
                fail_dialog.setDetailedText("Please reconnect devices.")
            fail_dialog.setStandardButtons(QMessageBox.Ok) 
            fail_dialog.exec_()
            return
        
        # fpga_data = self.get_fpga_data()
        # ser = serial.Serial(port=get_port("fpga"), baudrate=fpga_data["baudrate"], parity=fpga_data["parity"],
        #                 bytesize=fpga_data["bytesize"], stopbits=fpga_data["stopbits"], timeout=1)

        if self._enable_checkbox.checkState() != Qt.Checked:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            fail_dialog.setText("Enable is off!")
            fail_dialog.setWindowTitle("KCMH error")
            fail_dialog.setDetailedText("KCMH need to be enabled.")
            fail_dialog.setStandardButtons(QMessageBox.Ok) 
            fail_dialog.exec_()
            self._kill_beam_btn.setChecked(False)
            return
        
        # for b in fpga_data["byte_start_list"]:
        #     self._ser.write(b)
        self._launch_eudaq_default.setEnabled(False)
        self._first_file = self.get_new_outfile()
        self._pid = eudaq.default_run(self._line_edits, self._outpath_label.text())
        psutil.cpu_percent(interval=None)  # warm-up
        self._run_stats_start = {
            'time':  time.monotonic(),
            'disk':  psutil.disk_io_counters(),
            'net':   psutil.net_io_counters(),
        }
        try:
            import modules.sim as _sim
            _sim_log_path = _sim.sim_log_path
            self._program_log_buffer = ("sim", _sim_log_path, os.path.getsize(_sim_log_path))
        except (ImportError, AttributeError, OSError):
            self._program_log_buffer = io.StringIO()
            sys.stdout = _TeeWriter(sys.stdout, self._program_log_buffer)
        # reset Control Room กลับ Standby เมื่อเริ่ม EUDAQ session ใหม่
        try:
            import modules.sim as _sim
            if _sim.control_room is not None:
                _sim.control_room.reset()
        except (ImportError, AttributeError):
            pass
        # เริ่ม poll tmux ITS3 output (หลังจากที่ script เริ่มสร้าง session)
        self._terminal_widget.launch("ITS3", delay_ms=2000)
        # แสดง progress section ใน main window — ไม่ต้องเปิด dialog แยก
        self._show_progress_section()
        self._run_progress_dialog = RunProgress(
            window=self,
            progress_bar=self._inline_progress_bar,
            run_btn=self._inline_run_btn,
            stop_btn=self._inline_stop_btn,
            ph_locs=self._inline_ph_locs,
        )
        
    def stop_run(self):
        self._terminal_widget.terminate()
        self._hide_progress_section()
        # re-enable Kill beam ถ้า ser ยังอยู่ (beam อาจยังค้างอยู่หลัง run จบ)
        if self._ser is not None:
            self._kill_beam_btn.setChecked(False)  # reset state ก่อน ป้องกัน spurious trigger
            self._kill_beam_btn.setEnabled(True)
        if self._pid is not None:
            eudaq.stop(self._pid)
            self._show_toast("Run complete ✓", "All steps finished — waiting for Kill beam")

        if self._pid is not None and self.get_new_outfile() != self._first_file:
            self._first_file = self.get_new_outfile()
            self._current_file = self._first_file
            with open("./logs.txt", "a") as f:
                f.write(f"{self._current_file},{','.join([v.text() for v in self._line_edits.values()])}\n")
            # stop stdout capture and collect program log content
            _program_log_content = ""
            if isinstance(self._program_log_buffer, tuple) and self._program_log_buffer[0] == "sim":
                _, _sim_log_path, _sim_log_offset = self._program_log_buffer
                try:
                    with open(_sim_log_path, 'r', encoding='utf-8', errors='replace') as _f:
                        _f.seek(_sim_log_offset)
                        _program_log_content = _f.read()
                except OSError:
                    pass
            elif isinstance(self._program_log_buffer, io.StringIO):
                if isinstance(sys.stdout, _TeeWriter):
                    sys.stdout = sys.stdout._original
                _program_log_content = self._program_log_buffer.getvalue()
            self._program_log_buffer = None
            # append run stats block
            if self._run_stats_start is not None:
                _elapsed = time.monotonic() - self._run_stats_start['time']
                _disk_end = psutil.disk_io_counters()
                _net_end  = psutil.net_io_counters()
                _cpu      = psutil.cpu_percent(interval=None)
                _mem      = psutil.virtual_memory()
                _disk_w   = (_disk_end.write_bytes - self._run_stats_start['disk'].write_bytes) / 1024 / 1024
                _net_s    = (_net_end.bytes_sent   - self._run_stats_start['net'].bytes_sent)   / 1024 / 1024
                _net_r    = (_net_end.bytes_recv   - self._run_stats_start['net'].bytes_recv)   / 1024 / 1024
                _m, _s    = divmod(_elapsed, 60)
                try:
                    import subprocess as _sp
                    _gpu_r = _sp.run(
                        ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu',
                         '--format=csv,noheader,nounits'],
                        capture_output=True, text=True, timeout=3
                    )
                    if _gpu_r.returncode == 0:
                        _gu, _gmu, _gmt, _gt = [x.strip() for x in _gpu_r.stdout.strip().split(',')]
                        _gpu_line = f"  GPU       : util={_gu}%  mem={_gmu}/{_gmt} MiB  temp={_gt}°C\n"
                    else:
                        _gpu_line = ""
                except Exception:
                    _gpu_line = ""
                _program_log_content += (
                    "\n--- Run Stats ---\n"
                    f"  Elapsed   : {int(_m):02d}:{_s:05.2f}\n"
                    f"  CPU       : {_cpu:.1f}%\n"
                    f"  RAM       : {_mem.used//1024//1024}/{_mem.total//1024//1024} MiB ({_mem.percent:.1f}%)\n"
                    + _gpu_line +
                    f"  Disk write: {_disk_w:.1f} MiB\n"
                    f"  Net sent  : {_net_s:.1f} MiB\n"
                    f"  Net recv  : {_net_r:.1f} MiB\n"
                    "-----------------\n"
                )
                self._run_stats_start = None
            rsync_addr = self._rsync_addr_edit.text().strip()
            rsync_rpath = self._rsync_path_edit.text().strip()
            rsync_dest = f"{rsync_addr}:{rsync_rpath}/raw" if rsync_addr and rsync_rpath else ""
            if rsync_dest and self._current_file:
                import re as _re
                from modules.ui.rsync_toast import RsyncToast
                _rsync_pct_re = _re.compile(r'(\d+)%\s+([\d.]+\S+/s)')
                _pwd_ssh_opts = [
                    '-o', 'StrictHostKeyChecking=no',
                    '-o', 'PreferredAuthentications=keyboard-interactive,password',
                    '-o', 'PubkeyAuthentication=no',
                ]
                _key_ssh_opts = ['-o', 'StrictHostKeyChecking=no']
                print(f"[rsync] {self._current_file} → {rsync_dest}")
                fname_short = self._current_file.split('/')[-1]
                self._rsync_toast = RsyncToast(fname_short, rsync_addr, parent=self._window)
                self._rsync_toast.show_centered(self._window)

                def _stream_rsync(proc):
                    for raw in proc.stdout:
                        line = raw.decode('utf-8', errors='replace').rstrip()
                        m = _rsync_pct_re.search(line)
                        if m:
                            pct, speed = m.group(1), m.group(2)
                            QMetaObject.invokeMethod(self, "_rsync_progress_slot",
                                Qt.ConnectionType.QueuedConnection,
                                Q_ARG(str, pct), Q_ARG(str, speed))
                    proc.wait()
                    return proc.returncode, proc.stderr.read()

                def _rsync_program_log(fname, log_content, password):
                    import os as _os, tempfile as _tempfile
                    fname_base = _os.path.splitext(fname)[0]
                    with _tempfile.NamedTemporaryFile(
                        mode='w', suffix='.log', prefix=f"{fname_base}_program_",
                        delete=False, encoding='utf-8'
                    ) as tf:
                        tf.write(log_content)
                        tmp_path = tf.name
                    remote_log = f"{rsync_rpath}/log/{fname_base}_program.log"
                    log_dest = f"{rsync_addr}:{remote_log}"
                    print(f"[program log] rsync → {log_dest}")
                    if password:
                        result = subprocess.run(
                            ['sshpass', '-p', password, 'rsync', '-az',
                             '-e', 'ssh ' + ' '.join(_pwd_ssh_opts),
                             tmp_path, log_dest],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                        )
                    else:
                        result = subprocess.run(
                            ['rsync', '-az', tmp_path, log_dest],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                        )
                    _os.unlink(tmp_path)
                    if result.returncode == 0:
                        print(f"[program log] done → {remote_log}")
                    else:
                        print(f"[program log] ERROR: {result.stderr.decode(errors='replace').strip()}")

                def _run_monitor(fname, password):
                    import os as _os
                    fname_base = _os.path.splitext(fname)[0]
                    remote_raw     = f"{rsync_rpath}/raw/{fname}"
                    remote_root    = f"{rsync_rpath}/root/{fname_base}.root"
                    remote_wrapper = f"{rsync_rpath}/scripts/run_with_stats.py"
                    remote_log     = f"{rsync_rpath}/log/{fname_base}_std.log"
                    cmd = (
                        f'~/sutpct-env/bin/python3 "{remote_wrapper}"'
                        f' "{remote_raw}" -o "{remote_root}"'
                        f' > "{remote_log}" 2>&1'
                    )
                    print(f"[monitor] SSH → {rsync_addr}: {cmd}")
                    if password:
                        result = subprocess.run(
                            ['sshpass', '-p', password, 'ssh'] + _pwd_ssh_opts + [rsync_addr, cmd],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                        )
                    else:
                        result = subprocess.run(
                            ['ssh'] + _key_ssh_opts + [rsync_addr, cmd],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                        )
                    if result.returncode == 0:
                        print(f"[monitor] done → {remote_root}")
                        QMetaObject.invokeMethod(self, "_monitor_done_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "ok"), Q_ARG(str, f"{fname_base}.root"))
                    else:
                        err_msg = result.stderr.decode(errors='replace').strip()
                        print(f"[monitor] ERROR: {err_msg}")
                        QMetaObject.invokeMethod(self, "_monitor_done_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "error"), Q_ARG(str, err_msg[:200]))

                def _do_rsync(filepath, dest, password):
                    if password:
                        proc = subprocess.Popen(
                            ['sshpass', '-p', password, 'rsync', '-az', '--progress',
                             '-e', 'ssh ' + ' '.join(_pwd_ssh_opts),
                             filepath, dest],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )
                    else:
                        proc = subprocess.Popen(
                            ['rsync', '-az', '--progress', filepath, dest],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE
                        )
                    returncode, err = _stream_rsync(proc)
                    if returncode == 0:
                        print(f"[rsync] OK → {dest}")
                        QMetaObject.invokeMethod(self, "_rsync_toast_done_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "ok"), Q_ARG(str, f"Sent to {dest.split(':')[0]}"))
                        QMetaObject.invokeMethod(self, "_notify_rsync_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "ok"), Q_ARG(str, f"Sent to {dest.split(':')[0]}"))
                        threading.Thread(target=_run_monitor, args=(fname_short, password), daemon=True).start()
                        threading.Thread(target=_rsync_program_log, args=(fname_short, _program_log_content, password), daemon=True).start()
                    else:
                        err_msg = err.decode(errors='replace').strip()
                        print(f"[rsync] ERROR (code {returncode}): {err_msg}")
                        global _ssh_password
                        _ssh_password = None
                        if returncode == 23 or 'auth' in err_msg.lower() or 'permission denied' in err_msg.lower() or 'password' in err_msg.lower():
                            detail = f"Authentication failed — reconnect required\n{err_msg[:120]}"
                        else:
                            detail = f"Exit code {returncode}\n{err_msg[:120]}"
                        QMetaObject.invokeMethod(self, "_set_rsync_status_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "rsync fail"), Q_ARG(str, "#ef5350"))
                        QMetaObject.invokeMethod(self, "_rsync_toast_done_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "error"), Q_ARG(str, detail))
                        QMetaObject.invokeMethod(self, "_notify_rsync_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "error"), Q_ARG(str, detail))
                        QMetaObject.invokeMethod(self, "_rsync_connect_failed_slot",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, detail))
                threading.Thread(target=_do_rsync, args=(self._current_file, rsync_dest, _ssh_password), daemon=True).start()
                rsync_note = f"rsync → {rsync_addr} (sending...)"
            else:
                print(f"[rsync] skipped — dest='{rsync_dest}' file='{self._current_file}'")
                rsync_note = "rsync: skipped"
            fname = self._first_file.split('/')[-1] if self._first_file else "—"
            self._show_toast("Saved ✓", f"{fname}\n{rsync_note}")
        elif self._pid is not None and self.get_new_outfile() == self._first_file:
            self._current_file = None
            self._show_toast("No output file", "Run stopped without saving data", icon="✗", icon_color="#ef5350")
        self._pid = None

    def get_new_outfile(self):
        try:
            files = [os.path.join(self._outpath_label.text(), file) for file in os.listdir(self._outpath_label.text())]
        except FileNotFoundError:
            return None
        files = [myfile for myfile in files if os.path.isfile(myfile)]
        if files:
            return max(files, key=os.path.getmtime)
        else:
            return None
    
    def get_fpga_data(self):
        baudrate = 115200
        parity = serial.PARITY_NONE
        bytesize = serial.EIGHTBITS
        stopbits = serial.STOPBITS_ONE
        trigger_f_bin = bin(int(self._line_edits["Trigger Freq. (Hz)"].text())).lstrip('0b').zfill(16)
        trigger_f_byte_list = [int(trigger_f_bin[:-8], 2).to_bytes(1, 'big'), int(trigger_f_bin[-8:], 2).to_bytes(1, 'big')]
        alpide_delay = bin(int(self._line_edits["Beam delay (ms)"].text())).lstrip('0b').zfill(8)
        alpide_delay_byte = int(alpide_delay, 2).to_bytes(1, 'big')
        byte_start_list = [b'\x00', b'\x01', b'\x00', b'\x00', b'\x00', b'\x00', alpide_delay_byte, trigger_f_byte_list[0],
            trigger_f_byte_list[1]]
        return {
            "baudrate": baudrate,
            "parity": parity,
            "bytesize": bytesize,
            "stopbits": stopbits,
            "byte_start_list": byte_start_list
        }

    def enable_beam(self):
        if self._enable_checkbox.isChecked():
            if not (self._window._alpide_connect and self._window._zaber_connect and self._window._fpga_connect):
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Warning)
                msg.setText("Not all devices connected")
                msg.setInformativeText("Please connect ALPIDE, Zaber, and FPGA before enabling.")
                msg.setWindowTitle("Warning")
                msg.exec_()
                self._enable_checkbox.setChecked(False)
                return
        try:
            if self._ser:
                try:
                    self.ser.close()
                except:
                    pass

            fpga_data = self.get_fpga_data()
            self._ser = serial.Serial(port=get_port("fpga"), baudrate=fpga_data["baudrate"], parity=fpga_data["parity"],
                            bytesize=fpga_data["bytesize"], stopbits=fpga_data["stopbits"], timeout=1)
            
            self._ser.write(b'\x00')
            self._ser.write(b'\x00')
                
            self._kill_beam_btn.setChecked(False)
            if self._enable_checkbox.checkState() == Qt.Checked:
                self._ser.write(b'\x02')
                for b in fpga_data["byte_start_list"][1:]:
                    self._ser.write(b)
                has_rsync = bool(self._rsync_addr_edit.text().strip() and self._rsync_path_edit.text().strip())
                self._kill_beam_btn.setEnabled(has_rsync)
                self._launch_eudaq_default.setEnabled(has_rsync)
                if not has_rsync:
                    msg = QMessageBox()
                    msg.setIcon(QMessageBox.Warning)
                    msg.setText("rsync destination is empty")
                    msg.setInformativeText("Please fill in SSH address and remote path, then click Connect.")
                    msg.setWindowTitle("Warning")
                    msg.exec_()
                self._window.running(True)
            else:
                self._ser.write(b'\xF2')
                self._kill_beam_btn.setEnabled(False)
                self._launch_eudaq_default.setEnabled(False)
                self._ser = None
                self._window.running(False)
            # ser.close()
            # except:
            #     pass
        except ConnectionError:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            fail_dialog.setText("No FPGA connection")
            fail_dialog.setWindowTitle("FPGA error")
            fail_dialog.setDetailedText("Please connect to FPGA")
            fail_dialog.setStandardButtons(QMessageBox.Ok) 
            fail_dialog.exec_()
            self._kill_beam_btn.setChecked(False)
            self._kill_beam_btn.setEnabled(False)
            self._launch_eudaq_default.setEnabled(False)
            return
    
    def set_ph_loc(self, loc_str):
        self.set_ph_loc_full(loc_str)
    
    def check_connections(self):
        if self._window._alpide_connect:
            self._connection["alpide"].setIcon(self._connection_icons[1])
            self._connection["alpide"].setStyleSheet(self._connect_styles[1])
        else:
            self._connection["alpide"].setIcon(self._connection_icons[0])
            self._connection["alpide"].setStyleSheet(self._connect_styles[0])
        if self._window._zaber_connect:
            self._connection["zaber"].setIcon(self._connection_icons[1])
            self._connection["zaber"].setStyleSheet(self._connect_styles[1])
        else:
            self._connection["zaber"].setIcon(self._connection_icons[0])
            self._connection["zaber"].setStyleSheet(self._connect_styles[0])
        if self._window._fpga_connect:
            self._connection["fpga"].setIcon(self._connection_icons[1])
            self._connection["fpga"].setStyleSheet(self._connect_styles[1])
        else:
            self._connection["fpga"].setIcon(self._connection_icons[0])
            self._connection["fpga"].setStyleSheet(self._connect_styles[0])
            
        self._update_firmware_label()

    def check_connection(self, device):
        if device == "alpide":
            if alpide.found_daqs():
                self._window._alpide_connect = True
            else:
                self._window._alpide_connect = False
        elif device == "zaber":
            if self._window.check_zaber():
                self._window._zaber_connect = True
            else:
                self._window._zaber_connect = False
        elif device == "fpga":
            if self._window.check_fpga():
                self._window._fpga_connect = True
            else:
                self._window._fpga_connect = False
                
        if device == "alpide":
            if self._window._alpide_connect:
                self._connection["alpide"].setIcon(self._connection_icons[1])
                self._connection["alpide"].setStyleSheet(self._connect_styles[1])
            else:
                self._connection["alpide"].setIcon(self._connection_icons[0])
                self._connection["alpide"].setStyleSheet(self._connect_styles[0])
        elif device == "zaber":
            if self._window._zaber_connect:
                self._connection["zaber"].setIcon(self._connection_icons[1])
                self._connection["zaber"].setStyleSheet(self._connect_styles[1])
            else:
                self._connection["zaber"].setIcon(self._connection_icons[0])
                self._connection["zaber"].setStyleSheet(self._connect_styles[0])
        elif device == "fpga":
            if self._window._fpga_connect:
                self._connection["fpga"].setIcon(self._connection_icons[1])
                self._connection["fpga"].setStyleSheet(self._connect_styles[1])
            else:
                self._connection["fpga"].setIcon(self._connection_icons[0])
                self._connection["fpga"].setStyleSheet(self._connect_styles[0])
        
        self._update_firmware_label()

    def check_zaber_nohome(self):
        try:
            conn = zaber_connect.connect(get_port("zaber"))
            loc = motion.get_current_locations(conn)
            if ("_ph_widget" in self.__dict__.keys()):
                self._ph_widget.set_all_loc(loc)
            conn.close()
            return True
        except:
            return False
        
    def kill_beam_action(self):
        # fpga_data = self.get_fpga_data()
        # initailize serial may cause enable off
        # ser = serial.Serial(port=get_port("fpga"), baudrate=fpga_data["baudrate"], parity=fpga_data["parity"],
        #                 bytesize=fpga_data["bytesize"], stopbits=fpga_data["stopbits"], timeout=1)

        # ser.write(b'\xEF')
        # ser.close()
        
        
        # for b in fpga_data["byte_start_list"]:
        #         ser.write(b)
        if self._enable_checkbox.checkState() != Qt.Checked:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            fail_dialog.setText("Enable is off!")
            fail_dialog.setWindowTitle("KCMH error")
            fail_dialog.setDetailedText("KCMH need to be enabled.")
            fail_dialog.setStandardButtons(QMessageBox.Ok) 
            fail_dialog.exec_()
            self._kill_beam_btn.setChecked(False)
            return
        if not self._ser:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            fail_dialog.setText("FPGA not found!")
            fail_dialog.setWindowTitle("FPGA error")
            fail_dialog.setDetailedText("FPGA is not ready.")
            fail_dialog.setStandardButtons(QMessageBox.Ok) 
            fail_dialog.exec_()
            self._kill_beam_btn.setChecked(False)
            return
        

        if self._kill_beam_btn.isChecked():
            # self._ser.write(b'\x03')
            self._ser.write(b'\xFE')
            self._launch_eudaq_default.setEnabled(False)
            self._window.running(True)
            # sim: เริ่ม residual delivery และ connect signal เพื่อ reset UI เมื่อเสร็จ
            try:
                import modules.sim as _sim
                if _sim.control_room is not None:
                    _sim.control_room.beam_off_signal.connect(self._on_residual_done)
                    _sim.control_room.start_residual_delivery()
            except (ImportError, AttributeError):
                pass
            # self._window.running(True)
            # self._enable_checkbox.setDisabled(True)
            # self._gate_checkbox.setDisabled(True)
        else:
            # self._ser.write(b'\xF3')
            self._ser.write(b'\xEF')
            self._launch_eudaq_default.setEnabled(True)
            self._window.running(True)
            # self._window.running(False)
            # self._gate_checkbox.setDisabled(False)
            # self._enable_checkbox.setDisabled(False)

    def _save_fields(self):
        """บันทึกค่า field ทั้งหมดลง config.json"""
        try:
            try:
                with open(self._config_path, 'r') as f:
                    _cfg = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                _cfg = {}
            _cfg['fields'] = {k: v.text() for k, v in self._line_edits.items()}
            with open(self._config_path, 'w') as f:
                json.dump(_cfg, f, indent=2)
        except Exception:
            pass

    def _on_residual_done(self):
        """Control Room ส่ง residual beam ครบ → reset Kill beam UI พร้อม run ครั้งถัดไป"""
        try:
            import modules.sim as _sim
            if _sim.control_room is not None:
                try:
                    _sim.control_room.beam_off_signal.disconnect(self._on_residual_done)
                except TypeError:
                    pass
        except (ImportError, AttributeError):
            pass
        self._kill_beam_btn.setChecked(False)
        self._kill_beam_btn.setEnabled(False)
        self._launch_eudaq_default.setEnabled(True)
        self._window.running(False)
        self._show_toast("Beam cleared ✓", "Ready for next run")

    # ── Notification bell ────────────────────────────────────────────────

    def _update_bell_badge(self):
        if self._unread_count > 0:
            self._bell_badge.setText(str(min(self._unread_count, 99)))
            self._bell_badge.setVisible(True)
            self._bell_btn.setStyleSheet("""
                QPushButton {
                    font-size: 17px;
                    background-color: rgba(255,71,87,0.25);
                    border: 1px solid #ff4757;
                    border-radius: 7px;
                    color: #ffffff;
                }
                QPushButton:hover { background-color: rgba(255,71,87,0.38); }
            """)
        else:
            self._bell_badge.setVisible(False)
            self._bell_btn.setStyleSheet("""
                QPushButton {
                    font-size: 17px;
                    background-color: rgba(255,255,255,0.08);
                    border: 1px solid rgba(255,255,255,0.18);
                    border-radius: 7px;
                    color: #ffffff;
                }
                QPushButton:hover { background-color: rgba(255,255,255,0.18); }
                QPushButton:pressed { background-color: rgba(255,255,255,0.06); }
            """)

    def _toggle_notification_panel(self):
        if self._notif_panel is None:
            self._build_notification_panel()

        if self._notif_panel.isVisible():
            self._notif_panel.hide()
        else:
            # reset unread on open
            self._unread_count = 0
            self._update_bell_badge()
            self._rebuild_notif_list()
            self._reposition_notif_panel()
            self._notif_panel.show()
            self._notif_panel.raise_()

    def _reposition_notif_panel(self):
        if self._notif_panel is None:
            return
        panel_w = self._notif_panel.width()
        x = self.width() - panel_w - 12
        y = 60  # just below header
        self._notif_panel.move(x, y)

    def _build_notification_panel(self):
        """Create the floating notification panel (lazy)."""
        panel = QFrame(self)
        panel.setObjectName("notifPanel")
        panel.setFixedWidth(360)
        panel.setStyleSheet("""
            QFrame#notifPanel {
                background-color: #0d1a2e;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 10px;
            }
        """)

        outer_layout = QVBoxLayout(panel)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── panel header bar ─────────────────────────────────────────────
        header_bar = QFrame()
        header_bar.setFixedHeight(42)
        header_bar.setStyleSheet("""
            QFrame {
                background-color: #1e3a5f;
                border-radius: 10px 10px 0px 0px;
                border: none;
            }
            QLabel { border: none; color: #e0e8f8; font-size: 13px; font-weight: bold; }
        """)
        hb_layout = QHBoxLayout(header_bar)
        hb_layout.setContentsMargins(14, 0, 10, 0)
        hb_layout.addWidget(QLabel("🔔  Notifications"))
        hb_layout.addStretch()
        clear_btn = QPushButton("Clear all")
        clear_btn.setFixedHeight(26)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255,255,255,0.1);
                color: #b0c8e8;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 5px;
                font-size: 11px;
                padding: 0px 10px;
            }
            QPushButton:hover { background-color: rgba(255,255,255,0.2); color: #ffffff; }
        """)
        clear_btn.clicked.connect(self._clear_notifications)
        hb_layout.addWidget(clear_btn)
        outer_layout.addWidget(header_bar)

        # ── scrollable list area ─────────────────────────────────────────
        self._notif_scroll = QScrollArea()
        self._notif_scroll.setWidgetResizable(True)
        self._notif_scroll.setFrameShape(QFrame.NoFrame)
        self._notif_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._notif_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: #0d1a2e; width: 6px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.2); border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._notif_list_widget = QWidget()
        self._notif_list_widget.setStyleSheet("QWidget { background: transparent; }")
        self._notif_list_layout = QVBoxLayout(self._notif_list_widget)
        self._notif_list_layout.setContentsMargins(8, 8, 8, 8)
        self._notif_list_layout.setSpacing(6)
        self._notif_list_layout.addStretch()
        self._notif_scroll.setWidget(self._notif_list_widget)
        outer_layout.addWidget(self._notif_scroll)

        panel.hide()
        self._notif_panel = panel

    def _rebuild_notif_list(self):
        """Repopulate notification list items."""
        layout = self._notif_list_layout
        # remove all except the trailing stretch
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._notifications:
            empty_lbl = QLabel("No notifications yet")
            empty_lbl.setAlignment(Qt.AlignCenter)
            empty_lbl.setStyleSheet("QLabel { color: rgba(255,255,255,0.3); font-size: 12px; padding: 24px; border: none; }")
            layout.insertWidget(0, empty_lbl)
        else:
            for i, n in enumerate(self._notifications):
                row = self._make_notif_row(n)
                layout.insertWidget(i, row)

        # resize panel height to fit (max 420)
        self._notif_list_widget.adjustSize()
        desired = min(max(self._notif_list_widget.sizeHint().height() + 52, 90), 420)
        self._notif_panel.setFixedHeight(desired)

    def _make_notif_row(self, n):
        row = QFrame()
        row.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-left: 3px solid {n['icon_color']};
                border-radius: 6px;
            }}
            QLabel {{ border: none; }}
        """)
        rl = QVBoxLayout(row)
        rl.setContentsMargins(10, 7, 10, 7)
        rl.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        icon_lbl = QLabel(n["icon"])
        icon_lbl.setStyleSheet(f"QLabel {{ color: {n['icon_color']}; font-size: 13px; }}")
        title_lbl = QLabel(n["title"])
        title_lbl.setStyleSheet(f"QLabel {{ color: {n['icon_color']}; font-size: 12px; font-weight: bold; }}")
        time_lbl = QLabel(n["time"])
        time_lbl.setStyleSheet("QLabel { color: rgba(255,255,255,0.3); font-size: 10px; }")
        top_row.addWidget(icon_lbl)
        top_row.addWidget(title_lbl)
        top_row.addStretch()
        top_row.addWidget(time_lbl)
        rl.addLayout(top_row)

        if n["message"]:
            msg_lbl = QLabel(n["message"])
            msg_lbl.setStyleSheet("QLabel { color: #8898a8; font-size: 11px; }")
            msg_lbl.setWordWrap(True)
            rl.addWidget(msg_lbl)

        return row

    def _clear_notifications(self):
        self._notifications.clear()
        self._unread_count = 0
        self._update_bell_badge()
        self._rebuild_notif_list()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # reposition toasts
        existing = [c for c in self.children() if isinstance(c, QFrame) and c.objectName() == "toast"]
        for i, t in enumerate(existing):
            t.move(self.width() - t.width() - 20, 56 + i * (t.height() + 10))
        # reposition notification panel
        if self._notif_panel and self._notif_panel.isVisible():
            self._reposition_notif_panel()

    def _show_toast(self, title, message, duration_ms=3000, icon="✓", icon_color="#00e676"):
        """แสดง toast notification มุมขวาบน auto-dismiss"""
        # ── record in history ────────────────────────────────────────────
        self._notifications.insert(0, {
            "time": datetime.now().strftime("%H:%M:%S"),
            "title": title,
            "message": message,
            "icon_color": icon_color,
            "icon": icon,
        })
        self._unread_count += 1
        self._update_bell_badge()
        if self._notif_panel and self._notif_panel.isVisible():
            self._rebuild_notif_list()

        existing = [c for c in self.children() if isinstance(c, QFrame) and c.objectName() == "toast"]
        offset_y = 56 + sum(c.height() + 10 for c in existing)

        toast = QFrame(self)
        toast.setObjectName("toast")
        toast.setFixedWidth(300)

        # แถบสีบนสุด (accent bar ตามสี icon)
        accent = QFrame(toast)
        accent.setFixedHeight(4)
        accent.setStyleSheet(f"QFrame {{ background-color: {icon_color}; border: none; border-radius: 0px; }}")

        toast.setStyleSheet("""
            QFrame#toast {
                background-color: #0d1a2e;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
            }
        """)

        outer = QVBoxLayout(toast)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(accent)

        inner = QVBoxLayout()
        inner.setContentsMargins(14, 10, 14, 12)
        inner.setSpacing(6)

        # header: icon badge + title + close
        header = QHBoxLayout()
        header.setSpacing(8)

        badge = QLabel(icon)
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"""
            QLabel {{
                color: {icon_color};
                font-size: 15px;
                font-weight: bold;
                background-color: rgba(255,255,255,0.07);
                border-radius: 14px;
                border: none;
            }}
        """)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"QLabel {{ color: {icon_color}; font-size: 13px; font-weight: bold; border: none; }}")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton { color: rgba(255,255,255,0.35); font-size: 12px; border: none; background: transparent; }
            QPushButton:hover { color: #ffffff; background: rgba(255,255,255,0.1); border-radius: 11px; }
        """)
        close_btn.clicked.connect(toast.deleteLater)

        header.addWidget(badge)
        header.addWidget(title_lbl)
        header.addStretch()
        header.addWidget(close_btn)

        # divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("QFrame { background-color: rgba(255,255,255,0.08); border: none; }")

        # message
        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("QLabel { color: #b0c8e8; font-size: 12px; border: none; }")
        msg_lbl.setWordWrap(True)

        inner.addLayout(header)
        inner.addWidget(div)
        inner.addWidget(msg_lbl)
        outer.addLayout(inner)

        toast.adjustSize()
        toast.move(self.width() - toast.width() - 20, offset_y)
        toast.show()
        toast.raise_()

        QTimer.singleShot(duration_ms, toast.deleteLater)

    def validate_fields(self, kind):
        # if kind == "num_alpides":
        msg = {
            "num_alpides": ["number of ALPIDEs", list(range(1, 7))],
            "num_events": ["number of events", list(range(1, 100_000))],
            "strobe": ["STROBE value", list(range(100, 801))],
            "ithr": ["I theshold", list(range(30, 121))],
            "energy": ["proton energy", list(range(70, 241))],
            "MU": ["MU", list(range(1, 100000))],
            "current": ["current", list(range(4, 300))],
            "Exposure time (ms)": ["exposure time", list(range(1, 100_000))],
            "Beam delay (ms)": ["beam dalay", list(range(0, 256))],
            "Loops": ["number of loops", list(range(1, 50))],
            "Trigger Freq. (Hz)": ["trigger frequency", list(range(1, 99001))],
            "X step (mm)": ["X step length", [-float(self._window.orig_loc[0]), 150 - float(self._window.orig_loc[0])]],
            "Y step (mm)": ["Y step length", [-float(self._window.orig_loc[1]), 40 - float(self._window.orig_loc[1])]],
            "R step (degree)": ["angle step", list(range(0, 360))]
        }
        try:
            if kind not in ["X step (mm)", "Y step (mm)"]:
                value = int(self._line_edits[kind].text())
                if value not in msg[kind][1]:
                    raise ValueError
            else:
                value = float(self._line_edits[kind].text())
                if value < msg[kind][1][0] or value > msg[kind][1][1]:
                    raise ValueError
        except ValueError:
            valiadated_popup(msg[kind][0], msg[kind][1]).exec_()
            self._line_edits[kind].setStyleSheet("""
                QLineEdit{
                    border: 4px solid rgb(255, 0, 0);
                    font-size: 20px;
                }
                                                            """)
            self._line_edits[kind].setText("")
            self._line_edits[kind].setFocus()
        else:
            self._line_edits[kind].setStyleSheet("""
                QLineEdit{
                    border: 1px solid rgb(0, 0, 255);
                    font-size: 20px;
                }
                                                            """)

def valiadated_popup(msg, allowed_values):
    fail_dialog = QMessageBox()
    fail_dialog.setIcon(QMessageBox.Icon.Critical)
    fail_dialog.setText("Invalid {} input.".format(msg))
    fail_dialog.setWindowTitle("Input error")
    fail_dialog.setDetailedText("[{}, {}]".format(allowed_values[0], allowed_values[-1]))
    fail_dialog.setStandardButtons(QMessageBox.Ok) 
    return fail_dialog