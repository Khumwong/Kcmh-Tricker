# modules/ui/run.py
from PyQt5.QtWidgets import (
    QWidget, QPushButton, QLineEdit, QApplication, QMainWindow,
    QVBoxLayout, QHBoxLayout, QFrame, QSpacerItem, QSizePolicy,
    QMessageBox, QFileDialog, QCheckBox, QInputDialog,
    QLabel, QAction, qApp, QDialog, QGridLayout, QPlainTextEdit, QProgressBar, QToolButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTabWidget, QTextEdit
    )
from PyQt5.QtCore import Qt, QSize, QMetaObject, Q_ARG, QTimer
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtGui import QIcon, QColor
import csv
from modules import eudaq
from modules.ui.rootwidget import RootWidget
from modules.ui.run_progress import RunProgress
from modules.serial_connect import get_port
import serial
import modules.zaber.connect as zaber_connect
import modules.zaber.motion as motion
import modules.fpga.connect as fpga_connect
import json
import os
from os import path
import subprocess
import modules.alpide as alpide
import time
import threading
import psutil
from datetime import datetime


import modules.sound as _sound

_SOUND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sound")

from modules.ui.terminal import _format_its3_log
from modules.ui.zaber_dialog import ZaberMoveDialog
from modules.ui.terminal import EmbeddedTerminal, AppLogWidget
from modules.ui.qa_dialog import _QACompleteDialog
from modules.run_config import RunConfig
from modules.ui.notification_panel import NotificationPanel
from modules.rsync_manager import RsyncManager
from modules.ui.plan_manager import PlanManager
from modules.ui.phantom_panel import PhantomPanel
from modules.beam_controller import BeamController, RESET_BYTE, ENABLE_BYTE, DISABLE_BYTE


