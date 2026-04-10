# modules/ui/control_room.py
# Simulated Control Room Console — ใช้ใน sim mode เท่านั้น

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QFrame, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
import os, json


class BeamLamp(QLabel):
    """วงกลมไฟแสดงสถานะ beam"""
    COLORS = {
        "off":     "background-color: #444; border-radius: 40px; border: 3px solid #222;",
        "ready":   "background-color: #ffff00; border-radius: 40px; border: 3px solid #aaaa00;",
        "beam_on": "background-color: #ff3300; border-radius: 40px; border: 3px solid #aa2200;",
        "done":    "background-color: #00cc44; border-radius: 40px; border: 3px solid #008822;",
    }

    def __init__(self, label_text):
        super().__init__()
        self.setFixedSize(80, 80)
        self.setAlignment(Qt.AlignCenter)
        self._label_text = label_text
        self.set_state("off")

    def set_state(self, state):
        self._state = state
        self.setStyleSheet(self.COLORS.get(state, self.COLORS["off"]))


class ControlRoomWindow(QWidget):
    # signals ส่งไปยัง RunProgress
    beam_on_signal = pyqtSignal()
    beam_off_signal = pyqtSignal()

    def __init__(self, total_mu=30000):
        super().__init__()
        self._total_mu = total_mu
        self._current_mu = 0.0
        self._mu_per_step = 0.0
        self._mu_rate = 0.0
        self._beam_active = False
        self._prepared = False

        self._mu_timer = QTimer()
        self._mu_timer.setInterval(100)
        self._mu_timer.timeout.connect(self._tick_mu)

        self._prepare_timer = QTimer()
        self._prepare_timer.setSingleShot(True)
        self._prepare_timer.setInterval(3000)
        self._prepare_timer.timeout.connect(self._on_prepare_done)

        self._config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json")

        self.setWindowTitle("Control Room Console [SIM]")
        self.setFixedSize(520, 600)
        self._init_ui()
        self._load_ctrl_config()

    def _init_ui(self):
        main = QVBoxLayout()
        main.setSpacing(16)
        main.setContentsMargins(20, 20, 20, 20)

        # ── title ──────────────────────────────────────────────
        title = QLabel("KCMH Control Room Console")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        main.addWidget(title)

        sim_badge = QLabel("[ SIMULATION MODE ]")
        sim_badge.setAlignment(Qt.AlignCenter)
        sim_badge.setStyleSheet("color: orange; font-size: 13px; font-weight: bold;")
        main.addWidget(sim_badge)

        # ── beam lamps ─────────────────────────────────────────
        lamp_frame = QFrame()
        lamp_frame.setStyleSheet("QFrame { background: #1a1a1a; border-radius: 12px; }")
        lamp_layout = QHBoxLayout()
        lamp_layout.setContentsMargins(20, 20, 20, 20)
        lamp_layout.setSpacing(30)

        self._lamp_ready   = BeamLamp("Ready")
        self._lamp_beam_on = BeamLamp("Beam On")
        self._lamp_done    = BeamLamp("Done")

        for lamp, text in [
            (self._lamp_ready,   "Ready"),
            (self._lamp_beam_on, "Beam On"),
            (self._lamp_done,    "Done"),
        ]:
            col = QVBoxLayout()
            col.addWidget(lamp, alignment=Qt.AlignCenter)
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: white; font-size: 13px;")
            col.addWidget(lbl)
            lamp_layout.addLayout(col)

        lamp_frame.setLayout(lamp_layout)
        main.addWidget(lamp_frame)

        # ── MU settings (กรอกเองก่อน run) ────────────────────────
        settings_frame = QFrame()
        settings_frame.setStyleSheet("QFrame { background: #1e1e1e; border-radius: 10px; }")
        settings_layout = QHBoxLayout()
        settings_layout.setContentsMargins(16, 10, 16, 10)
        settings_layout.setSpacing(20)

        field_style = "color: white; font-size: 13px;"
        edit_style = """
            QLineEdit {
                background: #333; color: #00ff88; font-size: 16px;
                border: 1px solid #555; border-radius: 6px; padding: 4px 8px;
                font-family: monospace;
            }
        """

        # Planned MU — กรอกจาก Varian plan
        col = QVBoxLayout()
        lbl = QLabel("Planned MU")
        lbl.setStyleSheet(field_style)
        lbl.setAlignment(Qt.AlignCenter)
        self._planned_mu_edit = QLineEdit(str(int(self._total_mu)))
        self._planned_mu_edit.setStyleSheet(edit_style)
        self._planned_mu_edit.setFixedWidth(140)
        self._planned_mu_edit.setAlignment(Qt.AlignCenter)
        col.addWidget(lbl)
        col.addWidget(self._planned_mu_edit, alignment=Qt.AlignCenter)
        settings_layout.addLayout(col)

        # MU/min — กรอกได้ (dose rate ของเครื่อง)
        col2 = QVBoxLayout()
        lbl2 = QLabel("MU/min")
        lbl2.setStyleSheet(field_style)
        lbl2.setAlignment(Qt.AlignCenter)
        self._mu_rate_edit = QLineEdit("600")
        self._mu_rate_edit.setStyleSheet(edit_style)
        self._mu_rate_edit.setFixedWidth(140)
        self._mu_rate_edit.setAlignment(Qt.AlignCenter)
        col2.addWidget(lbl2)
        col2.addWidget(self._mu_rate_edit, alignment=Qt.AlignCenter)
        settings_layout.addLayout(col2)

        settings_frame.setLayout(settings_layout)
        main.addWidget(settings_frame)

        self._planned_mu_edit.editingFinished.connect(self._save_ctrl_config)
        self._mu_rate_edit.editingFinished.connect(self._save_ctrl_config)

        # ── MU display ─────────────────────────────────────────
        mu_frame = QFrame()
        mu_frame.setStyleSheet("QFrame { background: #111; border-radius: 10px; }")
        mu_layout = QVBoxLayout()
        mu_layout.setContentsMargins(16, 12, 16, 12)

        mu_title = QLabel("Field Progress (MU Delivered)")
        mu_title.setAlignment(Qt.AlignCenter)
        mu_title.setStyleSheet("color: #aaa; font-size: 13px;")
        mu_layout.addWidget(mu_title)

        self._mu_display = QLabel("0  /  {:,}".format(self._total_mu))
        self._mu_display.setAlignment(Qt.AlignCenter)
        self._mu_display.setStyleSheet("color: #00ff88; font-size: 36px; font-family: monospace; font-weight: bold;")
        mu_layout.addWidget(self._mu_display)

        self._mu_bar = QProgressBar()
        self._mu_bar.setMaximum(1000)
        self._mu_bar.setValue(0)
        self._mu_bar.setTextVisible(True)
        self._mu_bar.setFormat("%.2f%%" % 0)
        self._mu_bar.setFixedHeight(28)
        self._mu_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #333;
                border-radius: 8px;
                background: #222;
                color: white;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00cc44, stop:1 #00ff88);
                border-radius: 6px;
            }
        """)
        mu_layout.addWidget(self._mu_bar)

        self._mu_rate_label = QLabel("MU/min: —")
        self._mu_rate_label.setAlignment(Qt.AlignCenter)
        self._mu_rate_label.setStyleSheet("color: #777; font-size: 12px;")
        mu_layout.addWidget(self._mu_rate_label)

        mu_frame.setLayout(mu_layout)
        main.addWidget(mu_frame)

        # ── beam status label ───────────────────────────────────
        self._status_label = QLabel("● Standby")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("color: #888; font-size: 15px; font-weight: bold;")
        main.addWidget(self._status_label)

        # ── buttons ────────────────────────────────────────────
        btn_style = """
            QPushButton {{
                font-size: 18px;
                font-weight: bold;
                border-radius: 10px;
                padding: 12px;
                color: white;
                background-color: {bg};
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:disabled {{ background-color: #444; color: #888; }}
        """
        self._prepare_btn = QPushButton("PREPARE")
        self._prepare_btn.setStyleSheet(btn_style.format(bg="#1565C0", hover="#1976D2"))
        self._prepare_btn.clicked.connect(self._on_prepare)

        self._ready_btn = QPushButton("READY")
        self._ready_btn.setStyleSheet(btn_style.format(bg="#F57F17", hover="#F9A825"))
        self._ready_btn.setEnabled(False)
        self._ready_btn.clicked.connect(self._on_ready)

        self._beam_on_btn = QPushButton("BEAM ON")
        self._beam_on_btn.setStyleSheet(btn_style.format(bg="#B71C1C", hover="#D32F2F"))
        self._beam_on_btn.setEnabled(False)
        self._beam_on_btn.clicked.connect(self._on_beam_on)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self._prepare_btn)
        btn_layout.addWidget(self._ready_btn)
        btn_layout.addWidget(self._beam_on_btn)
        main.addLayout(btn_layout)

        self.setLayout(main)
        self.setStyleSheet("QWidget { background-color: #2b2b2b; }")

    # ── button handlers ────────────────────────────────────────

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
        self._status_label.setText("● Preparing beam...")
        self._status_label.setStyleSheet("color: #ffaa00; font-size: 15px; font-weight: bold;")
        self._prepare_timer.start()

    def _on_prepare_done(self):
        self._log("Prepare done — enabling READY")
        self._status_label.setText("● Beam prepared — press READY")
        self._status_label.setStyleSheet("color: #ffff00; font-size: 15px; font-weight: bold;")
        self._ready_btn.setEnabled(True)

    def _on_ready(self):
        self._log("button: READY clicked")
        self._prepared = True
        self._ready_btn.setEnabled(False)
        self._lamp_ready.set_state("beam_on")
        self._status_label.setText("● Ready — press BEAM ON")
        self._status_label.setStyleSheet("color: #ff9900; font-size: 15px; font-weight: bold;")
        self._beam_on_btn.setEnabled(True)

    def _on_beam_on(self):
        self._log(f"button: BEAM ON clicked  (prepared={self._prepared})")
        if not self._prepared:
            return
        self._beam_active = True
        self._lamp_ready.set_state("off")
        self._lamp_beam_on.set_state("beam_on")
        self._status_label.setText("● BEAM ON")
        self._status_label.setStyleSheet("color: #ff3300; font-size: 15px; font-weight: bold;")
        self._beam_on_btn.setEnabled(False)
        self.beam_on_signal.emit()

    def _stop_beam(self):
        self._beam_active = False
        self._mu_timer.stop()
        self._lamp_beam_on.set_state("off")
        self._lamp_done.set_state("done")
        self._status_label.setText("● Beam Off — Done")
        self._status_label.setStyleSheet("color: #00cc44; font-size: 15px; font-weight: bold;")
        self._prepare_btn.setEnabled(True)

    def _tick_mu(self):
        if not self._beam_active:
            self._mu_timer.stop()
            return
        increment = self._mu_rate * 0.1  # MU ต่อ 100ms
        self._current_mu = min(self._current_mu + increment, self._total_mu)
        pct = self._current_mu / self._total_mu * 100 if self._total_mu > 0 else 0
        self._mu_display.setText("{:,.0f}  /  {:,.0f}".format(self._current_mu, self._total_mu))
        self._mu_bar.setValue(int(self._current_mu * 1000 / self._total_mu) if self._total_mu > 0 else 0)
        self._mu_bar.setFormat("{:.2f}%".format(pct))
        if self._current_mu >= self._total_mu:
            self._mu_timer.stop()
            self._stop_beam()
            self.beam_off_signal.emit()

    def start_residual_delivery(self):
        """Kill beam กด → ส่ง MU ที่เหลือออกตาม rate จนครบ Planned MU"""
        if not self._beam_active:
            return
        self._log(f"Residual delivery started — {self._current_mu:.0f} → {self._total_mu:.0f} MU at {self._mu_rate*60:.0f} MU/min")
        self._status_label.setText("● Releasing residual beam...")
        self._status_label.setStyleSheet("color: #ff9900; font-size: 15px; font-weight: bold;")
        self._mu_timer.start()

    # ── called by RunProgress ───────────────────────────────────

    def start_mu_timer(self, exposure_ms, loops):
        """อัพเดต MU display params — คำนวณ MU/step จาก MU/min และ exposure time"""
        try:
            self._total_mu = float(self._planned_mu_edit.text())
        except ValueError:
            self._total_mu = 1000
        try:
            mu_per_min = float(self._mu_rate_edit.text())
        except ValueError:
            mu_per_min = 600
        # MU ที่ยิงต่อ 1 step = (MU/min) × exposure_ms / 60000
        self._mu_per_step = mu_per_min * exposure_ms / 60000.0
        self._mu_rate = mu_per_min / 60.0  # MU/s สำหรับ residual delivery
        self._current_mu = 0.0  # delivered MU เริ่มที่ 0
        self._mu_bar.setValue(0)
        self._mu_bar.setFormat("0.00%")
        self._mu_display.setText("0  /  {:,.0f}".format(self._total_mu))
        self._mu_rate_label.setText("MU/min: {:,.0f}".format(mu_per_min))
        self._log(f"MU params — Planned={self._total_mu:.0f} MU, {mu_per_min:.0f} MU/min, {self._mu_per_step:.2f} MU/step")

    def set_mu_by_step(self, step, total_steps):
        """ถูกเรียกโดย RunProgress ทุกครั้งที่ step จบ — เพิ่ม delivered MU"""
        delivered = min(self._mu_per_step * step, self._total_mu)
        pct = delivered / self._total_mu * 100 if self._total_mu > 0 else 0
        self._current_mu = delivered
        self._mu_display.setText("{:,.0f}  /  {:,.0f}".format(delivered, self._total_mu))
        self._mu_bar.setValue(int(delivered * 1000 / self._total_mu) if self._total_mu > 0 else 0)
        self._mu_bar.setFormat("{:.2f}%".format(pct))
        if delivered >= self._total_mu:
            self._stop_beam()
            self.beam_off_signal.emit()

    def _load_ctrl_config(self):
        try:
            with open(self._config_path, "r") as f:
                cfg = json.load(f)
            ctrl = cfg.get("ctrl_fields", {})
            if "Planned MU" in ctrl:
                self._planned_mu_edit.setText(str(ctrl["Planned MU"]))
                try:
                    self._total_mu = float(ctrl["Planned MU"])
                    self._mu_display.setText("0  /  {:,.0f}".format(self._total_mu))
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
                "MU/min": self._mu_rate_edit.text(),
            }
            with open(self._config_path, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            self._log(f"_save_ctrl_config error: {e}")

    def reset(self):
        self._current_mu = 0.0
        self._mu_per_step = 0.0
        self._mu_rate = 0.0
        self._beam_active = False
        self._prepared = False
        self._mu_timer.stop()
        self._prepare_timer.stop()
        self._lamp_ready.set_state("off")
        self._lamp_beam_on.set_state("off")
        self._lamp_done.set_state("off")
        self._status_label.setText("● Standby")
        self._status_label.setStyleSheet("color: #888; font-size: 15px; font-weight: bold;")
        self._mu_bar.setValue(0)
        self._mu_bar.setFormat("0.00%")
        self._mu_display.setText("0  /  {:,.0f}".format(self._total_mu))
        self._mu_rate_label.setText("MU/min: —")
        self._prepare_btn.setEnabled(True)
        self._ready_btn.setEnabled(False)
        self._beam_on_btn.setEnabled(False)
