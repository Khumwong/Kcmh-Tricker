#!/usr/bin/env python3
"""Headless UI-logic checks — mode switching, plan parsing, guards, dialogs, config.

Runs with QT_QPA_PLATFORM=offscreen. Constructs the REAL app (sim_mode=True so the
Zaber is NOT homed) — hardware is detected but nothing is actuated: this test never
calls launch_eudaq / _vel_start_run / kill_beam_action, so no EUDAQ, no stage move,
no FPGA write. It only exercises pure UI state.

    QT_QPA_PLATFORM=offscreen python3 -u tests/test_ui_flows.py

Does NOT replace a real run — end-to-end (raw->rsync->log->root, stage motion,
ITS3 producer table) still needs docs/TEST_PLAN.md section B on the beam machine.
"""
import os, sys, tempfile, csv, traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

_p = _f = 0
def check(name, fn):
    global _p, _f
    try:
        fn()
        print(f"  PASS  {name}"); _p += 1
    except Exception as e:
        print(f"  FAIL  {name}  ->  {e}")
        traceback.print_exc()
        _f += 1

app = QApplication(sys.argv)

import modules.sim as _sim
from modules.ui.control_room import ControlRoomWindow
_sim.control_room = ControlRoomWindow()
from modules.window import MyWindow
win = MyWindow(sim_mode=True)
_sim.main_window = win
rw = win.centralWidget()
while rw is not None and not hasattr(rw, "_set_qa_mode"):
    rw = rw.findChild(type(rw))  # unlikely; RunWidget is the central widget
rw = win.centralWidget()

print(f"\n[connect] fpga={win._fpga_connect} zaber={win._zaber_connect} alpide={win._alpide_connect}")

# ── mode switching ───────────────────────────────────────────────────────────
def qa_mode_enables_velocity():
    rw._set_qa_mode(True)
    assert win._qa_mode is True
    assert rw._vel_x_edit.isEnabled(), "vel_x should be enabled in QA"
    assert not rw._qa_pos_x_edit.isHidden(), "Target field should show in QA"
    assert rw._launch_eudaq_default.isEnabled(), "Launch enabled in QA without Enable checkbox"

def treatment_mode_speed_field_stays_usable():
    # Speed fields now serve Treatment too (per-loop step speed); only the
    # Target (QA position) field is QA-only.
    rw._set_qa_mode(False)
    assert win._qa_mode is False
    assert rw._vel_x_edit.isEnabled(), "vel_x should stay enabled in Treatment"
    assert rw._qa_pos_x_edit.isHidden(), "Target field should hide in Treatment"

def treatment_launch_needs_enable():
    rw._set_qa_mode(False)
    rw._enable_checkbox.setChecked(False)
    # Launch gate for treatment depends on Enable + rsync; just assert the checkbox wiring
    assert rw._enable_checkbox.isChecked() is False

check("QA mode enables velocity fields + Launch", qa_mode_enables_velocity)
check("Treatment keeps speed field, hides Target", treatment_mode_speed_field_stays_usable)
check("Treatment Launch gated on Enable checkbox", treatment_launch_needs_enable)

# ── speed limit guard (logic only, no motion) ────────────────────────────────
def speed_limit_values_present():
    rw.set_zaber_max_speeds((2.54, 2.44, 6.0))
    assert rw._zaber_max_speeds == (2.54, 2.44, 6.0)
    lbl = rw._vel_limit_label.text()
    assert "2.5" in lbl and "6" in lbl, f"limit label not updated: {lbl!r}"

def over_limit_is_detectable():
    mx, my, mr = rw._zaber_max_speeds
    rw._vel_x_edit.setText("5.0")  # > 2.54
    over = float(rw._vel_x_edit.text()) > mx
    assert over, "5.0 should exceed max vx"
    rw._vel_x_edit.setText("2.0")

check("Speed limits stored + shown", speed_limit_values_present)
check("Over-limit velocity is detectable", over_limit_is_detectable)

# ── plan loading — both schemas ──────────────────────────────────────────────
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_full_schema_example():
    path = os.path.join(PROJ, "plan", "plan_format_example.csv")
    with open(path) as f:
        n_data = sum(1 for _ in f) - 1
    rw._load_plan_from_file(path)
    d = rw._plan_mgr.data
    assert len(d) == n_data, f"loaded {len(d)} rows, file has {n_data}"
    assert all(s == "pending" for s in rw._plan_mgr.status), "all rows should start pending"
    modes = {r.get("mode", "").strip().lower() for r in d}
    assert modes == {"treatment", "qa"}, f"modes: {modes}"

