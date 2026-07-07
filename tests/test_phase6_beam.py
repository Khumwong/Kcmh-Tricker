"""
Phase 6 — BeamController
Run: python3 -u tests/test_phase6_beam.py

Checks (no hardware needed):
  - import BeamController
  - instantiate without crash
  - FPGA byte constants are exactly correct (CRITICAL)
  - beam_enabled / beam_disabled / countdown_tick signals defined
  - auto-kill timer not running on init
  - _beam_on starts False
  - disable() when already off does not crash
  - get_fpga_data() returns required keys with correct types

NOTE: Actual serial write tests require real FPGA hardware.
      Run manually: enable → confirm \x02 received by FPGA
                    disable → confirm \xF2 received by FPGA
"""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = ["test"]

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, fn):
    try:
        fn()
        results.append(PASS)
        print(f"  ✅  {name}")
    except Exception as e:
        results.append(FAIL)
        print(f"  ❌  {name}  — {e}")

from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)

# ── import ────────────────────────────────────────────────────────────────────

from modules.beam_controller import BeamController, RESET_BYTE, ENABLE_BYTE, DISABLE_BYTE

# ── CRITICAL: byte constants must not change ──────────────────────────────────

def test_reset_byte():
    assert RESET_BYTE == b'\x00', f"RESET_BYTE changed! expected \\x00, got {RESET_BYTE!r}"

def test_enable_byte():
    assert ENABLE_BYTE == b'\x02', f"ENABLE_BYTE changed! expected \\x02, got {ENABLE_BYTE!r}"

def test_disable_byte():
    assert DISABLE_BYTE == b'\xF2', f"DISABLE_BYTE changed! expected \\xF2, got {DISABLE_BYTE!r}"

print("\n  ── CRITICAL: FPGA byte constants ──")
check("RESET_BYTE  == \\x00", test_reset_byte)
check("ENABLE_BYTE == \\x02", test_enable_byte)
check("DISABLE_BYTE == \\xF2", test_disable_byte)

# ── instantiate ───────────────────────────────────────────────────────────────

ctrl = None

def test_instantiate():
    global ctrl
    ctrl = BeamController(parent=None)
    assert ctrl is not None

check("BeamController instantiates without crash", test_instantiate)

# ── initial state ─────────────────────────────────────────────────────────────

def test_initial_state():
    assert ctrl._beam_on is False, f"_beam_on should start False, got {ctrl._beam_on}"
    assert not ctrl._auto_kill_timer.isActive(), "auto-kill timer should not run on init"

check("_beam_on starts False", test_initial_state)
check("auto-kill timer not active on init", lambda: (
    None if not ctrl._auto_kill_timer.isActive()
    else (_ for _ in ()).throw(AssertionError("timer is active at init"))
))

# ── signals defined ───────────────────────────────────────────────────────────

check("signal 'beam_enabled' defined",    lambda: (hasattr(ctrl, 'beam_enabled')    or (_ for _ in ()).throw(AttributeError())))
check("signal 'beam_disabled' defined",   lambda: (hasattr(ctrl, 'beam_disabled')   or (_ for _ in ()).throw(AttributeError())))
check("signal 'countdown_tick' defined",  lambda: (hasattr(ctrl, 'countdown_tick')  or (_ for _ in ()).throw(AttributeError())))

# ── disable() when already off ────────────────────────────────────────────────

check("disable() when beam already off does not crash",
      lambda: ctrl.disable(ser=None))

# ── get_fpga_data() ───────────────────────────────────────────────────────────

def test_fpga_data():
    import serial
    data = ctrl.get_fpga_data()
    required = {"baudrate": int, "parity": str, "bytesize": int, "stopbits": (int, float)}
    for key, expected_type in required.items():
        assert key in data, f"missing key: {key}"
        assert isinstance(data[key], expected_type), f"{key} wrong type: {type(data[key])}"

check("get_fpga_data() returns all required keys with correct types", test_fpga_data)

# ── summary ───────────────────────────────────────────────────────────────────

passes = results.count(PASS)
fails  = results.count(FAIL)
print(f"\nResult: {passes} PASS  {fails} FAIL")
if fails == 0:
    print("\n  ⚠️  Byte constants OK in code — still verify with real FPGA hardware before deploy")
sys.exit(0 if fails == 0 else 1)
