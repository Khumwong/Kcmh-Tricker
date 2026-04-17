# modules/ui/control_room.py
# Simulated Control Room Console — ใช้ใน sim mode เท่านั้น

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QLineEdit, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor
import os, json


# ---------------------------------------------------------------------------
# Lamp indicator
# ---------------------------------------------------------------------------

class BeamLamp(QWidget):
    STYLES = {
        "off":     ("●", "#3a3a3a", "#555"),
        "ready":   ("●", "#f9ca24", "#f0932b"),
        "beam_on": ("●", "#ff4757", "#c0392b"),
        "done":    ("●", "#2ed573", "#27ae60"),
    }

    def __init__(self, label_text):
        super().__init__()
        self._label_text = label_text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        self._dot = QLabel("●")
        self._dot.setAlignment(Qt.AlignCenter)
        self._dot.setFixedSize(64, 64)

        self._lbl = QLabel(label_text)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet("color: #aaa; font-size: 12px; font-weight: bold; letter-spacing: 1px;")

        layout.addWidget(self._dot)
        layout.addWidget(self._lbl)
        self.set_state("off")

    def set_state(self, state):
        self._state = state
        dot_char, color, shadow = self.STYLES.get(state, self.STYLES["off"])
        self._dot.setText(dot_char)
        self._dot.setStyleSheet(f"""
            QLabel {{
                font-size: 56px;
                color: {color};
                background: transparent;
            }}
        """)
        if state != "off":
            self._lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; letter-spacing: 1px;")
        else:
            self._lbl.setStyleSheet("color: #555; font-size: 12px; font-weight: bold; letter-spacing: 1px;")


# ---------------------------------------------------------------------------
# Divider
# ---------------------------------------------------------------------------