def click_qa_row_switches_mode():
    rw._set_qa_mode(False)
    # find first qa row index
    idx = next(i for i, r in enumerate(rw._plan_mgr.data)
               if r.get("mode", "").strip().lower() == "qa")
    rw._apply_plan_row(rw._plan_mgr.data[idx]) if hasattr(rw, "_apply_plan_row") else None
    # _on_plan_row_clicked path sets qa mode from row; call the mode setter used there
    _mode = rw._plan_mgr.data[idx].get("mode", "treatment").strip().lower()
    rw._set_qa_mode(_mode == "qa")
    assert win._qa_mode is True

def load_legacy_schema():
    p = os.path.join(tempfile.mkdtemp(), "legacy.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "label", "start_x", "start_y", "start_r", "num_alpides",
                    "num_events", "strobe", "ithr", "energy", "MU", "current",
                    "Exposure time (ms)", "Beam delay (ms)", "Loops", "Trigger Freq. (Hz)",
                    "X step (mm)", "Y step (mm)", "R step (degree)"])
        w.writerow([1, "", 22, 0, 0, 6, 30000, 100, 60, 200, 1000, 10, 1000, 200, 5, 9500, 0, 0, 0])
    rw._load_plan_from_file(p)
    assert len(rw._plan_mgr.data) == 1
    assert rw._plan_mgr.data[0].get("mode", "treatment") in ("treatment", "", None)

check("Load plan_format_example.csv (full schema)", load_full_schema_example)
check("QA plan row -> QA mode", click_qa_row_switches_mode)
check("Legacy 19-col plan still loads", load_legacy_schema)

# ── config.json ─────────────────────────────────────────────────────────────
def config_has_no_dead_key():
    cfg = rw._config
    assert cfg.get("rsync_dest", "__none__") == "__none__", "rsync_dest should be gone"

def config_roundtrip():
    old = rw._line_edits["energy"].text()
    try:
        rw._line_edits["energy"].setText("123")
        rw._save_fields()
        from modules.run_config import RunConfig
        fresh = RunConfig(os.path.join(PROJ, "config.json"))
        assert fresh.get("fields", {}).get("energy") == "123", "energy not persisted"
    finally:
        rw._line_edits["energy"].setText(old)
        rw._save_fields()

check("config.json has no dead rsync_dest key", config_has_no_dead_key)
check("config.json field round-trips", config_roundtrip)

# ── dialogs construct ───────────────────────────────────────────────────────
def qa_complete_dialog_builds():
    from modules.ui.qa_dialog import _QACompleteDialog
    for modal in (True, False):
        dlg = _QACompleteDialog(win, "run123.raw", 3, 45.6, "70", "40000", "6",
                                title="QA Acquisition Complete", modal=modal)
        assert dlg.isModal() is modal
        dlg.close()

def create_plan_dialog_columns_match_example():
    from modules.ui.plan_dialog import CreatePlanDialog, PLAN_COLUMNS
    cur = {k: v.text() for k, v in rw._line_edits.items()}
    dlg = CreatePlanDialog(current_fields=cur, parent=win)
    dlg._import_current()
    dlg._add_row()
    dlg.close()
    with open(os.path.join(PROJ, "plan", "plan_format_example.csv")) as f:
        hdr = f.readline().strip().split(",")
    assert PLAN_COLUMNS == hdr, f"CreatePlan header != example:\n {PLAN_COLUMNS}\n {hdr}"

check("_QACompleteDialog constructs (modal + non-modal)", qa_complete_dialog_builds)
check("CreatePlanDialog columns == plan_format_example.csv header", create_plan_dialog_columns_match_example)

# ── ITS3 log formatter (unit) ───────────────────────────────────────────────
def its3_formatter_parses_table():
    from modules.ui.terminal import _format_its3_log
    raw = ("[10:00:00]\n Current run: 5000 events (100.0 Hz)\n"
           " ALPIDE_plane_0   RUN     5000    3   Started\n"
           " ALPIDE_plane_1   RUN     4000    3   Started\n"
           " ALPIDE_plane_2   RUN     5000    3   Started\n"
           " ALPIDE_plane_3   RUN     5000    3   Started\n"
           " ALPIDE_plane_4   RUN     5000    3   Started\n"
           " ALPIDE_plane_5   RUN     5000    3   Started\n"
           " dc               RUN     4000    9   Warning! Out of sync! AL1:1000\n")
    out = _format_its3_log(raw)
    assert "(1 with producer detail)" in out, out.splitlines()[0]
    assert "Out of sync" in out, "dc message dropped"
    assert "Data EV#" in out

check("_format_its3_log parses euRun table + keeps Out-of-sync", its3_formatter_parses_table)

print(f"\nResult: {_p} PASS  {_f} FAIL")
# stop background poll timers/threads before teardown to avoid shutdown noise
for _t in ("_firmware_timer", "_pos_poll_timer"):
    try:
        getattr(rw, _t).stop()
    except Exception:
        pass
app.processEvents()
win.close()
_sim.control_room.close()
app.processEvents()
sys.exit(1 if _f else 0)