class RunWidget(QWidget):
    def __init__(self, window):
        super(RunWidget, self).__init__()
        self._ser = None
        self._window = window
        self._run_type = 0
        self._pid = None
        self._run_active = False
        self._phantom_panel = PhantomPanel(parent=self)
        self._phantom_panel.stopped.connect(self._on_phantom_stopped_slot)
        self._active_move_dlg = None
        self._w = None
        self._opened_file = None
        self._first_file = None
        self._run_stats_start = None
        self._qa_launch_time = None
        self._zaber_max_speeds = None
        self._gating_log = []
        self._run_start_epoch = None
        self._run_stop_epoch = None
        self._checks = [0, 0]
        self._beam_ctrl = BeamController(parent=self)
        self._beam_ctrl._auto_kill_timer.timeout.connect(self._tick_auto_kill)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._tick_blink)
        self._blink_state = False
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
        self._pill_active_style = """
            QPushButton { background: #ffffff; color: #1e3a5f; font-size: 12px; font-weight: bold;
                          border: none; border-radius: 6px; padding: 4px 14px; }
        """
        self._pill_inactive_style = """
            QPushButton { background: transparent; color: rgba(255,255,255,0.6); font-size: 12px; font-weight: bold;
                          border: none; border-radius: 6px; padding: 4px 14px; }
            QPushButton:hover { color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.08); }
        """
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
                            "fpga": QPushButton(" FPGA"),
                            "camera": QPushButton(" Camera")}
        self._connection["alpide"].clicked.connect(lambda x: self.check_connection("alpide"))
        self._connection["fpga"].clicked.connect(lambda x: self.check_connection("fpga"))
        self._connection["zaber"].clicked.connect(lambda x: self.check_connection("zaber"))
        self._connection["camera"].clicked.connect(lambda x: self._open_video_window())
        for v in self._connection.values():
            v.setCursor(Qt.CursorShape.PointingHandCursor)
            v.setIconSize(QSize(20, 20))
            v.setFixedWidth(150)
        self.check_connections()

        # Plan state — data model delegated to PlanManager
        self._plan_mgr = PlanManager(parent=self)
        self._plan_mgr.plan_changed.connect(self._on_plan_changed_slot)

        self._config = RunConfig(path.join(os.getcwd(), 'config.json'))
        default_outpath = self._config.get('outpath', path.join(os.getcwd(), 'output'))
        default_rsync_address = self._config.get('rsync_address', '')
        default_rsync_path = self._config.get('rsync_path', '')
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
        self._rsync_connected = False
        self._rsync_mgr = RsyncManager(parent=self)
        self._rsync_mgr.status_changed.connect(self._on_rsync_status_slot)
        self._rsync_mgr.done.connect(self._on_rsync_done_slot)
        self._rsync_mgr.failed.connect(self._on_rsync_failed_slot)
        self._rsync_mgr.progress.connect(self._rsync_progress_slot)
        self._rsync_mgr.proc_created.connect(self._on_rsync_proc_created_slot)
        self._current_file = None
        self._launch_eudaq_default = QPushButton("Launch default")
        self._launch_eudaq_default.setEnabled(False)
        self._kill_beam_btn = QPushButton("Kill beam")
        self._kill_beam_btn.setCheckable(True)
        self._kill_beam_btn.setEnabled(False)
        self._kill_beam_btn.clicked.connect(self.kill_beam_action)
        self._auto_kill_checkbox = QCheckBox("Auto kill beam (5s)")
        self._auto_kill_checkbox.setChecked(False)
        self._auto_kill_checkbox.setStyleSheet("""
            QCheckBox { font-size: 13px; color: #455a64; }
            QCheckBox::indicator { width: 16px; height: 16px; }
        """)
        self._gate_checkbox = QCheckBox()
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
        self._auto_kill_checkbox.stateChanged.connect(
            lambda s: self.log(f"Auto kill beam {'ON' if s else 'OFF'}")
        )
        self._launch_eudaq_default.clicked.connect(self.launch_eudaq)
        self._kill_beam_btn.setFixedHeight(40)
        self._launch_eudaq_default.setFixedHeight(40)
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
                background-color: #546e7a;
                color: #cfd8dc;
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
            "Beam on delay (ms)": QLineEdit(),
            "Beam off delay (ms)": QLineEdit(),
            "Loops": QLineEdit(),
            "Trigger Freq. (Hz)": QLineEdit(),
            "X step (mm)": QLineEdit(),
            "Y step (mm)": QLineEdit(),
            "R step (degree)": QLineEdit()
        }
                         
        _field_defaults = {
            "num_alpides": "6", "num_events": "30000", "strobe": "100",
            "ithr": "60", "energy": "200", "MU": "1000", "current": "10",
            "Exposure time (ms)": "1000", "Beam delay (ms)": "200",
            "Beam on delay (ms)": "200", "Beam off delay (ms)": "200", "Loops": "1",
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
            "Beam delay (ms)": ("FPGA trigger delay byte (alpide_delay). Hard limit 0 - 255 "
                                "(one byte — raising it needs FPGA firmware). Does NOT change "
                                "the acquisition window; use Beam on delay for that."),
            "Beam on delay (ms)": ("Gate opens this long BEFORE the exposure so the trigger is "
                                   "already running when the beam arrives (KCMH turn-on lag "
                                   "~300 ms). GUI window timing only, no FPGA limit: 0 - 100000"),
            "Beam off delay (ms)": ("Keep the trigger running this long AFTER exposure ends, "
                                    "before closing the gate and moving the phantom — lets ALPIDE "
                                    "confirm the beam is gone. GUI-side window only: 0 - 100000"),
            "Loops": "The loop of radiation: must be less than exposure time",
            "Trigger Freq. (Hz)": "The trigger frequency: 1 - 95000",
            "X step (mm)": "Stage X step per loop (mm) — max 150 mm",
            "Y step (mm)": "Stage Y step per loop (mm) — max 40 mm",
            "R step (degree)": "Stage R step per loop (°) — max 360°",
        }
        # โหลดค่าล่าสุดจาก config ถ้ามี
        _saved_fields = self._config.get('fields', {})
        _saved_qa = self._config.get('qa_pos', {})
        # Speed fields are one set of widgets shared by QA (sweep speed toward
        # Target) and Treatment (per-loop step speed), but the two persist
        # separately — _set_qa_mode() swaps the widget contents on mode change so
        # a QA sweep speed never leaks into a Treatment step and vice versa.
        _saved_trt_speed = self._config.get('trt_speed', {})
        self._speed_store = {
            'qa':  [_saved_qa.get('vel_x', '0'),          _saved_qa.get('vel_y', '0'),          _saved_qa.get('vel_r', '0')],
            'trt': [_saved_trt_speed.get('vel_x', '2.5'), _saved_trt_speed.get('vel_y', '2.5'), _saved_trt_speed.get('vel_r', '6')],
        }
        for k, v in self._line_edits.items():
            v.setText(_saved_fields.get(k, _field_defaults.get(k, "")))
            if _field_tooltips.get(k):
                v.setToolTip(_field_tooltips[k])
        self._saved_qa_config = _saved_qa  # apply after grid fields are created
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
        self._top_widget = QFrame()
        self._bottom_widget = QFrame()

        # ── Notification history ─────────────────────────────────────────
        self._notif = NotificationPanel(parent_widget=self)
        self.init_ui()
        # Speed fields serve both modes (QA sweep speed / Treatment step speed) —
        # _set_qa_mode() keeps them enabled and refreshes their tooltip per mode.
        for _i, edit in enumerate((self._vel_x_edit, self._vel_y_edit, self._vel_r_edit)):
            edit.setEnabled(True)
            edit.editingFinished.connect(lambda i=_i: self._validate_speed_field(i))
            edit.editingFinished.connect(self._save_fields)
        for edit in (self._qa_pos_x_edit, self._qa_pos_y_edit, self._qa_pos_r_edit):
            edit.setEnabled(True)
            edit.editingFinished.connect(self._save_fields)
        self.set_zaber_max_speeds(None)   # paint the default/max label
        # poll device status ทุก 2 วินาที
        self._firmware_timer = QTimer(self)
        self._firmware_timer.setInterval(2000)
        self._firmware_timer.timeout.connect(self._update_firmware_label)
        self._firmware_timer.start()
        self._pos_poll_timer = QTimer(self)
        self._pos_poll_timer.setInterval(400)
        self._pos_poll_timer.timeout.connect(self._poll_position)
        self._set_qa_mode(False)

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

        # Treatment / QA pill — อันแรกก่อน ALPIDE
        self._mode_treatment_btn = QPushButton("Treatment")
        self._mode_qa_btn = QPushButton("QA")
        self._mode_treatment_btn.setStyleSheet(self._pill_active_style)
        self._mode_qa_btn.setStyleSheet(self._pill_inactive_style)
        self._mode_treatment_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_qa_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_treatment_btn.clicked.connect(lambda: self._set_qa_mode(False))
        self._mode_qa_btn.clicked.connect(lambda: self._set_qa_mode(True))
        _mode_pill = QFrame()
        _mode_pill.setFixedHeight(38)
        _mode_pill.setStyleSheet("""
            QFrame { background: rgba(255,255,255,0.12); border-radius: 8px;
                     border: 1px solid rgba(255,255,255,0.22); }
        """)
        _pill_layout = QHBoxLayout(_mode_pill)
        _pill_layout.setContentsMargins(3, 3, 3, 3)
        _pill_layout.setSpacing(2)
        _pill_layout.addWidget(self._mode_treatment_btn)
        _pill_layout.addWidget(self._mode_qa_btn)
        header_layout.addWidget(_mode_pill)

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
        self._notif._bell_btn.setParent(bell_wrap)
        self._notif._bell_btn.setGeometry(0, 1, 36, 36)
        self._notif._bell_badge.setParent(bell_wrap)
        self._notif._bell_badge.setGeometry(24, 0, 16, 16)
        self._notif._bell_badge.raise_()
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
        ph_card_layout.addWidget(make_section_header("Zaber"))

        ph_inner = QWidget()
        ph_inner_layout = QVBoxLayout(ph_inner)
        ph_inner_layout.setContentsMargins(8, 4, 8, 4)
        ph_inner_layout.setSpacing(2)

        # hidden compat labels — run_progress reads .text()
        self._ph_x_label = QLabel(self._window.orig_loc[0])
        self._ph_y_label = QLabel(self._window.orig_loc[1])
        self._ph_r_label = QLabel(self._window.orig_loc[2])
        for lbl in [self._ph_x_label, self._ph_y_label, self._ph_r_label]:
            lbl.setVisible(False)
            lbl.setParent(ph_inner)  # parent but not in layout — hidden widgets in layout still reserve space

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
        self._ph_x_edit_ctrl.setToolTip("Go to X position (mm) — max 150 mm")
        self._ph_y_edit_ctrl.setToolTip("Go to Y position (mm) — max 40 mm")
        self._ph_r_edit_ctrl.setToolTip("Go to R position (°) — max 360°")
        self._ph_x_edit_ctrl.textChanged.connect(lambda: self._ph_change_line_edit(0))
        self._ph_y_edit_ctrl.textChanged.connect(lambda: self._ph_change_line_edit(1))
        self._ph_r_edit_ctrl.textChanged.connect(lambda: self._ph_change_line_edit(2))

        _axis_lbl_style = "QLabel { font-size: 12px; font-weight: bold; color: #1e2d3d; border: none; background: transparent; min-width: 14px; }"
        _unit_lbl_style = "QLabel { font-size: 11px; color: #4a6078; border: none; background: transparent; }"
        _section_lbl_style = "QLabel { font-size: 11px; font-weight: bold; color: #4a6078; border: none; background: transparent; text-transform: uppercase; letter-spacing: 1px; }"
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
        ph_grid.setSpacing(4)
        ph_grid.setColumnStretch(1, 1)  # disp stretch
        ph_grid.setColumnStretch(5, 1)  # edit stretch

        # headers row 0  (col layout: 0=axis 1=disp 2=unit | 3=vsep | 4=axis 5=edit 6=unit 7=btn)
        cur_hdr = QLabel("Current"); cur_hdr.setStyleSheet(_section_lbl_style)
        goto_hdr = QLabel("Go to");  goto_hdr.setStyleSheet(_section_lbl_style)
        ph_grid.addWidget(cur_hdr,  0, 0, 1, 3)
        ph_grid.addWidget(goto_hdr, 0, 4, 1, 3)

        # vertical separator spanning all data rows
        vsep = QFrame(); vsep.setFrameShape(QFrame.VLine)
        vsep.setStyleSheet("QFrame { background: #dde5ef; border: none; }")
        ph_grid.addWidget(vsep, 0, 3, 4, 1)

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
            # Current side  (cols 0-2)
            a_cur = QLabel(axis); a_cur.setStyleSheet(_axis_lbl_style); a_cur.setFixedWidth(14)
            u_cur = QLabel(unit); u_cur.setStyleSheet(_unit_lbl_style)
            ph_grid.addWidget(a_cur,    row, 0)
            ph_grid.addWidget(disp_lbl, row, 1)
            ph_grid.addWidget(u_cur,    row, 2)

            # Go to side  (cols 4-6)
            a_go = QLabel(axis); a_go.setStyleSheet(_axis_lbl_style); a_go.setFixedWidth(14)
            u_go = QLabel(unit); u_go.setStyleSheet(_unit_lbl_style)
            ph_grid.addWidget(a_go,  row, 4)
            ph_grid.addWidget(edit,  row, 5)
            ph_grid.addWidget(u_go,  row, 6)

            # Action button column (col 7)
            label, slot = btn_slots[i]
            b = QPushButton(label)
            b.setStyleSheet(_ph_action_style)
            b.setFixedWidth(62)
            b.clicked.connect(slot)
            ph_grid.addWidget(b, row, 7)
            if label == "Apply":
                self._ph_apply_btn = b
                b.setEnabled(False)

        ph_body = QHBoxLayout()
        ph_body.addLayout(ph_grid)

        ph_inner_layout.addLayout(ph_body)

        # ── Step + Velocity grid ──────────────────────────────────────────
        def _make_hdiv():
            d = QFrame(); d.setFixedHeight(1)
            d.setStyleSheet("QFrame { background: #dde5ef; border: none; }")
            return d

        ph_inner_layout.addSpacing(6)
        ph_inner_layout.addWidget(_make_hdiv())
        ph_inner_layout.addSpacing(4)

        sv_grid = QGridLayout()
        sv_grid.setSpacing(4)
        sv_grid.setColumnStretch(1, 1)
        sv_grid.setColumnStretch(5, 1)
        sv_grid.setColumnStretch(7, 1)

        step_hdr = QLabel("Step  (per loop)"); step_hdr.setStyleSheet(_section_lbl_style)
        tgt_hdr  = QLabel("Target"); tgt_hdr.setStyleSheet(_section_lbl_style)
        spd_hdr  = QLabel("Speed"); spd_hdr.setStyleSheet(_section_lbl_style)
        sv_grid.addWidget(step_hdr, 0, 0, 1, 3)
        sv_grid.addWidget(tgt_hdr,  0, 5)
        sv_grid.addWidget(spd_hdr,  0, 7)

        sv_vsep = QFrame(); sv_vsep.setFrameShape(QFrame.VLine)
        sv_vsep.setStyleSheet("QFrame { background: #dde5ef; border: none; }")
        sv_grid.addWidget(sv_vsep, 0, 3, 4, 1)
        self._qa_col_widgets = []

        self._qa_pos_x_edit = QLineEdit("")
        self._qa_pos_y_edit = QLineEdit("")
        self._qa_pos_r_edit = QLineEdit("")
        self._qa_pos_x_edit.setToolTip("Target X position (mm) — max 150 mm")
        self._qa_pos_y_edit.setToolTip("Target Y position (mm) — max 40 mm")
        self._qa_pos_r_edit.setToolTip("Target R position (°) — max 360°")
        self._vel_x_edit = QLineEdit("2.5")
        self._vel_y_edit = QLineEdit("2.5")
        self._vel_r_edit = QLineEdit("6.0")
        self._vel_x_edit.setToolTip("Move speed X — 2.5 to 40 mm/s")
        self._vel_y_edit.setToolTip("Move speed Y — 2.5 to 40 mm/s")
        self._vel_r_edit.setToolTip("Move speed R — 6 to 80 °/s")

        sv_axes = [
            ("X", self._line_edits["X step (mm)"],     "mm",
             self._qa_pos_x_edit, "mm", self._vel_x_edit, "mm/s"),
            ("Y", self._line_edits["Y step (mm)"],     "mm",
             self._qa_pos_y_edit, "mm", self._vel_y_edit, "mm/s"),
            ("R", self._line_edits["R step (degree)"], "°",
             self._qa_pos_r_edit, "°",  self._vel_r_edit, "°/s"),
        ]
        for i, (axis, s_edit, s_unit, p_edit, p_unit, v_edit, v_unit) in enumerate(sv_axes):
            row = i + 1
            a_s = QLabel(axis); a_s.setStyleSheet(_axis_lbl_style); a_s.setFixedWidth(14)
            u_s = QLabel(s_unit); u_s.setStyleSheet(_unit_lbl_style)
            s_edit.setFixedHeight(28); s_edit.setMinimumWidth(40)
            s_edit.setAlignment(Qt.AlignmentFlag.AlignCenter); s_edit.setStyleSheet(_edit_style)
            sv_grid.addWidget(a_s,    row, 0)
            sv_grid.addWidget(s_edit, row, 1)
            sv_grid.addWidget(u_s,    row, 2)
            a_q = QLabel(axis); a_q.setStyleSheet(_axis_lbl_style); a_q.setFixedWidth(14)
            u_p = QLabel(p_unit); u_p.setStyleSheet(_unit_lbl_style)
            u_v = QLabel(v_unit); u_v.setStyleSheet(_unit_lbl_style)
            for edit in (p_edit, v_edit):
                edit.setFixedHeight(28)
                edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
                edit.setStyleSheet(_edit_style)
            sv_grid.addWidget(a_q,    row, 4)
            sv_grid.addWidget(p_edit, row, 5)
            sv_grid.addWidget(u_p,    row, 6)
            sv_grid.addWidget(v_edit, row, 7)
            sv_grid.addWidget(u_v,    row, 8)
            pass

        ph_inner_layout.addLayout(sv_grid)

        self._vel_limit_label = QLabel("max speed: — mm/s  — mm/s  — °/s")
        self._vel_limit_label.setStyleSheet(
            "QLabel { font-size: 10px; color: #4a6078; border: none; }")
        ph_inner_layout.addWidget(self._vel_limit_label)

        # apply saved QA target positions now that fields exist (speed fields are
        # filled by _set_qa_mode from self._speed_store per active mode)
        for edit, key in [(self._qa_pos_x_edit, 'qa_pos_x'),
                          (self._qa_pos_y_edit, 'qa_pos_y'),
                          (self._qa_pos_r_edit, 'qa_pos_r')]:
            if self._saved_qa_config.get(key, "") != "":
                edit.setText(self._saved_qa_config[key])
        ph_inner_layout.addSpacing(2)

        ph_card_layout.addWidget(ph_inner)

        self._plan_card = self._build_plan_section()

        # Terminal + Activity log tabs
        self._terminal_widget = EmbeddedTerminal(self)
        self._terminal_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._app_log_widget = AppLogWidget(self)
        self._app_log_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._terminal_tabs = QTabWidget(self)
        self._terminal_tabs.setStyleSheet("""
            QTabWidget::pane {
                background-color: #0d1a2e;
                border: 1px solid #2a3f58;
                border-radius: 0px 6px 6px 6px;
            }
            QTabBar::tab {
                background-color: #1a2e44;
                color: #8aaac8;
                border: 1px solid #2a3f58;
                border-bottom: none;
                padding: 4px 14px;
                font-size: 10pt;
                font-family: monospace;
            }
            QTabBar::tab:selected {
                background-color: #0d1a2e;
                color: #c8d8e8;
            }
            QTabBar::tab:hover:!selected {
                background-color: #243650;
            }
        """)
        self._terminal_tabs.addTab(self._terminal_widget, "ITS3")
        self._terminal_tabs.addTab(self._app_log_widget, "Activity")
        self._terminal_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self._terminal_tabs, 1)

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

        mid_row_widget = QWidget()
        mid_row_widget.setMaximumHeight(290)
        mid_row_layout = QHBoxLayout(mid_row_widget)
        mid_row_layout.setContentsMargins(0, 0, 0, 0)
        mid_row_layout.setSpacing(10)
        mid_row_layout.addWidget(self._phantom_card, 4, Qt.AlignTop)
        mid_row_layout.addWidget(self._plan_card, 6)
        right_layout.addWidget(mid_row_widget)

        # Controller card
        ctrl_card = QFrame()
        ctrl_card.setStyleSheet(CARD_STYLE)
        ctrl_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        ctrl_card_layout = QVBoxLayout(ctrl_card)
        ctrl_card_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_card_layout.setSpacing(0)

        ctrl_card_layout.addWidget(make_section_header("Beam"))

        ctrl_grid = QGridLayout()
        ctrl_grid.setSpacing(8)
        ctrl_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        ctrl_fields = [
            ("Exposure time (ms)",  "Exposure time (ms)"),
            ("Beam delay (ms)",     "Beam delay (ms)"),
            ("Beam on delay (ms)",  "Beam on delay (ms)"),
            ("Beam off delay (ms)", "Beam off delay (ms)"),
            ("Loops",               "Loops"),
            ("Energy (MeV)",        "energy"),
            ("MU",                  "MU"),
            ("Current (nA)",        "current"),
        ]
        for idx, (display, key) in enumerate(ctrl_fields):
            row, col = divmod(idx, 4)
            ctrl_grid.addWidget(make_field_cell(display, self._line_edits[key]), row, col)

        # Enable container — placed in footer between Launch default and Kill beam
        cb_container = QFrame()
        cb_container.setStyleSheet(INNER_CELL_STYLE)
        cb_inner = QVBoxLayout(cb_container)
        cb_inner.setContentsMargins(8, 6, 8, 6)
        cb_inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb_inner.addWidget(self._enable_checkbox)
        self._enable_container = cb_container

        ctrl_inner = QWidget()
        ctrl_inner_layout = QVBoxLayout(ctrl_inner)
        ctrl_inner_layout.setContentsMargins(10, 8, 10, 8)
        ctrl_inner_layout.addLayout(ctrl_grid)
        ctrl_card_layout.addWidget(ctrl_inner)
        right_layout.addWidget(ctrl_card, 1)
        self._beam_ctrl_inner = ctrl_inner
        self._beam_ctrl_card = ctrl_card

        # EUDAQ card
        eudaq_card = QFrame()
        eudaq_card.setStyleSheet(CARD_STYLE)
        eudaq_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        eudaq_card_layout = QVBoxLayout(eudaq_card)
        eudaq_card_layout.setContentsMargins(0, 0, 0, 0)
        eudaq_card_layout.setSpacing(0)

        eudaq_card_layout.addWidget(make_section_header("Sensor"))

        eudaq_grid = QGridLayout()
        eudaq_grid.setSpacing(8)
        eudaq_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        eudaq_fields = [
            ("# ALPIDEs",          "num_alpides"),
            ("Events",             "num_events"),
            ("STROBE",             "strobe"),
            ("I Threshold",        "ithr"),
            ("Trigger Freq. (Hz)", "Trigger Freq. (Hz)"),
        ]
        for idx, (display, key) in enumerate(eudaq_fields):
            row, col = divmod(idx, 4)
            eudaq_grid.addWidget(make_field_cell(display, self._line_edits[key]), row, col)

        eudaq_inner = QWidget()
        eudaq_inner_layout = QVBoxLayout(eudaq_inner)
        eudaq_inner_layout.setContentsMargins(10, 8, 10, 8)
        eudaq_inner_layout.addLayout(eudaq_grid)
        eudaq_card_layout.addWidget(eudaq_inner)
        right_layout.addWidget(eudaq_card, 1)

        # assemble body — Controller+EUDAQ ซ้าย(6), Output+Phantom+Terminal ขวา(4)
        body_layout.addWidget(right_panel, 6)
        body_layout.addWidget(left_panel, 4)

        # ================================================================
        # FOOTER  —  self._bottom_widget
        # ================================================================
        self._vel_estop_btn = QPushButton("⚠  Stop Rotation")
        self._vel_estop_btn.setFixedHeight(40)
        self._vel_estop_btn.setMinimumWidth(150)
        self._vel_estop_btn.setStyleSheet("""
            QPushButton { font-size: 12px; font-weight: bold; border-radius: 6px;
                padding: 4px 16px; color: #ffffff; border: 2px solid #e53935;
                background: #c62828; }
            QPushButton:hover { background: #b71c1c; }
        """)
        self._vel_estop_btn.setVisible(False)
        self._vel_estop_btn.clicked.connect(self._vel_emergency_stop)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(20, 10, 20, 10)
        footer_layout.setSpacing(24)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._launch_eudaq_default)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._enable_container)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._vel_estop_btn)
        footer_layout.addWidget(self._kill_beam_btn)
        footer_layout.addWidget(self._auto_kill_checkbox)
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
        self._progress_section.setFixedHeight(0)

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
        self._inline_cancel_btn = QPushButton("Cancel")
        self._inline_cancel_btn.setStyleSheet(
            btn_style + "QPushButton { background-color: #e65100; } QPushButton:hover { background-color: #f57c00; }")
        self._inline_cancel_btn.clicked.connect(self._cancel_eudaq)
        self._inline_run_btn = QPushButton("Run")
        self._inline_run_btn.setStyleSheet(
            btn_style + "QPushButton { background-color: #1565C0; } QPushButton:hover { background-color: #1976D2; }")
        self._inline_stop_btn = QPushButton("Stop")
        self._inline_stop_btn.setStyleSheet(
            btn_style + "QPushButton { background-color: #b71c1c; } QPushButton:hover { background-color: #d32f2f; }")
        row.addWidget(self._inline_cancel_btn)
        row.addWidget(self._inline_run_btn)
        row.addWidget(self._inline_stop_btn)

        outer.addLayout(row)

        return section

    def _show_progress_section(self):
        # sync position labels with current phantom position
        self._inline_ph_locs[0].setText("X: " + self._ph_x_label.text() + " mm")
        self._inline_ph_locs[1].setText("Y: " + self._ph_y_label.text() + " mm")
        self._inline_ph_locs[2].setText("R: " + self._ph_r_label.text() + " deg")
        self._progress_section.setFixedHeight(130)

    def _hide_progress_section(self):
        self._progress_section.setFixedHeight(0)
        self._inline_progress_bar.setValue(0)
        self._inline_progress_bar.setFormat('')
        self._inline_cancel_btn.setEnabled(True)

    def _cancel_eudaq(self):
        self._run_active = False
        self._hide_progress_section()
        if self._pid is not None:
            eudaq.stop(self._pid, pump=QApplication.processEvents)
        self._terminal_widget.clear()  # cancelled before a run — no final frame to keep
        if hasattr(self, '_mu_tracker') and self._mu_tracker:
            self._mu_tracker.stop()
        self._launch_eudaq_default.setEnabled(True)
        self._window.running(False)
        self.log("EUDAQ cancelled")

    # ------------------------------------------------------------------ #
    #  Plan section                                                        #
    # ------------------------------------------------------------------ #

    def _build_plan_section(self):
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background: #ffffff; border: 1px solid #c0cfe0; border-radius: 8px; }
            QLabel { border: none; }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        # ── navy header bar ───────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet("""
            QFrame { background: #1e3a5f; border-radius: 6px 6px 0 0; border: none; }
            QLabel { border: none; }
        """)
        header.setFixedHeight(32)
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(12, 0, 8, 0)
        self._plan_name_label = QLabel("Plan: —")
        self._plan_name_label.setStyleSheet(
            "QLabel { font-weight: bold; font-size: 12px; color: #fff; }"
        )
        self._plan_progress_label = QLabel("")
        self._plan_progress_label.setStyleSheet(
            "QLabel { font-size: 11px; color: rgba(255,255,255,0.65); margin-left: 8px; }"
        )
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(22, 22)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton { font-size: 11px; background: rgba(255,255,255,0.15);
                border: none; border-radius: 4px; color: #fff; }
            QPushButton:hover { background: rgba(255,255,255,0.3); }
        """)
        btn_close.clicked.connect(self.close_plan)
        h_row.addWidget(self._plan_name_label)
        h_row.addWidget(self._plan_progress_label)
        h_row.addStretch()
        h_row.addWidget(btn_close)
        layout.addWidget(header)

        # ── run table ─────────────────────────────────────────────────
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 6, 8, 0)
        inner_layout.setSpacing(6)

        # ── horizontal split: table left | detail right ───────────────
        body_row = QHBoxLayout()
        body_row.setSpacing(8)

        # left — run list
        self._plan_table = QTableWidget(0, 4)
        self._plan_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._plan_table.setFixedHeight(190)
        self._plan_table.setHorizontalHeaderLabels(["Run", "Attempt", "Status", "OK"])
        _hdr = self._plan_table.horizontalHeader()
        _hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        _hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        _hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        _hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        _hdr.setStyleSheet(
            "QHeaderView::section { background: #2a4a6f; color: rgba(255,255,255,0.7);"
            " font-size: 10px; padding: 2px; border: none; }"
        )
        self._plan_table.model().setHeaderData(1, Qt.Horizontal,
            "How many times 'Load Run →' was pressed for this run", Qt.ToolTipRole)
        self._plan_table.model().setHeaderData(2, Qt.Horizontal,
            "Auto status: ○ pending  ► current  ✓ done", Qt.ToolTipRole)
        self._plan_table.model().setHeaderData(3, Qt.Horizontal,
            "Manually tick when you've verified this run is correct (un-tick to redo)", Qt.ToolTipRole)
        self._plan_table.verticalHeader().setVisible(False)
        self._plan_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._plan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._plan_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._plan_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._plan_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._plan_table.setAlternatingRowColors(True)
        self._plan_table.setStyleSheet("""
            QTableWidget { font-size: 12px; gridline-color: #dde5ef;
                background: #fff; border: 1px solid #c0cfe0; border-radius: 5px; }
            QTableWidget::item:selected { background: #bbdefb; color: #1e2d3d; }
            QScrollBar:vertical { width: 10px; background: #eef2f7; border-radius: 5px; }
            QScrollBar::handle:vertical { background: #8aaac8; border-radius: 4px; min-height: 24px; }
            QScrollBar::handle:vertical:hover { background: #5a82a0; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        self._plan_table.clicked.connect(self._on_plan_row_clicked)
        self._plan_table.itemChanged.connect(self._on_plan_item_changed)
        body_row.addWidget(self._plan_table, 2)

        # right — detail card
        self._plan_detail_label = QLabel("─── select a run ───")
        self._plan_detail_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._plan_detail_label.setWordWrap(True)
        self._plan_detail_label.setStyleSheet("""
            QLabel {
                font-size: 13px; font-family: monospace; color: #6a8098;
                background: #f4f7fb; border: 1px solid #c0cfe0;
                border-radius: 5px; padding: 6px 8px;
            }
        """)
        body_row.addWidget(self._plan_detail_label, 3)

        inner_layout.addLayout(body_row)

        # ── action row ────────────────────────────────────────────────
        action = QHBoxLayout()
        action.setSpacing(8)
        self._load_run_btn = QPushButton("Load Run →")
        self._load_run_btn.setFixedHeight(28)
        self._load_run_btn.setEnabled(False)
        self._load_run_btn.setCursor(Qt.PointingHandCursor)
        self._load_run_btn.setStyleSheet("""
            QPushButton { font-size: 12px; font-weight: bold; background: #1565C0;
                color: #fff; border: none; border-radius: 5px; padding: 3px 14px; }
            QPushButton:hover { background: #1976D2; }
            QPushButton:disabled { background: #bcc8d8; color: #8898a8; }
        """)
        self._load_run_btn.clicked.connect(self._load_selected_run)
        self._plan_info_label = QLabel("")
        self._plan_info_label.setStyleSheet(
            "QLabel { font-size: 10px; color: #4a6078; font-family: monospace; }"
        )
        action.addWidget(self._load_run_btn)
        action.addWidget(self._plan_info_label, 1)
        inner_layout.addLayout(action)

        self._plan_move_bar = QProgressBar()
        self._plan_move_bar.setRange(0, 0)  # indeterminate
        self._plan_move_bar.setFixedHeight(4)
        self._plan_move_bar.setTextVisible(False)
        self._plan_move_bar.setVisible(False)
        self._plan_move_bar.setStyleSheet("""
            QProgressBar { background: #dde5ef; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #1565C0; border-radius: 2px; }
        """)
        inner_layout.addWidget(self._plan_move_bar)

        layout.addWidget(inner)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return card

    def _populate_plan_table(self):
        self._plan_table.blockSignals(True)
        self._plan_table.setRowCount(0)
        STATUS_ICON  = {"pending": "○", "current": "►", "done": "✓"}
        STATUS_COLOR = {"pending": "#4a6078", "current": "#1565C0", "done": "#2e7d32"}
        for i, row_data in enumerate(self._plan_mgr.data):
            r = self._plan_table.rowCount()
            self._plan_table.insertRow(r)
            status = self._plan_mgr.status[i]

            # col 0 — run label
            label = row_data.get("label", "")
            run_text = row_data.get("run", str(i + 1))
            if label:
                run_text = f"{run_text}  {label}"
            run_item = QTableWidgetItem(run_text)
            run_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            if status == "done":
                run_item.setForeground(QColor("#b0bec5"))
            elif status == "current":
                run_item.setForeground(QColor("#1565C0"))
            self._plan_table.setItem(r, 0, run_item)

            # col 1 — attempt count
            count = self._plan_mgr.run_counts[i] if i < len(self._plan_mgr.run_counts) else 0
            count_item = QTableWidgetItem(f"×{count}" if count > 0 else "")
            count_item.setTextAlignment(Qt.AlignCenter)
            count_item.setForeground(QColor("#7a9ab0"))
            self._plan_table.setItem(r, 1, count_item)

            # col 2 — status icon
            st_item = QTableWidgetItem(STATUS_ICON.get(status, "○"))
            st_item.setTextAlignment(Qt.AlignCenter)
            st_item.setForeground(QColor(STATUS_COLOR.get(status, "#4a6078")))
            self._plan_table.setItem(r, 2, st_item)

            # col 3 — OK checkbox (manual user verification)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            done_val = self._plan_mgr.run_done[i] if i < len(self._plan_mgr.run_done) else False
            chk_item.setCheckState(Qt.Checked if done_val else Qt.Unchecked)
            self._plan_table.setItem(r, 3, chk_item)

        self._plan_table.resizeRowsToContents()
        self._plan_table.blockSignals(False)

    @pyqtSlot()
    def _on_plan_changed_slot(self):
        self._populate_plan_table()

    def _on_plan_item_changed(self, item):
        if item.column() == 3 and 0 <= item.row() < len(self._plan_mgr.run_done):
            self._plan_mgr.run_done[item.row()] = (item.checkState() == Qt.Checked)

    def _on_plan_row_clicked(self, index):
        idx = index.row()
        if idx < 0 or idx >= len(self._plan_mgr.data):
            return
        d = self._plan_mgr.data[idx]
        label = d.get("label", "")
        _mode = d.get("mode", "treatment").strip().lower()
        _is_qa = (_mode == "qa")
        if _is_qa:
            _move_tip  = (f"Target  X:{d.get('qa_pos_x','—')} mm  Y:{d.get('qa_pos_y','—')} mm  R:{d.get('qa_pos_r','—')}°<br>"
                          f"Speed   X:{d.get('vel_x','0')} mm/s  Y:{d.get('vel_y','0')} mm/s  R:{d.get('vel_r','0')} °/s")
            _move_det  = (f"Target    X:{d.get('qa_pos_x','—')} mm  Y:{d.get('qa_pos_y','—')} mm  R:{d.get('qa_pos_r','—')}°\n"
                          f"Speed     X:{d.get('vel_x','0')} mm/s  Y:{d.get('vel_y','0')} mm/s  R:{d.get('vel_r','0')} °/s")
        else:
            _move_tip  = (f"Steps   X:{d.get('X step (mm)','0')} mm  Y:{d.get('Y step (mm)','0')} mm  R:{d.get('R step (degree)','0')}°<br>"
                          f"Ctrl    Exp:{d.get('Exposure time (ms)','?')}ms  Delay:{d.get('Beam delay (ms)','?')}ms  Loops:{d.get('Loops','?')}")
            _move_det  = (f"Steps     X:{d.get('X step (mm)','0')} mm  Y:{d.get('Y step (mm)','0')} mm  R:{d.get('R step (degree)','0')}°\n"
                          f"Ctrl      Exp:{d.get('Exposure time (ms)','?')} ms  Delay:{d.get('Beam delay (ms)','?')} ms  Loops:{d.get('Loops','?')}  Freq:{d.get('Trigger Freq. (Hz)','?')} Hz")
        tooltip = (
            f"<b>Run {idx+1}" + (f" [{label}]" if label else "") + f"  [{_mode.upper()}]</b><br>"
            f"Phantom  X:{d.get('start_x','?')}  Y:{d.get('start_y','?')}  R:{d.get('start_r','?')}<br>"
            + _move_tip + "<br>"
            f"EUDAQ    ALPIDEs:{d.get('num_alpides','?')}  Events:{d.get('num_events','?')}  "
            f"STROBE:{d.get('strobe','?')}  Thr:{d.get('ithr','?')}<br>"
            f"Beam     Energy:{d.get('energy','?')} MeV  MU:{d.get('MU','?')}  Current:{d.get('current','?')} nA"
        )
        for col in range(4):
            item = self._plan_table.item(idx, col)
            if item:
                item.setToolTip(tooltip)
        self._plan_info_label.setText("")
        self._plan_detail_label.setText(
            f"[{_mode.upper()}]\n"
            f"Phantom   X:{d.get('start_x','?')} mm  Y:{d.get('start_y','?')} mm  R:{d.get('start_r','?')}°\n"
            + _move_det + "\n"
            f"EUDAQ     ALPIDEs:{d.get('num_alpides','?')}  Events:{d.get('num_events','?')}  STROBE:{d.get('strobe','?')}  Thr:{d.get('ithr','?')}\n"
            f"Beam      Energy:{d.get('energy','?')} MeV  MU:{d.get('MU','?')}  Current:{d.get('current','?')} nA"
        )
        self._load_run_btn.setText(f"Load Run {idx+1} →")
        self._load_run_btn.setEnabled(True)

    def _load_selected_run(self):
        idx = self._plan_table.currentRow()
        if idx < 0:
            return
        self._load_run(idx)

    def _load_run(self, idx):
        if idx < 0 or idx >= len(self._plan_mgr.data):
            return
        row_data = self._plan_mgr.data[idx]
        _label = row_data.get("label", "") or f"Run {idx+1}"
        self.log(f"Plan: loaded run {idx+1} [{_label}]")

        # apply mode first so field locks are correct
        _mode = row_data.get("mode", "treatment").strip().lower()
        self._set_qa_mode(_mode == "qa")

        # populate all form fields — a blank cell RESETS optional fields to their
        # default so a row never silently inherits the previous row's step/sweep
        _blank_default = {
            "X step (mm)": "0", "Y step (mm)": "0", "R step (degree)": "0",
        }
        for key in self._line_edits:
            if key in row_data and row_data[key] != "":
                self._line_edits[key].setText(row_data[key])
            elif key in _blank_default:
                self._line_edits[key].setText(_blank_default[key])

        # populate QA fields (position + speed) — blank cell resets: pos -> "", speed -> "0"
        for edit, key, _blank in [(self._qa_pos_x_edit, "qa_pos_x", ""),
                                  (self._qa_pos_y_edit, "qa_pos_y", ""),
                                  (self._qa_pos_r_edit, "qa_pos_r", ""),
                                  (self._vel_x_edit,    "vel_x",    "0"),
                                  (self._vel_y_edit,    "vel_y",    "0"),
                                  (self._vel_r_edit,    "vel_r",    "0")]:
            if key in row_data and row_data[key] != "":
                edit.setText(row_data[key])
            else:
                edit.setText(_blank)
        # clamp the speed fields into the active-mode band, then sync the store
        for _i in range(3):
            self._validate_speed_field(_i)
        self._speed_store['qa' if self._window._qa_mode else 'trt'] = [
            self._vel_x_edit.text(), self._vel_y_edit.text(), self._vel_r_edit.text()]

        # set phantom go-to inputs
        sx = row_data.get("start_x", "0")
        sy = row_data.get("start_y", "0")
        sr = row_data.get("start_r", "0")
        self._ph_x_edit_ctrl.setText(sx)
        self._ph_y_edit_ctrl.setText(sy)
        self._ph_r_edit_ctrl.setText(sr)
        self._ph_check_apply()

        # update status via plan_mgr (emits plan_changed → _populate_plan_table)
        self._plan_mgr.step_to(idx)
        self._plan_table.selectRow(idx)

        done = sum(1 for s in self._plan_mgr.status if s == "done")
        self._plan_progress_label.setText(
            f"Run {idx + 1} / {len(self._plan_mgr.data)}  ({done} done)"
        )
        self._plan_info_label.setText(f"Moving → X={sx} Y={sy} R={sr}...")
        self._load_run_btn.setEnabled(False)
        self._phantom_panel._phantom_moving = True

        dlg = ZaberMoveDialog(self, f"X:{sx} mm  Y:{sy} mm  R:{sr}°")
        self._active_move_dlg = dlg

        def _move():
            conn = None
            try:
                conn = zaber_connect.connect(get_port("zaber"))
                dlg.set_conn(conn)
                motion.apply_move(conn, (float(sx), float(sy), float(sr)),
                                  self._current_move_speeds())
                loc = motion.get_current_locations(conn)
                dlg._sig_move_done.emit(float(loc[0]), float(loc[1]), float(loc[2]))
            except Exception as exc:
                dlg._sig_move_error.emit(str(exc))
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

        threading.Thread(target=_move, daemon=True).start()
        result = dlg.exec_()
        self._phantom_panel._phantom_moving = False
        QTimer.singleShot(0, lambda: setattr(self, '_active_move_dlg', None))

        if result == QDialog.Accepted:
            loc = dlg.result_loc
            xs, ys, rs = f"{loc[0]:.2f}", f"{loc[1]:.2f}", f"{loc[2]:.2f}"
            self.set_ph_loc_full([xs, ys, rs])
            self._plan_info_label.setText(f"Ready  X={xs} Y={ys} R={rs}")
            self._load_run_btn.setEnabled(True)
            self._show_toast("Phantom moved", f"X={xs}  Y={ys}  R={rs}", icon="✓", icon_color="#00e676")
        elif result == ZaberMoveDialog.STOPPED:
            self._plan_info_label.setText("Move stopped by emergency stop")
            self._load_run_btn.setEnabled(True)
            self._show_toast("Move stopped", "Emergency stop activated", icon="⚠", icon_color="#ff9800")
        else:
            self._plan_info_label.setText(f"Phantom move failed: {dlg.result_error}")
            self._load_run_btn.setEnabled(True)
            self._show_toast("Phantom error", dlg.result_error or "Unknown error", icon="✕", icon_color="#ef5350")

    def _load_plan_from_file(self, fname):
        self._plan_mgr.load_file_as_dicts(fname)
        rows = self._plan_mgr.data
        if not rows:
            QMessageBox.warning(self, "Empty Plan",
                                "The CSV file has no runs.")
            return
        self._plan_name_label.setText(f"Plan: {os.path.basename(fname)}")
        self._plan_progress_label.setText(f"0 / {len(rows)} runs")
        self._load_run_btn.setEnabled(False)
        self._load_run_btn.setText("Load Run →")
        self._plan_info_label.setText("Select a run")
        self._plan_card.setVisible(True)

    def load_plan(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        fname, _ = QFileDialog.getOpenFileName(
            self, "Load Plan", "", "CSV Files (*.csv)", options=options
        )
        if fname:
            self._load_plan_from_file(fname)

    def create_plan(self):
        from modules.ui.plan_dialog import CreatePlanDialog
        current = {k: v.text() for k, v in self._line_edits.items()}
        current["start_x"] = self._ph_x_label.text()
        current["start_y"] = self._ph_y_label.text()
        current["start_r"] = self._ph_r_label.text()
        dlg = CreatePlanDialog(current_fields=current, parent=self)
        if dlg.exec_() and dlg.saved_path:
            reply = QMessageBox.question(
                self, "Load Plan", "Load the newly created plan now?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._load_plan_from_file(dlg.saved_path)

    def close_plan(self):
        reply = QMessageBox.question(
            self, "ปิด Plan", "ต้องการปิด plan ใช่ไหม?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self.log("Plan closed")
        self._plan_mgr.close()
        self._plan_card.setVisible(False)

    # ------------------------------------------------------------------ #
    #  Phantom control methods                                             #
    # ------------------------------------------------------------------ #
    def _current_move_speeds(self):
        """(vx, vy, vr) from the Speed fields, clamped to [SPEED_FLOOR, SPEED_CEIL]
        per axis. Never 0 / blank / below floor — every move has a real speed."""
        flr, ceil = motion.SPEED_FLOOR, motion.SPEED_CEIL
        out = []
        for i, edit in enumerate((self._vel_x_edit, self._vel_y_edit, self._vel_r_edit)):
            try:
                s = float(edit.text())
            except (ValueError, TypeError):
                s = flr[i]
            out.append(min(max(s, flr[i]), ceil[i]))
        return tuple(out)

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
            motion.apply_step(conn, axis, direction * step, self._current_move_speeds()[axis])
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
            self._ph_x_edit_ctrl.setText("100.0")
            self._ph_y_edit_ctrl.setText("0")
            self._ph_r_edit_ctrl.setText("0")
        self.log(f"Phantom preset → {loc.capitalize()} (X:{self._ph_x_edit_ctrl.text()} Y:{self._ph_y_edit_ctrl.text()} R:{self._ph_r_edit_ctrl.text()})")
        self._ph_check_apply()

    def _ph_apply(self):
        self._ph_apply_btn.setEnabled(False)
        _x, _y, _r = self._ph_x_edit_ctrl.text(), self._ph_y_edit_ctrl.text(), self._ph_r_edit_ctrl.text()
        self.log(f"Phantom move → X:{_x} mm  Y:{_y} mm  R:{_r}°")

        dlg = ZaberMoveDialog(self, f"X:{_x} mm  Y:{_y} mm  R:{_r}°")
        self._active_move_dlg = dlg
        self._phantom_panel._phantom_moving = True

        def _move():
            conn = None
            try:
                conn = zaber_connect.connect(get_port("zaber"))
                dlg.set_conn(conn)
                motion.apply_move(conn, (float(_x), float(_y), float(_r)),
                                  self._current_move_speeds())
                loc = motion.get_current_locations(conn)
                dlg._sig_move_done.emit(float(loc[0]), float(loc[1]), float(loc[2]))
            except Exception as e:
                dlg._sig_move_error.emit(str(e))
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

        threading.Thread(target=_move, daemon=True).start()
        result = dlg.exec_()
        self._phantom_panel._phantom_moving = False
        QTimer.singleShot(0, lambda: setattr(self, '_active_move_dlg', None))

        if result == QDialog.Accepted:
            loc = dlg.result_loc
            self.set_ph_loc_full([f"{l:.2f}" for l in loc])
            self._ph_apply_btn.setEnabled(True)
            self._show_toast("Phantom moved ✓", f"X:{loc[0]:.2f} mm  Y:{loc[1]:.2f} mm  R:{loc[2]:.2f}°")
        elif result == ZaberMoveDialog.STOPPED:
            self._ph_apply_btn.setEnabled(True)
            self._show_toast("Move stopped", "Emergency stop activated", icon="⚠", icon_color="#ff9800")
        else:
            self._ph_apply_btn.setEnabled(True)
            QMessageBox.critical(self, "Connection issue",
                                 f"Fail to connect Zaber.\n{dlg.result_error}")

    def _ph_clear(self):
        loc = self._window.orig_loc
        self._ph_x_edit_ctrl.setText(loc[0])
        self._ph_y_edit_ctrl.setText(loc[1])
        self._ph_r_edit_ctrl.setText(loc[2])

    def _vel_stop(self):
        self._phantom_panel.vel_stop()  # state + hardware; UI handled by _on_phantom_stopped_slot

    def _vel_emergency_stop(self):
        """ใช้ได้ทั้ง manual test และระหว่าง run."""
        if self._run_active:
            self._vel_stop_run()
        else:
            self._phantom_panel.emergency_stop()

    @pyqtSlot()
    def _on_phantom_stopped_slot(self):
        if hasattr(self, '_vel_estop_btn'):
            self._vel_estop_btn.setVisible(False)

    @pyqtSlot()
    def _vel_reset_slot(self):
        if hasattr(self, '_vel_estop_btn'):
            self._vel_estop_btn.setVisible(False)

    def _poll_position(self):
        conn = self._phantom_panel._vel_conn
        if conn is None:
            return
        def _thread():
            try:
                locs = motion.poll_positions(conn)
                self._phantom_panel._pos_poll_result = (f"{locs[0]:.2f}", f"{locs[1]:.2f}", f"{locs[2]:.2f}")
                QMetaObject.invokeMethod(self, "_on_pos_poll_slot", Qt.ConnectionType.QueuedConnection)
            except Exception:
                pass
        threading.Thread(target=_thread, daemon=True).start()

    @pyqtSlot()
    def _on_pos_poll_slot(self):
        r = self._phantom_panel._pos_poll_result
        if r is None:
            return
        self._ph_x_label.setText(r[0])
        self._ph_y_label.setText(r[1])
        self._ph_r_label.setText(r[2])
        if hasattr(self, '_ph_disp_labels'):
            for lbl, val in zip(self._ph_disp_labels, r):
                lbl.setText(val)

    def _vel_start_run(self):
        """Starts Zaber position move — QA mode only."""
        if not self._window._qa_mode:
            return
        px_str = self._qa_pos_x_edit.text().strip()
        py_str = self._qa_pos_y_edit.text().strip()
        pr_str = self._qa_pos_r_edit.text().strip()
        if not px_str and not py_str and not pr_str:
            return
        try:
            sx = float(self._vel_x_edit.text() or 0)
            sy = float(self._vel_y_edit.text() or 0)
            sr = float(self._vel_r_edit.text() or 0)
            px = float(px_str) if px_str and sx > 0 else None
            py = float(py_str) if py_str and sy > 0 else None
            pr = float(pr_str) if pr_str and sr > 0 else None
        except ValueError:
            return
        if not self._window._zaber_connect:
            return

        _MAX_VX, _MAX_VY, _MAX_VR = motion.SPEED_CEIL
        over = []
        if sx > _MAX_VX: over.append(f"X: {sx} mm/s  (max {_MAX_VX} mm/s)")
        if sy > _MAX_VY: over.append(f"Y: {sy} mm/s  (max {_MAX_VY} mm/s)")
        if sr > _MAX_VR: over.append(f"R: {sr} °/s  (max {_MAX_VR} °/s)")
        if over:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Speed limit exceeded")
            msg.setText("Speed exceeds safe limit — cannot run.")
            msg.setDetailedText("\n".join(over))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
            return

        if hasattr(self, '_vel_estop_btn'):
            self._vel_estop_btn.setVisible(True)

        def _thread():
            import time as _t
            import modules.ui.run_progress as _rp
            conn = None
            try:
                conn = zaber_connect.connect(get_port("zaber"))
                self._phantom_panel._vel_conn = conn
                motion.move_to_target(conn, px, py, pr, sx, sy, sr)
                # poll until stage stops (reached target) or emergency stop
                while self._phantom_panel._vel_conn is not None:
                    try:
                        if not any(conn.get_device(d).get_axis(1).is_busy() for d in (1, 2, 3)):
                            break
                    except Exception:
                        break
                    _t.sleep(0.1)
                # stage reached target — stop acquisition
                if self._run_active:
                    _rp.force_stop = True
            except Exception as e:
                print(f"[QA run] move_to_target error: {e}")
                self._phantom_panel._vel_conn = None
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                QMetaObject.invokeMethod(self, "_vel_estop_hide_slot",
                    Qt.ConnectionType.QueuedConnection)

        threading.Thread(target=_thread, daemon=True).start()

    def _vel_stop_run(self):
        """Auto-called at acquisition end (or emergency stop) — stops stage move."""
        self._pos_poll_timer.stop()
        conn = self._phantom_panel._vel_conn
        self._phantom_panel._vel_conn = None
        self._phantom_panel._phantom_moving = False
        if hasattr(self, '_vel_estop_btn'):
            self._vel_estop_btn.setVisible(False)
        if conn is not None:
            def _stop_thread():
                try:
                    motion.stop_all(conn)
                    locs = motion.poll_positions(conn)
                    self._phantom_panel._pos_poll_result = (f"{locs[0]:.2f}", f"{locs[1]:.2f}", f"{locs[2]:.2f}")
                    QMetaObject.invokeMethod(self, "_on_pos_poll_slot",
                        Qt.ConnectionType.QueuedConnection)
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
            threading.Thread(target=_stop_thread, daemon=True).start()

    @pyqtSlot()
    def _vel_estop_hide_slot(self):
        if hasattr(self, '_vel_estop_btn'):
            self._vel_estop_btn.setVisible(False)

    @pyqtSlot(bool)
    def _on_camera_poll_slot(self, cam_ok):
        self._connection["camera"].setIcon(self._connection_icons[1 if cam_ok else 0])
        self._connection["camera"].setStyleSheet(self._connect_styles[1 if cam_ok else 0])

    @pyqtSlot(bool)
    def _on_zaber_poll_slot(self, zaber_ok):
        if zaber_ok != self._window._zaber_connect:
            self._window._zaber_connect = zaber_ok
            icon_idx = 1 if zaber_ok else 0
            self._connection["zaber"].setIcon(self._connection_icons[icon_idx])
            self._connection["zaber"].setStyleSheet(self._connect_styles[icon_idx])

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

    def set_zaber_max_speeds(self, speeds):
        """`speeds` (the live device maxspeed, or None) is kept for reference; the
        Speed fields are bounded by the fixed motion.SPEED_FLOOR / SPEED_CEIL."""
        if speeds:
            self._zaber_max_speeds = speeds
        flr, ceil = motion.SPEED_FLOOR, motion.SPEED_CEIL
        if hasattr(self, '_vel_limit_label'):
            self._vel_limit_label.setText(
                f"default {flr[0]:g} / {flr[1]:g} / {flr[2]:g}   ·   "
                f"max {ceil[0]:g} / {ceil[1]:g} / {ceil[2]:g}   (mm/s, mm/s, °/s)")
        # clamp any out-of-range Speed field into the allowed band
        for i in range(3):
            self._validate_speed_field(i)

    def _validate_speed_field(self, idx):
        """Clamp Speed field `idx` into its band. Treatment: [FLOOR, CEIL] — never
        below the gentle default. QA: [0, CEIL] — 0 still means 'axis does not move'."""
        edit = (self._vel_x_edit, self._vel_y_edit, self._vel_r_edit)[idx]
        ceil = motion.SPEED_CEIL[idx]
        lo = 0.0 if getattr(self._window, '_qa_mode', False) else motion.SPEED_FLOOR[idx]
        try:
            v = float(edit.text())
        except (ValueError, TypeError):
            v = lo
        v = min(max(v, lo), ceil)
        txt = f"{v:g}"
        if edit.text() != txt:
            edit.setText(txt)

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
        _raw_start = os.path.join(self._outpath_label.text(), 'raw')
        if not os.path.isdir(_raw_start):
            _raw_start = self._outpath_label.text()
        fileName, _ = QFileDialog.getOpenFileName(self,"QFileDialog.getOpenFileName()", _raw_start,"RAW Files (*.raw)", options=options)
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
    def _on_rsync_status_slot(self, text, color):
        self._set_rsync_status(text, color)
        if text == "rsync connected":
            self._rsync_connected = True
            self.log(f"rsync connected to {self._rsync_addr_edit.text().strip()}")
            self._config.set('rsync_address', self._rsync_addr_edit.text().strip())
            self._config.set('rsync_path', self._rsync_path_edit.text().strip())
            self._config.save()
        elif text in ("rsync fail", ""):
            self._rsync_connected = False

    @pyqtSlot(str)
    def _on_rsync_failed_slot(self, err):
        self._rsync_connected = False
        self.log(f"rsync connection failed — {err[:120]}")
        self._set_rsync_status("", "")
        if self._rsync_toast:
            self._rsync_toast.hide()
        raw_note = f"\nRaw file saved: {os.path.basename(self._current_file)}" if self._current_file else ""
        self._show_toast("rsync failed", err[:120] + raw_note, icon="✗", icon_color="#ef5350")

    @pyqtSlot(str, str)
    def _on_rsync_done_slot(self, kind, detail):
        if kind == "ok":
            self.log(f"rsync done — {detail}")
            self._show_toast("rsync done ✓", detail)
            if self._rsync_toast:
                self._rsync_toast.set_done(success=True, detail=detail)
                self._rsync_toast = None
        elif kind == "error":
            self.log(f"rsync FAILED — {detail}")
            self._show_toast("rsync failed ✗", detail, icon="✗", icon_color="#ef5350")
            if self._rsync_toast:
                self._rsync_toast.set_done(success=False, detail=detail)
                self._rsync_toast = None
            self._on_rsync_failed_slot(detail)
        elif kind == "monitor_ok":
            self.log(f"ROOT conversion done — {detail}")
            self._show_toast("monitor done ✓", detail)
        elif kind == "monitor_error":
            self.log(f"ROOT conversion FAILED — {detail}")
            self._show_toast("monitor failed ✗", detail, icon="✗", icon_color="#ef5350")

    @pyqtSlot(str, str)
    def _rsync_progress_slot(self, pct, speed):
        if self._rsync_toast:
            self._rsync_toast.update_progress(pct, speed)

    @pyqtSlot(object)
    def _on_rsync_proc_created_slot(self, proc):
        if self._rsync_toast:
            self._rsync_toast.set_proc(proc)

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
        self.log(f"rsync connect → {addr}:{rpath}")
        self._rsync_mgr.connect(addr, rpath, password)

    def chooseOutpath(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        options |= QFileDialog.ShowDirsOnly
        dirName = QFileDialog.getExistingDirectory(self,"QFileDialog.getExistingDirectory()", self._outpath_label.text(), options=options)
        if dirName:
            self.log(f"Output path set → {dirName}")
            self._outpath_label.setText(dirName)
            self._config.set('outpath', dirName)
            self._config.save()
    
    def _update_firmware_label(self):
        _base = "QLabel { font-size: 12px; font-weight: bold; background: transparent; border: none; padding: 3px 10px; font-family: monospace; }"

        # FPGA — ข้ามถ้า beam ใช้ port อยู่ เพราะ check_connection() เปิด/ปิด port ซ้อนทำให้ self._ser ถูก invalidate
        if self._ser is None or not self._ser.is_open:
            try:
                _fpga_port = get_port("fpga")
                fpga_ok = fpga_connect.check_connection(_fpga_port)
            except Exception:
                # get_port threw — hardware not reachable; keep operator-set state
                fpga_ok = self._window._fpga_connect
        else:
            fpga_ok = True
        if fpga_ok != self._window._fpga_connect:
            self._window._fpga_connect = fpga_ok
            icon_idx = 1 if fpga_ok else 0
            self._connection["fpga"].setIcon(self._connection_icons[icon_idx])
            self._connection["fpga"].setStyleSheet(self._connect_styles[icon_idx])

        # Zaber — ตรวจแค่ USB device presence (ไม่เปิด serial port → ไม่ conflict)
        # get_port() สแกน OS device list เท่านั้น ใช้ได้ทั้งตอน connected และ disconnected
        if not self._run_active and not self._phantom_panel._phantom_moving:
            if not getattr(self, '_zaber_checking', False):
                self._zaber_checking = True
                def _do_zaber_check():
                    try:
                        get_port("zaber")
                        ok = True
                    except Exception:
                        ok = False
                    self._zaber_checking = False
                    QMetaObject.invokeMethod(self, '_on_zaber_poll_slot',
                        Qt.ConnectionType.QueuedConnection, Q_ARG(bool, ok))
                threading.Thread(target=_do_zaber_check, daemon=True).start()

        # Camera — background thread เพราะ cv2.VideoCapture(0) บล็อก UI ได้นาน
        if not getattr(self, '_camera_checking', False):
            self._camera_checking = True
            def _do_camera_check():
                ok = self._window.check_camera()
                self._camera_checking = False
                QMetaObject.invokeMethod(self, '_on_camera_poll_slot',
                    Qt.ConnectionType.QueuedConnection, Q_ARG(bool, ok))
            threading.Thread(target=_do_camera_check, daemon=True).start()

        # ALPIDE
        found = alpide.found_daqs()
        if found != self._window._alpide_connect:
            self._window._alpide_connect = found
            icon_idx = 1 if found else 0
            self._connection["alpide"].setIcon(self._connection_icons[icon_idx])
            self._connection["alpide"].setStyleSheet(self._connect_styles[icon_idx])
        if not self._window._alpide_connect:
            self._firmware_label.setText("● No DAQ found")
            self._firmware_label.setStyleSheet(_base + "QLabel { color: #ef5350; }")
        elif not alpide.is_programmed():
            self._firmware_label.setText("⚠ Firmware Not Flashed")
            self._firmware_label.setStyleSheet(_base + "QLabel { color: #ffd740; }")
            if not getattr(self, '_firmware_installing', False):
                self._firmware_installing = True
                import modules.eudaq as eudaq
                eudaq.install_firmware_auto(parent_widget=self._window)
                self._firmware_installing = False
        else:
            self._firmware_label.setText("● Firmware Installed")
            self._firmware_label.setStyleSheet(_base + "QLabel { color: #a5d6a7; }")
    
    def _open_video_window(self):
        from modules.ui.video_window import VideoWindow
        if not hasattr(self, '_video_win') or not self._video_win.isVisible():
            self._video_win = VideoWindow(parent=self._window)
        self._video_win.show()
        self._video_win.raise_()

    def clear_for_new(self):
        for line_edit in self._line_edits.values():
            line_edit.setText("")

    def launch_eudaq(self):
        self.log("Launch EUDAQ — checking connections")
        self.check_connection('alpide')
        self.check_connection('fpga')
        _qa = self._window._qa_mode
        if _qa:
            connections = [self._window._alpide_connect, alpide.is_programmed()]
        else:
            connections = [
                self._window._alpide_connect,
                self.check_zaber_nohome(),
                self._window._zaber_connect,
                alpide.is_programmed(),
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
        
        if not self._window._qa_mode and self._enable_checkbox.checkState() != Qt.Checked:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            fail_dialog.setText("Enable is off!")
            fail_dialog.setWindowTitle("KCMH error")
            fail_dialog.setDetailedText("KCMH need to be enabled.")
            fail_dialog.setStandardButtons(QMessageBox.Ok)
            fail_dialog.exec_()
            self._kill_beam_btn.setChecked(False)
            return
        if self._window._qa_mode:
            self._window.running(True)
            self._qa_launch_time = time.monotonic()
            if self._window._fpga_connect:
                try:
                    if self._ser:
                        try:
                            self._ser.close()
                        except Exception:
                            pass
                    fpga_data = self.get_fpga_data()
                    port = get_port("fpga")
                    self._ser = serial.Serial(
                        port=port, baudrate=fpga_data["baudrate"],
                        parity=fpga_data["parity"], bytesize=fpga_data["bytesize"],
                        stopbits=fpga_data["stopbits"], timeout=1)
                    self._ser.write(RESET_BYTE)
                    self._ser.write(RESET_BYTE)
                    self._ser.write(ENABLE_BYTE)
                    for b in fpga_data["byte_start_list"][1:]:
                        self._ser.write(b)
                except Exception as e:
                    print(f"[QA] FPGA open failed — {e}")

        self._launch_eudaq_default.setEnabled(False)
        self._first_file = self.get_new_outfile()
        self.log("Run started — EUDAQ launching")
        QApplication.beep()
        _le = self._line_edits
        print(f"[LAUNCH] {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        print(f"  mode={'QA' if self._window._qa_mode else 'Treatment'}")
        for _k in ["Exposure time (ms)", "Beam delay (ms)", "Beam on delay (ms)", "Beam off delay (ms)", "Loops", "energy", "MU",
                   "current", "num_alpides", "num_events", "strobe", "ithr"]:
            if _k in _le:
                print(f"  {_k}={_le[_k].text()}")
        if self._window._qa_mode:
            print(f"  qa_pos  X={self._qa_pos_x_edit.text()} Y={self._qa_pos_y_edit.text()} R={self._qa_pos_r_edit.text()}")
            print(f"  qa_spd  X={self._vel_x_edit.text()} Y={self._vel_y_edit.text()} R={self._vel_r_edit.text()}")
            # phantom position at launch = sweep start (set by _load_run's blocking move)
            self._qa_start_pos = (self._ph_x_label.text(), self._ph_y_label.text(),
                                  self._ph_r_label.text())
        else:
            self._qa_start_pos = None
        self._launch_time = time.monotonic()
        self._gating_log = []
        # NOT stamped here — FPGA doesn't gate the beam (\xFE) until Start Acquisition.
        self._run_start_epoch = None
        self._run_stop_epoch = None
        self._pid = eudaq.default_run(self._line_edits, self._outpath_label.text())
        psutil.cpu_percent(interval=None)  # warm-up
        self._run_stats_start = {
            'time':     time.monotonic(),
            'time_abs': datetime.now(),
            'disk':     psutil.disk_io_counters(),
            'net':      psutil.net_io_counters(),
        }
        # Control Room ไม่ reset ตรงนี้ — flow ใหม่คือรอ READY หลัง Launch
        # เริ่ม poll tmux ITS3 output (หลังจากที่ script เริ่มสร้าง session)
        self._terminal_widget.launch("ITS3", delay_ms=2000)
        # สร้าง MU tracker ไว้รอ (เฉพาะ real mode) — จะ .start() ตอนกด Run
        try:
            import modules.sim as _sim_mod
            _is_sim = (_sim_mod.control_room is not None
                       or _sim_mod.main_window is not None)
        except Exception:
            _is_sim = False
        # หยุด tracker เก่า (ถ้ายังค้างอยู่จาก run ก่อน) ก่อนสร้างใหม่
        if hasattr(self, '_mu_tracker') and self._mu_tracker:
            self._mu_tracker.stop()
        self._mu_tracker = None
        if not _is_sim:
            from modules.ui.video_window import MuTracker
            self._mu_tracker = MuTracker(
                output_dir=self._outpath_label.text().strip(),
                ssh_addr=self._rsync_addr_edit.text().strip(),
                ssh_path=self._rsync_path_edit.text().strip(),
                ssh_pass=self._rsync_mgr._password or '',
                log_fn=self.log,
            )
            # เช็คกล้องพร้อมทันที ไม่รอกด Run
            self._mu_tracker.prepare()
            # .start() (เริ่ม camera) จะถูกเรียกใน RunProgress._start_worker()
        # แสดง progress section ใน main window — ไม่ต้องเปิด dialog แยก
        self._run_active = True
        self._show_progress_section()
        self._run_progress_dialog = RunProgress(
            window=self,
            progress_bar=self._inline_progress_bar,
            run_btn=self._inline_run_btn,
            stop_btn=self._inline_stop_btn,
            ph_locs=self._inline_ph_locs,
        )
        
    def stop_run(self):
        self._run_active = False
        self._run_stop_epoch = time.time()
        if self._window._qa_mode:
            # clear so we can detect the fresh end-of-sweep poll from _vel_stop_run
            self._phantom_panel._pos_poll_result = None
        self._vel_stop_run()  # หยุด stage ทันทีก่อนทำ log building / eudaq.stop
        _acq_t = getattr(self, '_acq_start_time', None)
        _acq_elapsed = f"{time.monotonic() - _acq_t:.2f}s" if _acq_t else "?"
        print(f"[RUN END]   {datetime.now().strftime('%H:%M:%S.%f')[:-3]}  (acquisition={_acq_elapsed})")
        self._hide_progress_section()
        self.log("Run stopped")
        if hasattr(self, '_mu_tracker') and self._mu_tracker:
            self._mu_tracker.stop()
            # ไม่ set None ทันที — stop() spawn SSHWorker (อัปโหลดวิดีโอ) เป็น QThread
            # ไว้ใน self._mu_tracker._ssh_worker ถ้า mu_tracker โดน GC ไปก่อน thread จบ
            # จะเสี่ยง "QThread destroyed while running"
        # QA mode: ส่ง disable bytes และ close serial port ทันที (ไม่มี kill beam flow)
        if self._window._qa_mode and self._ser is not None:
            try:
                self._ser.write(DISABLE_BYTE)
            except Exception:
                pass
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
            self.log("QA: FPGA trigger disabled (\\xF2 sent)")
        # re-enable Kill beam ถ้า ser ยังอยู่ (beam อาจยังค้างอยู่หลัง run จบ)
        if self._ser is not None:
            self._kill_beam_btn.setChecked(False)  # reset state ก่อน ป้องกัน spurious trigger
            self._kill_beam_btn.setEnabled(True)
            self._start_auto_kill_sequence()
        if self._pid is not None:
            # pump=processEvents keeps the embedded terminal polling during the
            # stop sequence, so it shows RUNNING → STOPPED → TERMINATED live and
            # freezes itself on the TERMINATED frame; until_done ends the wait as
            # soon as that happens (see EmbeddedTerminal.freeze)
            eudaq.stop(self._pid, pump=QApplication.processEvents,
                       until_done=lambda: self._terminal_widget._frozen)
            if self._window._qa_mode:
                _toast_sub = "Acquisition complete — UI unlocked"
            else:
                _toast_sub = "Auto-kill beam ใน 5 วินาที" if self._auto_kill_checkbox.isChecked() else "รอกด Kill beam"
            self._show_toast("Run complete ✓", _toast_sub)
        self._terminal_widget.freeze()  # fallback if the settled-frame detection missed

        # QA sweep: wait for _vel_stop_run's background poll so the log records the
        # real end-of-sweep position, not the stale start position
        if self._window._qa_mode:
            _deadline = time.monotonic() + 3.0
            while (self._phantom_panel._pos_poll_result is None
                   and time.monotonic() < _deadline):
                QApplication.processEvents()
                time.sleep(0.05)
            if self._phantom_panel._pos_poll_result is not None:
                self._on_pos_poll_slot()

        if self._pid is not None and self.get_new_outfile() != self._first_file:
            self._first_file = self.get_new_outfile()
            self._current_file = self._first_file
            # build program log
            _program_log_content = ""
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
                _t_start = self._run_stats_start['time_abs']
                _t_end   = datetime.now()
                _raw_size_str = ""
                if self._current_file:
                    try:
                        _raw_bytes = os.path.getsize(self._current_file)
                        _raw_size_str = f"  Raw size  : {_raw_bytes/1024/1024:.1f} MiB\n"
                    except OSError:
                        pass
                _le = self._line_edits
                _ctrl_fields = [
                    ("Exposure time (ms)", _le.get("Exposure time (ms)", None)),
                    ("Beam delay (ms)",    _le.get("Beam delay (ms)", None)),
                    ("Beam on delay (ms)",  _le.get("Beam on delay (ms)", None)),
                    ("Beam off delay (ms)", _le.get("Beam off delay (ms)", None)),
                    ("Loops",             _le.get("Loops", None)),
                    ("Trigger Freq. (Hz)",_le.get("Trigger Freq. (Hz)", None)),
                    ("X step (mm)",       _le.get("X step (mm)", None)),
                    ("Y step (mm)",       _le.get("Y step (mm)", None)),
                    ("R step (degree)",   _le.get("R step (degree)", None)),
                ]
                _eudaq_fields = [
                    ("# ALPIDEs",    _le.get("num_alpides", None)),
                    ("Events",       _le.get("num_events", None)),
                    ("STROBE",       _le.get("strobe", None)),
                    ("I Threshold",  _le.get("ithr", None)),
                    ("Energy (MeV)", _le.get("energy", None)),
                    ("MU",           _le.get("MU", None)),
                    ("Current (nA)", _le.get("current", None)),
                ]
                def _fv(w): return w.text() if w is not None else "-"

                _sp = self._current_move_speeds()
                _speed_line = (f"  {'Move speed':<20}: "
                               f"X={_sp[0]:g} mm/s  Y={_sp[1]:g} mm/s  R={_sp[2]:g} °/s\n")

                # QA sweep block — records mode, sweep target/speed, and start->end
                # position so a QA run can be correlated with stage position offline
                _qa_block = ""
                if self._window._qa_mode:
                    _sp = getattr(self, '_qa_start_pos', None) or ("-", "-", "-")
                    _qa_block = (
                        f"\n--- QA Sweep ---\n"
                        f"  Mode      : QA\n"
                        f"  Start     : X={_sp[0]}  Y={_sp[1]}  R={_sp[2]}\n"
                        f"  End       : X={self._ph_x_label.text()}  "
                        f"Y={self._ph_y_label.text()}  R={self._ph_r_label.text()}\n"
                        f"  Target    : X={_fv(self._qa_pos_x_edit)}  "
                        f"Y={_fv(self._qa_pos_y_edit)}  R={_fv(self._qa_pos_r_edit)}\n"
                        f"  Speed     : X={_fv(self._vel_x_edit)} mm/s  "
                        f"Y={_fv(self._vel_y_edit)} mm/s  R={_fv(self._vel_r_edit)} deg/s\n"
                    )

                _program_log_content = (
                    f"=== Run Log ===\n"
                    f"  File      : {self._current_file.split('/')[-1] if self._current_file else '-'}\n"
                    f"  Start     : {_t_start.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"  End       : {_t_end.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    + _raw_size_str +
                    f"\n--- Output ---\n"
                    f"  SSH       : {self._rsync_addr_edit.text().strip()}\n"
                    f"  Path      : {self._rsync_path_edit.text().strip()}\n"
                    f"\n--- Phantom ---\n"
                    f"  X         : {self._ph_x_label.text()} mm\n"
                    f"  Y         : {self._ph_y_label.text()} mm\n"
                    f"  R         : {self._ph_r_label.text()} deg\n"
                    + _qa_block +
                    f"\n--- Controller ---\n"
                    + "".join(f"  {k:<20}: {_fv(w)}\n" for k, w in _ctrl_fields)
                    + _speed_line +
                    f"\n--- EUDAQ ---\n"
                    + "".join(f"  {k:<20}: {_fv(w)}\n" for k, w in _eudaq_fields) +
                    f"\n--- Run Stats ---\n"
                    f"  Elapsed   : {int(_m):02d}:{_s:05.2f}\n"
                    f"  CPU       : {_cpu:.1f}%\n"
                    f"  RAM       : {_mem.used//1024//1024}/{_mem.total//1024//1024} MiB ({_mem.percent:.1f}%)\n"
                    + _gpu_line +
                    f"  Disk write: {_disk_w:.1f} MiB\n"
                    f"  Net sent  : {_net_s:.1f} MiB\n"
                    f"  Net recv  : {_net_r:.1f} MiB\n"
                    "===============\n"
                )
                self._run_stats_start = None
            # Append ITS3 terminal log (snapshots written by _refresh each poll)
            try:
                _its3_log_path = getattr(self._terminal_widget, 'log_path', None)
                if _its3_log_path and os.path.exists(_its3_log_path):
                    with open(_its3_log_path, 'r', errors='replace') as _lf:
                        _its3_content = _lf.read()
                    if _its3_content.strip():
                        _program_log_content += f"\n--- ITS3 Session Log ---\n{_format_its3_log(_its3_content)}\n"
                    os.unlink(_its3_log_path)
                    self._terminal_widget.log_path = None
            except Exception:
                pass
            # Save log locally to <outpath>/log/ (always, regardless of rsync) — mirrors server layout
            try:
                _local_log_dir = os.path.join(self._outpath_label.text(), 'log')
                os.makedirs(_local_log_dir, exist_ok=True)
                _raw_base = os.path.splitext(os.path.basename(self._current_file))[0] if self._current_file else 'run_unknown'
                _local_log_path = os.path.join(_local_log_dir, f"{_raw_base}.log")
                with open(_local_log_path, 'w', encoding='utf-8') as _llf:
                    _llf.write(_program_log_content)
                print(f"[log] saved locally → {_local_log_path}")
            except Exception as _e:
                print(f"[log] local save failed: {_e}")
            rsync_addr = self._rsync_addr_edit.text().strip()
            rsync_rpath = self._rsync_path_edit.text().strip()
            rsync_dest = f"{rsync_addr}:{rsync_rpath}/raw" if rsync_addr and rsync_rpath else ""
            if rsync_dest and self._current_file and self._rsync_connected:
                from modules.ui.rsync_toast import RsyncToast
                print(f"[rsync] {self._current_file} → {rsync_dest}")
                fname_short = self._current_file.split('/')[-1]
                self._rsync_toast = RsyncToast(fname_short, rsync_addr, parent=self._window)
                self._rsync_toast.show_centered(self._window)
                self._rsync_mgr.upload(
                    self._current_file, rsync_dest, _program_log_content,
                    fname_short, rsync_addr, rsync_rpath,
                    gating_csv_content=self._build_gating_csv_content(),
                )
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
        self._vel_stop_run()
        _qa_mode = self._window._qa_mode
        if _qa_mode:
            self._launch_eudaq_default.setEnabled(True)
            self._window.running(False)
            _elapsed = time.monotonic() - self._qa_launch_time if self._qa_launch_time else 0
            self._qa_launch_time = None
        else:
            _elapsed = time.monotonic() - self._launch_time if getattr(self, '_launch_time', None) else 0
        _le = self._line_edits
        _prev_dlg = getattr(self, '_run_complete_dlg', None)
        if _prev_dlg is not None:
            _prev_dlg.close()  # ปิด popup รอบก่อนที่ยังค้างอยู่ ไม่ให้สะสม (non-modal)
        self._run_complete_dlg = _QACompleteDialog(
            self._window,
            file_name=(self._current_file or "").split("/")[-1] or "—",
            loops=_le["Loops"].text() if "Loops" in _le else "—",
            elapsed_s=_elapsed,
            energy=_le["energy"].text() if "energy" in _le else "—",
            mu=_le["MU"].text() if "MU" in _le else "—",
            num_alpides=_le["num_alpides"].text() if "num_alpides" in _le else "—",
            title="QA Acquisition Complete" if _qa_mode else "Treatment Acquisition Complete",
            modal=_qa_mode,
        )
        if _qa_mode:
            self._run_complete_dlg.exec_()
        else:
            # non-modal — ต้องไม่บล็อก Kill beam button ถ้า beam ยังค้างอยู่
            self._run_complete_dlg.show()
        try:
            import modules.sim as _sim
            if _sim.control_room is not None:
                _sim.control_room.reset()
        except Exception:
            pass

    def log_gate_event(self, state, x, y, r):
        """เก็บจังหวะที่ FPGA gate เปิด/ปิดจริง (\\xFE/\\xEF) พร้อมตำแหน่ง Zaber ณ ตอนนั้น
        — ไว้เช็คว่าบีมเข้า sensor ระหว่าง Zaber กำลังขยับหรือเปล่า"""
        self._gating_log.append((time.time(), state, x, y, r))

    def _build_gating_csv_content(self):
        try:
            trigger_freq_hz = self._line_edits["Trigger Freq. (Hz)"].text().strip()
        except Exception:
            trigger_freq_hz = ""
        lines = [
            f"# run_start_epoch={self._run_start_epoch or 0.0}",
            f"# run_stop_epoch={self._run_stop_epoch or 0.0}",
            f"# trigger_freq_hz={trigger_freq_hz}",
            "epoch,datetime,step_index,gate_state,x_mm,y_mm,r_mm",
        ]
        step_index = 0
        for epoch, state, x, y, r in self._gating_log:
            if state == "OPEN":
                step_index += 1
            readable = datetime.fromtimestamp(epoch).strftime('%Y-%m-%d %H:%M:%S.%f')
            lines.append(f"{epoch},{readable},{step_index},{state},{x:.4f},{y:.4f},{r:.4f}")
        return "\n".join(lines) + "\n"

    def get_new_outfile(self):
        raw_dir = os.path.join(self._outpath_label.text(), 'raw')
        try:
            files = [os.path.join(raw_dir, file) for file in os.listdir(raw_dir)]
        except FileNotFoundError:
            return None
        files = [myfile for myfile in files if os.path.isfile(myfile)]
        if files:
            return max(files, key=os.path.getmtime)
        else:
            return None
    
    def get_fpga_data(self):
        fpga_data = self._beam_ctrl.get_fpga_data()  # static serial params
        trigger_f_bin = bin(int(self._line_edits["Trigger Freq. (Hz)"].text())).lstrip('0b').zfill(16)
        trigger_f_byte_list = [int(trigger_f_bin[:-8], 2).to_bytes(1, 'big'), int(trigger_f_bin[-8:], 2).to_bytes(1, 'big')]
        alpide_delay_val = int(self._line_edits["Beam delay (ms)"].text())
        if alpide_delay_val > 255:
            raise ValueError(f"Beam delay {alpide_delay_val} ms เกินค่าสูงสุดที่ FPGA รองรับ (255 ms)")
        alpide_delay_byte = alpide_delay_val.to_bytes(1, 'big')
        fpga_data["byte_start_list"] = [
            b'\x00', b'\x01', b'\x00', b'\x00', b'\x00', b'\x00',
            alpide_delay_byte, trigger_f_byte_list[0], trigger_f_byte_list[1]
        ]
        return fpga_data

    def enable_beam(self):
        enabling = self._enable_checkbox.isChecked()
        if enabling:
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
                    self._ser.close()
                except:
                    pass

            fpga_data = self.get_fpga_data()
            self._ser = serial.Serial(port=get_port("fpga"), baudrate=fpga_data["baudrate"], parity=fpga_data["parity"],
                            bytesize=fpga_data["bytesize"], stopbits=fpga_data["stopbits"], timeout=1)
            
            self._ser.write(RESET_BYTE)
            self._ser.write(RESET_BYTE)

            self._kill_beam_btn.setChecked(False)
            self._stop_auto_kill_sequence()
            if self._enable_checkbox.checkState() == Qt.Checked:
                self.log("Beam ENABLED (\\x02 sent to FPGA)")
                self._ser.write(ENABLE_BYTE)
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
                beam_dialog = QMessageBox()
                beam_dialog.setIcon(QMessageBox.Warning)
                beam_dialog.setText("Beam status before disabling?")
                beam_dialog.setInformativeText("Press “Kill beam” if the beam is still active.\nPress “Continue” if the beam has ended.")
                beam_dialog.setWindowTitle("Beam check")
                kill_btn = beam_dialog.addButton("Kill beam", QMessageBox.DestructiveRole)
                kill_btn.setStyleSheet("background-color: #c62828; color: white; font-weight: bold; padding: 6px 16px;")
                done_btn = beam_dialog.addButton("Continue", QMessageBox.AcceptRole)
                done_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 16px;")
                cancel_btn = beam_dialog.addButton("Cancel", QMessageBox.RejectRole)
                cancel_btn.setStyleSheet("background-color: #f9a825; color: white; font-weight: bold; padding: 6px 16px;")
                beam_dialog.exec_()
                clicked = beam_dialog.clickedButton()
                if clicked == kill_btn:
                    if self._ser:
                        self._ser.write(b'\xFE')
                elif clicked == done_btn:
                    pass
                else:
                    self._enable_checkbox.blockSignals(True)
                    self._enable_checkbox.setChecked(True)
                    self._enable_checkbox.blockSignals(False)
                    return
                self._stop_auto_kill_sequence()
                self.log("Beam DISABLED (\\xF2 sent to FPGA)")
                self._ser.write(DISABLE_BYTE)
                self._kill_beam_btn.setEnabled(False)
                self._launch_eudaq_default.setEnabled(False)
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
                self._vel_stop_run()
                self._window.running(False)
                self._terminal_widget.clear()  # unchecking Enable dismisses the ended ITS3 session
        except ValueError as e:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Warning)
            fail_dialog.setText("ค่า parameter ไม่ถูกต้อง")
            fail_dialog.setInformativeText(str(e))
            fail_dialog.setWindowTitle("Parameter error")
            fail_dialog.setStandardButtons(QMessageBox.Ok)
            fail_dialog.exec_()
            self._enable_checkbox.blockSignals(True)
            self._enable_checkbox.setChecked(False)
            self._enable_checkbox.blockSignals(False)
            if not enabling:
                self._window.running(False)
            return
        except (ConnectionError, serial.SerialException) as e:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            fail_dialog.setText("No FPGA connection")
            fail_dialog.setWindowTitle("FPGA error")
            fail_dialog.setDetailedText(f"Please connect to FPGA\n{e}")
            fail_dialog.setStandardButtons(QMessageBox.Ok)
            fail_dialog.exec_()
            self._kill_beam_btn.setChecked(False)
            self._kill_beam_btn.setEnabled(False)
            self._launch_eudaq_default.setEnabled(False)
            if enabling:
                self._enable_checkbox.blockSignals(True)
                self._enable_checkbox.setChecked(False)
                self._enable_checkbox.blockSignals(False)
            else:
                self._window.running(False)
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

    def _set_qa_mode(self, qa: bool):
        _prev_qa = getattr(self._window, '_qa_mode', None)
        self._window._qa_mode = qa
        self._mode_treatment_btn.setStyleSheet(self._pill_inactive_style if qa else self._pill_active_style)
        self._mode_qa_btn.setStyleSheet(self._pill_active_style if qa else self._pill_inactive_style)
        self._enable_container.setVisible(not qa)
        self._kill_beam_btn.setEnabled(not qa)
        self._beam_ctrl_inner.setEnabled(not qa)
        self._launch_eudaq_default.setEnabled(qa)
        # Target position is QA-only; Speed serves both modes (QA sweep speed /
        # Treatment step-Apply-jog speed) and is clamped per _validate_speed_field.
        for edit in [self._qa_pos_x_edit, self._qa_pos_y_edit, self._qa_pos_r_edit]:
            edit.setEnabled(qa)
            edit.setVisible(qa)
        for edit in [self._vel_x_edit, self._vel_y_edit, self._vel_r_edit]:
            edit.setEnabled(True)
            edit.setVisible(True)
        _vel_tip = ("Sweep speed toward Target — 0 = axis stays still.\n"
                    "Also used by Apply / jog. Range 0–40 mm/s (R 0–80 °/s)."
                    if qa else
                    "Move speed — used by Apply, jog, and the per-loop step.\n"
                    "Range 2.5–40 mm/s (R 6–80 °/s), clamped to that band.")
        self._vel_x_edit.setToolTip(_vel_tip)
        self._vel_y_edit.setToolTip(_vel_tip)
        self._vel_r_edit.setToolTip(_vel_tip)
        # swap the shared Speed widgets between the QA and Treatment stores
        if _prev_qa is not None and _prev_qa != qa:
            self._speed_store['qa' if _prev_qa else 'trt'] = [
                self._vel_x_edit.text(), self._vel_y_edit.text(), self._vel_r_edit.text()]
        for _e, _v in zip((self._vel_x_edit, self._vel_y_edit, self._vel_r_edit),
                          self._speed_store['qa' if qa else 'trt']):
            _e.setText(_v)
        for _i in range(3):
            self._validate_speed_field(_i)
        for w in self._qa_col_widgets:
            w.setVisible(qa)
        # ซ่อนตัวเลขที่ไม่เกี่ยวใน QA mode
        for key in ["Exposure time (ms)", "Beam delay (ms)", "Beam on delay (ms)", "Beam off delay (ms)", "Loops",
                    "energy", "MU", "current",
                    "X step (mm)", "Y step (mm)", "R step (degree)"]:
            self._line_edits[key].setVisible(not qa)
        loops_edit = self._line_edits["Loops"]
        if qa:
            self._loops_saved = loops_edit.text()
            loops_edit.setText("1")
            loops_edit.setEnabled(False)
        else:
            loops_edit.setEnabled(True)
            if getattr(self, '_loops_saved', None):
                loops_edit.setText(self._loops_saved)
        self.check_connections()

    def check_connection(self, device):
        if device == "alpide":
            if alpide.found_daqs():
                self._window._alpide_connect = True
                if not alpide.is_programmed():
                    import modules.eudaq as eudaq
                    eudaq.install_firmware_auto(parent_widget=self._window)
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
        _ok = {"alpide": self._window._alpide_connect,
               "zaber":  self._window._zaber_connect,
               "fpga":   self._window._fpga_connect}.get(device)
        self.log(f"Check {device.upper()} — {'connected' if _ok else 'not found'}")
                
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
        if not self._ser or not self._ser.is_open:
            fail_dialog = QMessageBox()
            fail_dialog.setIcon(QMessageBox.Icon.Critical)
            fail_dialog.setText("FPGA not found!")
            fail_dialog.setWindowTitle("FPGA error")
            fail_dialog.setDetailedText("FPGA is not ready.")
            fail_dialog.setStandardButtons(QMessageBox.Ok) 
            fail_dialog.exec_()
            self._kill_beam_btn.setChecked(False)
            return
        

        self._stop_auto_kill_sequence()
        _byte = b'\xFE' if self._kill_beam_btn.isChecked() else b'\xEF'
        _sent = False
        for _attempt in range(2):
            try:
                if not self._ser.is_open:
                    raise serial.SerialException("port closed")
                self._ser.write(_byte)
                _sent = True
                break
            except Exception:
                if _attempt == 0:
                    # reopen และลองใหม่ 1 ครั้ง
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    try:
                        fpga_data = self.get_fpga_data()
                        self._ser = serial.Serial(
                            port=get_port("fpga"), baudrate=fpga_data["baudrate"],
                            parity=fpga_data["parity"], bytesize=fpga_data["bytesize"],
                            stopbits=fpga_data["stopbits"], timeout=1)
                        self.log("FPGA port reopened — retrying")
                    except Exception as _reopen_e:
                        self.log(f"FPGA reopen failed: {_reopen_e}")
                        break
        try:
            if _sent:
                if self._kill_beam_btn.isChecked():
                    self.log("Kill beam sent (\\xFE to FPGA)")
                    _sound.play(os.path.join(_SOUND_DIR, "kill-beam.mp4"), stop_after_ms=5000)
                    self._vel_stop_run()
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
                else:
                    self._launch_eudaq_default.setEnabled(True)
                    self._window.running(True)
            else:
                raise serial.SerialException("write failed after reopen")
        except Exception as e:
            self.log(f"FPGA write error: {e}")
            self._ser = None
            self._kill_beam_btn.setChecked(False)
            self._kill_beam_btn.setEnabled(False)
            self._launch_eudaq_default.setEnabled(False)
            err = QMessageBox()
            err.setIcon(QMessageBox.Icon.Critical)
            err.setWindowTitle("FPGA error")
            err.setText("ส่งคำสั่งไปยัง FPGA ไม่ได้")
            err.setDetailedText(str(e))
            err.setStandardButtons(QMessageBox.Ok)
            err.exec_()
            self._enable_checkbox.blockSignals(True)
            self._enable_checkbox.setChecked(False)
            self._enable_checkbox.blockSignals(False)
            self._window.running(False)

    def _start_auto_kill_sequence(self):
        self._blink_state = False
        self._blink_timer.start()
        if self._auto_kill_checkbox.isChecked():
            self._beam_ctrl._auto_kill_countdown = 5
            self._beam_ctrl._auto_kill_timer.start()
            self._kill_beam_btn.setText("Kill beam (5s)")

    def _stop_auto_kill_sequence(self):
        self._beam_ctrl._auto_kill_timer.stop()
        self._blink_timer.stop()
        self._kill_beam_btn.setText("Kill beam")
        self._kill_beam_btn.setStyleSheet(self._kill_beam_btn.styleSheet().replace(
            "background-color: #ff6f00;", "background-color: #c62828;"))

    def _tick_auto_kill(self):
        self._beam_ctrl._auto_kill_countdown -= 1
        if self._beam_ctrl._auto_kill_countdown <= 0:
            self._stop_auto_kill_sequence()
            if self._kill_beam_btn.isEnabled() and not self._kill_beam_btn.isChecked():
                self._kill_beam_btn.setChecked(True)
                self.kill_beam_action()
        else:
            self._kill_beam_btn.setText(f"Kill beam ({self._beam_ctrl._auto_kill_countdown}s)")

    def _tick_blink(self):
        self._blink_state = not self._blink_state
        color = "#ff6f00" if self._blink_state else "#c62828"
        self._kill_beam_btn.setStyleSheet(
            self._kill_beam_btn.styleSheet()
            .replace("background-color: #ff6f00;", "background-color: #c62828;")
            .replace("background-color: #c62828;", f"background-color: {color};", 1)
        )

    def _save_fields(self):
        """บันทึกค่า field ทั้งหมดลง config.json"""
        # fold the live Speed widgets into the active-mode store first
        _active = 'qa' if getattr(self._window, '_qa_mode', False) else 'trt'
        self._speed_store[_active] = [
            self._vel_x_edit.text(), self._vel_y_edit.text(), self._vel_r_edit.text()]
        try:
            self._config.set('fields', {k: v.text() for k, v in self._line_edits.items()})
            self._config.set('qa_pos', {
                'qa_pos_x': self._qa_pos_x_edit.text(),
                'qa_pos_y': self._qa_pos_y_edit.text(),
                'qa_pos_r': self._qa_pos_r_edit.text(),
                'vel_x': self._speed_store['qa'][0],
                'vel_y': self._speed_store['qa'][1],
                'vel_r': self._speed_store['qa'][2],
            })
            self._config.set('trt_speed', {
                'vel_x': self._speed_store['trt'][0],
                'vel_y': self._speed_store['trt'][1],
                'vel_r': self._speed_store['trt'][2],
            })
            self._config.save()
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._notif.handle_resize()

    def log(self, message: str):
        """Append a message to the Activity log tab."""
        self._app_log_widget.append(message)

    def _show_toast(self, title, message, duration_ms=3000, icon="\u2713", icon_color="#00e676"):
        self._notif.show_toast(title, message, duration_ms=duration_ms, icon=icon, icon_color=icon_color)

    def validate_fields(self, kind):
        # if kind == "num_alpides":
        msg = {
            "num_alpides": ["number of ALPIDEs", list(range(1, 7))],
            "num_events": ["number of events", list(range(1, 10000000))],
            "strobe": ["STROBE value", list(range(1, 801))],
            "ithr": ["I theshold", list(range(30, 121))],
            "energy": ["proton energy", list(range(70, 241))],
            "MU": ["MU", list(range(1, 100000))],
            "current": ["current", list(range(4, 300))],
            "Exposure time (ms)": ["exposure time", list(range(1, 100_000))],
            "Beam delay (ms)": ["beam dalay", list(range(0, 256))],
            "Beam on delay (ms)": ["beam on delay", list(range(0, 100_000))],
            "Beam off delay (ms)": ["beam off delay", list(range(0, 100_000))],
            "Loops": ["number of loops", list(range(1, 100))],
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