def _hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("QFrame { background: #333; border: none; max-height: 1px; }")
    return line


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class ControlRoomWindow(QWidget):
    beam_on_signal  = pyqtSignal()
    beam_off_signal = pyqtSignal()

    _BTN = """
        QPushButton {{
            font-size: 15px;
            font-weight: bold;
            border-radius: 10px;
            padding: 14px 0;
            color: {fg};
            background-color: {bg};
            border: 2px solid {border};
            letter-spacing: 1px;
        }}
        QPushButton:hover:enabled {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #2a2a2a; color: #555; border-color: #333; }}
    """

    def __init__(self, total_mu=30000):
        super().__init__()
        self._total_mu    = total_mu
        self._current_mu  = 0.0
        self._mu_per_step = 0.0
        self._mu_rate     = 0.0
        self._beam_active = False
        self._prepared    = False

        self._mu_timer = QTimer()
        self._mu_timer.setInterval(100)
        self._mu_timer.timeout.connect(self._tick_mu)

        self._prepare_timer = QTimer()
        self._prepare_timer.setSingleShot(True)
        self._prepare_timer.setInterval(3000)
        self._prepare_timer.timeout.connect(self._on_prepare_done)

        self._config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json"
        )

        self.setWindowTitle("Control Room Console [SIM]")
        self.setFixedWidth(480)
        self.setStyleSheet("QWidget { background-color: #1a1a2e; color: #e0e0e0; }")
        self._init_ui()
        self._load_ctrl_config()

    # ── UI ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # title
        title = QLabel("KCMH CONTROL ROOM")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #e0e0e0; font-size: 17px; font-weight: bold; letter-spacing: 2px;")
        root.addWidget(title)

        # sim badge + hw toggle on same row
        badge_row = QHBoxLayout()
        badge_row.setSpacing(12)

        sim_badge = QLabel("[ SIM ]")
        sim_badge.setStyleSheet(
            "color: #f9ca24; font-size: 12px; font-weight: bold; "
            "background: #2d2d00; border-radius: 6px; padding: 3px 10px;"
        )
        sim_badge.setFixedHeight(28)

        self._hw_checkbox = QCheckBox("Connect devices")
        self._hw_checkbox.setStyleSheet("""
            QCheckBox { color: #aaa; font-size: 12px; spacing: 6px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;
                                   border: 2px solid #555; background: #222; }
            QCheckBox::indicator:checked { background: #2ed573; border-color: #2ed573; }
        """)
        self._hw_checkbox.setToolTip("ติ๊ก = ต่ออุปกรณ์จริงทุกอย่าง ยกเว้น beam")
        self._hw_checkbox.stateChanged.connect(self._on_hw_toggle)

        badge_row.addWidget(sim_badge, alignment=Qt.AlignVCenter)
        badge_row.addStretch(1)
        badge_row.addWidget(self._hw_checkbox, alignment=Qt.AlignVCenter)
        root.addLayout(badge_row)

        root.addWidget(_hline())

        # ── lamps ──────────────────────────────────────────────
        lamp_frame = QFrame()
        lamp_frame.setStyleSheet("QFrame { background: #16213e; border-radius: 12px; }")
        lamp_row = QHBoxLayout(lamp_frame)
        lamp_row.setContentsMargins(20, 16, 20, 16)
        lamp_row.setSpacing(0)

        self._lamp_ready   = BeamLamp("READY")
        self._lamp_beam_on = BeamLamp("BEAM ON")
        self._lamp_done    = BeamLamp("DONE")

        for lamp in (self._lamp_ready, self._lamp_beam_on, self._lamp_done):
            lamp_row.addWidget(lamp, 1, Qt.AlignCenter)

        root.addWidget(lamp_frame)

        # ── MU settings ────────────────────────────────────────
        settings_frame = QFrame()
        settings_frame.setStyleSheet("QFrame { background: #16213e; border-radius: 12px; }")
        settings_row = QHBoxLayout(settings_frame)
        settings_row.setContentsMargins(20, 14, 20, 14)
        settings_row.setSpacing(24)

        field_lbl_style = "color: #888; font-size: 12px; letter-spacing: 1px;"
        edit_style = """
            QLineEdit {
                background: #0f3460; color: #2ed573;
                font-size: 20px; font-weight: bold;
                border: 1px solid #2ed573; border-radius: 8px;
                padding: 6px 10px;
            }
        """

        for label_text, attr in [("Planned MU", "_planned_mu_edit"), ("MU / min", "_mu_rate_edit")]:
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(field_lbl_style)
            edit = QLineEdit()
            edit.setStyleSheet(edit_style)
            edit.setAlignment(Qt.AlignCenter)
            edit.setFixedHeight(46)
            setattr(self, attr, edit)
            col.addWidget(lbl)
            col.addWidget(edit)
            settings_row.addLayout(col)

        self._planned_mu_edit.setText(str(int(self._total_mu)))
        self._mu_rate_edit.setText("600")
        self._planned_mu_edit.editingFinished.connect(self._save_ctrl_config)
        self._mu_rate_edit.editingFinished.connect(self._save_ctrl_config)

        root.addWidget(settings_frame)

        # ── MU progress ────────────────────────────────────────
        mu_frame = QFrame()
        mu_frame.setStyleSheet("QFrame { background: #16213e; border-radius: 12px; }")
        mu_layout = QVBoxLayout(mu_frame)
        mu_layout.setContentsMargins(20, 14, 20, 14)
        mu_layout.setSpacing(8)

        mu_title = QLabel("MU Delivered")
        mu_title.setAlignment(Qt.AlignCenter)
        mu_title.setStyleSheet("color: #666; font-size: 11px; letter-spacing: 2px;")
        mu_layout.addWidget(mu_title)

        self._mu_display = QLabel("0  /  {:,}".format(int(self._total_mu)))
        self._mu_display.setAlignment(Qt.AlignCenter)
        self._mu_display.setStyleSheet(
            "color: #2ed573; font-size: 32px; font-weight: bold; font-family: Arial;"
        )
        mu_layout.addWidget(self._mu_display)

        self._mu_bar = QProgressBar()
        self._mu_bar.setMaximum(1000)
        self._mu_bar.setValue(0)
        self._mu_bar.setTextVisible(False)
        self._mu_bar.setFixedHeight(10)
        self._mu_bar.setStyleSheet("""
            QProgressBar {
                border: none; border-radius: 5px; background: #0f3460;
            }
            QProgressBar::chunk {
                border-radius: 5px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2ed573, stop:1 #17c0eb);
            }
        """)
        mu_layout.addWidget(self._mu_bar)

        self._mu_pct_label = QLabel("0.00%")
        self._mu_pct_label.setAlignment(Qt.AlignCenter)
        self._mu_pct_label.setStyleSheet("color: #555; font-size: 12px; font-family: Arial;")
        mu_layout.addWidget(self._mu_pct_label)

        self._mu_rate_label = QLabel("MU/min: —")
        self._mu_rate_label.setAlignment(Qt.AlignCenter)
        self._mu_rate_label.setStyleSheet("color: #444; font-size: 11px;")
        mu_layout.addWidget(self._mu_rate_label)

        root.addWidget(mu_frame)

        # ── status ─────────────────────────────────────────────
        self._status_label = QLabel("● Standby")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("color: #555; font-size: 14px; font-weight: bold;")
        root.addWidget(self._status_label)

        root.addWidget(_hline())

        # ── buttons ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._prepare_btn = QPushButton("PREPARE")
        self._prepare_btn.setStyleSheet(self._BTN.format(
            fg="white", bg="#0f3460", border="#1a6fb5", hover="#1a5276"
        ))

        self._ready_btn = QPushButton("READY")
        self._ready_btn.setStyleSheet(self._BTN.format(
            fg="white", bg="#7d4e00", border="#f39c12", hover="#e67e22"
        ))
        self._ready_btn.setEnabled(False)

        self._beam_on_btn = QPushButton("BEAM ON")
        self._beam_on_btn.setStyleSheet(self._BTN.format(
            fg="white", bg="#7b0000", border="#e74c3c", hover="#c0392b"
        ))
        self._beam_on_btn.setEnabled(False)

        for btn in (self._prepare_btn, self._ready_btn, self._beam_on_btn):
            btn.setFixedHeight(52)
            btn_row.addWidget(btn)

        self._prepare_btn.clicked.connect(self._on_prepare)
        self._ready_btn.clicked.connect(self._on_ready)
        self._beam_on_btn.clicked.connect(self._on_beam_on)

        root.addLayout(btn_row)

        root.addWidget(_hline())

        # ── Sim device buttons ──────────────────────────────────
        dev_row = QHBoxLayout()
        dev_row.setSpacing(8)

        self._daq_connected   = False
        self._zaber_connected = False
        self._fpga_connected  = False

        self._connect_daq_btn   = QPushButton("Connect DAQ")
        self._connect_zaber_btn = QPushButton("Connect Zaber")
        self._connect_fpga_btn  = QPushButton("Connect FPGA")

        for btn in (self._connect_daq_btn, self._connect_zaber_btn, self._connect_fpga_btn):
            btn.setFixedHeight(40)
            self._set_dev_btn_style(btn, connected=False)
            dev_row.addWidget(btn)

        self._connect_daq_btn.clicked.connect(self._on_toggle_daq)
        self._connect_zaber_btn.clicked.connect(self._on_toggle_zaber)
        self._connect_fpga_btn.clicked.connect(self._on_toggle_fpga)

        root.addLayout(dev_row)
        self.adjustSize()

    # ── hardware toggle ──────────────────────────────────────────────────

    # ── helper ───────────────────────────────────────────────────────────

    def _set_dev_btn_style(self, btn, connected):
        if connected:
            btn.setStyleSheet(self._BTN.format(
                fg="white", bg="#1e5c2e", border="#2ed573", hover="#27ae60"
            ))
        else:
            btn.setStyleSheet(self._BTN.format(
                fg="white", bg="#2d3436", border="#636e72", hover="#4a5568"
            ))

    def _update_main_connections(self, alpide=None, zaber=None, fpga=None):
        import modules.sim as _sim
        mw = _sim.main_window
        if mw is None:
            return
        if alpide is not None:
            mw._alpide_connect = alpide
        if zaber is not None:
            mw._zaber_connect = zaber
        if fpga is not None:
            mw._fpga_connect = fpga
        mw._run_widget.check_connections()

    # ── DAQ ──────────────────────────────────────────────────────────────

    def _on_toggle_daq(self):
        if self._daq_connected:
            self._daq_connected = False
            self._connect_daq_btn.setText("Connect DAQ")
            self._set_dev_btn_style(self._connect_daq_btn, False)
            import modules.alpide as _alpide
            _alpide.found_daqs = lambda: False
            self._update_main_connections(alpide=False)
            self._log("DAQ disconnected (sim)")
        else:
            import time
            from modules.ui.firmware_toast import FirmwareToast
            from PyQt5.QtWidgets import QApplication
            import modules.sim as _sim

            self._log("Connect DAQ (sim) — starting fake firmware install")
            parent = _sim.main_window if _sim.main_window is not None else self
            toast = FirmwareToast(parent=parent, fake=True)
            toast.show_centered(parent)

            for _ in range(50):  # 5 วินาที
                time.sleep(0.1)
                QApplication.processEvents()

            toast.set_done(success=True)

            self._daq_connected = True
            self._connect_daq_btn.setText("Disconnect DAQ")
            self._set_dev_btn_style(self._connect_daq_btn, True)
            import modules.alpide as _alpide
            _alpide.found_daqs = lambda: True
            self._update_main_connections(alpide=True)
            self._log("DAQ connected (sim)")

    # ── Zaber ─────────────────────────────────────────────────────────────

    def _on_toggle_zaber(self):
        import modules.sim as _sim
        import modules.zaber.connect as zaber_connect
        if self._zaber_connected:
            self._zaber_connected = False
            self._connect_zaber_btn.setText("Connect Zaber")
            self._set_dev_btn_style(self._connect_zaber_btn, False)
            def _zaber_disconnected(port):
                raise ConnectionError("Zaber not connected (sim)")
            zaber_connect.connect = _zaber_disconnected
            self._update_main_connections(zaber=False)
            self._log("Zaber disconnected (sim)")
        else:
            self._zaber_connected = True
            self._connect_zaber_btn.setText("Disconnect Zaber")
            self._set_dev_btn_style(self._connect_zaber_btn, True)
            zaber_connect.connect = lambda port: _sim._mock_conn
            self._update_main_connections(zaber=True)
            self._log("Zaber connected (sim)")

    # ── FPGA ──────────────────────────────────────────────────────────────

    def _on_toggle_fpga(self):
        import modules.fpga.connect as fpga
        if self._fpga_connected:
            self._fpga_connected = False
            self._connect_fpga_btn.setText("Connect FPGA")
            self._set_dev_btn_style(self._connect_fpga_btn, False)
            fpga.check_connection = lambda port: False
            self._update_main_connections(fpga=False)
            self._log("FPGA disconnected (sim)")
        else:
            self._fpga_connected = True
            self._connect_fpga_btn.setText("Disconnect FPGA")
            self._set_dev_btn_style(self._connect_fpga_btn, True)
            fpga.check_connection = lambda port: True
            self._update_main_connections(fpga=True)
            self._log("FPGA connected (sim)")

    def _on_hw_toggle(self, state):
        import modules.sim as _sim
        if state:
            self._log("Switching to HW MODE — restoring real hardware")
            _sim.apply_hw_mode()
        else:
            self._log("Switching to SIM MODE — re-applying mocks")
            _sim.apply_sim_mode()

    # ── button handlers ──────────────────────────────────────────────────

    def _log(self, msg):
        try:
            import modules.sim as _sim
            _sim._log.info(f"[ControlRoom] {msg}")
        except Exception:
            print(f"[ControlRoom] {msg}")

    def _on_prepare(self):
        self._log("button: PREPARE clicked")
        self._prepare_btn.setEnabled(False)
        self._lamp_ready.set_state("ready")
        self._set_status("● Preparing beam...", "#f9ca24")
        self._prepare_timer.start()

    def _on_prepare_done(self):
        self._log("Prepare done — enabling READY")
        self._set_status("● Beam prepared — press READY", "#f9ca24")
        self._ready_btn.setEnabled(True)

    def _on_ready(self):
        self._log("button: READY clicked")
        self._prepared = True
        self._ready_btn.setEnabled(False)
        self._lamp_ready.set_state("beam_on")
        self._set_status("● Ready — press BEAM ON", "#f39c12")
        self._beam_on_btn.setEnabled(True)

    def _on_beam_on(self):
        self._log(f"button: BEAM ON clicked  (prepared={self._prepared})")
        if not self._prepared:
            return
        self._beam_active = True
        self._lamp_ready.set_state("off")
        self._lamp_beam_on.set_state("beam_on")
        self._set_status("● BEAM ON", "#ff4757")
        self._beam_on_btn.setEnabled(False)
        self.beam_on_signal.emit()

    def _stop_beam(self):
        self._beam_active = False
        self._mu_timer.stop()
        self._lamp_beam_on.set_state("off")
        self._lamp_done.set_state("done")
        self._set_status("● Beam Off — Done", "#2ed573")
        self._prepare_btn.setEnabled(True)

    def _set_status(self, text, color):
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: bold;"
        )

    # ── MU timer ─────────────────────────────────────────────────────────

    def _tick_mu(self):
        if not self._beam_active:
            self._mu_timer.stop()
            return
        increment = self._mu_rate * 0.1
        self._current_mu = min(self._current_mu + increment, self._total_mu)
        self._update_mu_display()
        if self._current_mu >= self._total_mu:
            self._mu_timer.stop()
            self._stop_beam()
            self.beam_off_signal.emit()

    def _update_mu_display(self):
        pct = self._current_mu / self._total_mu * 100 if self._total_mu > 0 else 0
        self._mu_display.setText("{:,}  /  {:,}".format(
            int(self._current_mu), int(self._total_mu)
        ))
        self._mu_bar.setValue(int(self._current_mu * 1000 / self._total_mu) if self._total_mu > 0 else 0)
        self._mu_pct_label.setText("{:.2f}%".format(pct))

    def start_residual_delivery(self):
        if not self._beam_active:
            return
        self._log(f"Residual delivery started — {self._current_mu:.0f} → {self._total_mu:.0f} MU")
        self._set_status("● Releasing residual beam...", "#f39c12")
        self._mu_timer.start()

    # ── called by RunProgress ─────────────────────────────────────────────

    def start_mu_timer(self, exposure_ms, loops):
        try:
            self._total_mu = float(self._planned_mu_edit.text())
        except ValueError:
            self._total_mu = 1000
        try:
            mu_per_min = float(self._mu_rate_edit.text())
        except ValueError:
            mu_per_min = 600
        self._mu_per_step = mu_per_min * exposure_ms / 60000.0
        self._mu_rate = mu_per_min / 60.0
        self._current_mu = 0.0
        self._mu_bar.setValue(0)
        self._mu_pct_label.setText("0.00%")
        self._mu_display.setText("0  /  {:,}".format(int(self._total_mu)))
        self._mu_rate_label.setText("MU/min: {:,}".format(int(mu_per_min)))
        self._log(f"MU params — Planned={self._total_mu:.0f}, {mu_per_min:.0f} MU/min, {self._mu_per_step:.2f} MU/step")

    def set_mu_by_step(self, step, total_steps):
        delivered = min(self._mu_per_step * step, self._total_mu)
        self._current_mu = delivered
        self._update_mu_display()
        if delivered >= self._total_mu:
            self._stop_beam()
            self.beam_off_signal.emit()

    # ── config ────────────────────────────────────────────────────────────

    def _load_ctrl_config(self):
        try:
            with open(self._config_path, "r") as f:
                cfg = json.load(f)
            ctrl = cfg.get("ctrl_fields", {})
            if "Planned MU" in ctrl:
                self._planned_mu_edit.setText(str(ctrl["Planned MU"]))
                try:
                    self._total_mu = float(ctrl["Planned MU"])
                    self._mu_display.setText("0  /  {:,}".format(int(self._total_mu)))
                except ValueError:
                    pass
            if "MU/min" in ctrl:
                self._mu_rate_edit.setText(str(ctrl["MU/min"]))
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_ctrl_config(self):
        try:
            try:
                with open(self._config_path, "r") as f:
                    cfg = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                cfg = {}
            cfg["ctrl_fields"] = {
                "Planned MU": self._planned_mu_edit.text(),
                "MU/min":     self._mu_rate_edit.text(),
            }
            with open(self._config_path, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            self._log(f"_save_ctrl_config error: {e}")

    def reset(self):
        self._current_mu  = 0.0
        self._mu_per_step = 0.0
        self._mu_rate     = 0.0
        self._beam_active = False
        self._prepared    = False
        self._mu_timer.stop()
        self._prepare_timer.stop()
        self._lamp_ready.set_state("off")
        self._lamp_beam_on.set_state("off")
        self._lamp_done.set_state("off")
        self._set_status("● Standby", "#555")
        self._mu_bar.setValue(0)
        self._mu_pct_label.setText("0.00%")
        self._mu_display.setText("0  /  {:,}".format(int(self._total_mu)))
        self._mu_rate_label.setText("MU/min: —")
        self._prepare_btn.setEnabled(True)
        self._ready_btn.setEnabled(False)
        self._beam_on_btn.setEnabled(False)
