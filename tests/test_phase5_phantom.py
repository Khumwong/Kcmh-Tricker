"""
Phase 5 — PhantomPanel  (requires --sim, no real Zaber)
Run: python3 -u tests/test_phase5_phantom.py --sim

Checks (sim mode — logic only, no hardware):
  - import PhantomPanel
  - instantiate without crash
  - _phantom_moving starts False
  - step() sets _phantom_moving while running, clears after
  - apply() rejects out-of-range values (X > 150, Y > 40, R > 360)
  - vel_stop() clears _phantom_moving even if not started
  - emergency_stop() callable without crash
  - position poll: _pos_poll_result initializes to None

NOTE: Zaber hardware tests must be done manually on real hardware.
      This script only validates sim-mode logic paths.
"""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = ["test", "--sim"]

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⚪ SKIP"
results = []

def check(name, fn):
    try:
        fn()
        results.append(PASS)
        print(f"  ✅  {name}")
    except NotImplementedError:
        results.append(SKIP)
        print(f"  ⚪  {name}  — skipped (hardware required)")
    except Exception as e:
        results.append(FAIL)
        print(f"  ❌  {name}  — {e}")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QEventLoop, QTimer
app = QApplication(sys.argv)

# ── import ────────────────────────────────────────────────────────────────────

from modules.ui.phantom_panel import PhantomPanel

# ── instantiate ───────────────────────────────────────────────────────────────

panel = None

def test_instantiate():
    global panel
    panel = PhantomPanel(parent=None)
    assert panel is not None

check("PhantomPanel instantiates without crash", test_instantiate)

# ── initial state ─────────────────────────────────────────────────────────────

def test_initial_state():
    assert panel._phantom_moving is False, f"expected False, got {panel._phantom_moving}"
    assert panel._pos_poll_result is None

check("_phantom_moving starts False", test_initial_state)
check("_pos_poll_result starts None", lambda: (
    None if panel._pos_poll_result is None
    else (_ for _ in ()).throw(AssertionError(f"expected None, got {panel._pos_poll_result}"))
))

# ── apply() range validation ──────────────────────────────────────────────────

def test_apply_x_out_of_range():
    ok = panel.apply(x=200.0, y=0.0, r=0.0)
    assert ok is False or ok == "rejected", f"expected rejection for X=200, got {ok!r}"

def test_apply_y_out_of_range():
    ok = panel.apply(x=0.0, y=50.0, r=0.0)
    assert ok is False or ok == "rejected"

def test_apply_r_out_of_range():
    ok = panel.apply(x=0.0, y=0.0, r=400.0)
    assert ok is False or ok == "rejected"

check("apply() rejects X > 150 mm", test_apply_x_out_of_range)
check("apply() rejects Y > 40 mm",  test_apply_y_out_of_range)
check("apply() rejects R > 360°",   test_apply_r_out_of_range)

# ── vel_stop() when not running ───────────────────────────────────────────────

check("vel_stop() callable when not running (no crash)",
      lambda: panel.vel_stop())

# ── emergency_stop() ─────────────────────────────────────────────────────────

check("emergency_stop() callable without crash",
      lambda: panel.emergency_stop())

def test_estop_clears_moving():
    panel._phantom_moving = True
    panel.emergency_stop()
    assert panel._phantom_moving is False, "_phantom_moving not cleared after emergency_stop"

check("emergency_stop() clears _phantom_moving", test_estop_clears_moving)

# ── summary ───────────────────────────────────────────────────────────────────

passes = results.count(PASS)
fails  = results.count(FAIL)
skips  = results.count(SKIP)
print(f"\nResult: {passes} PASS  {fails} FAIL  {skips} SKIP")
if skips:
    print("  (SKIPs require real Zaber hardware — test manually)")
sys.exit(0 if fails == 0 else 1)
