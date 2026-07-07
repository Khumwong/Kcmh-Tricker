"""
Phase 3 — RsyncManager
Run: python3 -u tests/test_phase3_rsync.py

Checks:
  - import RsyncManager
  - instantiate without crash
  - status_changed signal emits correctly
  - done / failed signals defined
  - progress signal emits (pct, speed)
  - connect() with bad host sets failed state (no hang)
  - _connected flag starts False
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
from PyQt5.QtCore import QEventLoop, QTimer
app = QApplication(sys.argv)

# ── import ────────────────────────────────────────────────────────────────────

from modules.rsync_manager import RsyncManager

# ── instantiate ───────────────────────────────────────────────────────────────

mgr = None

def test_instantiate():
    global mgr
    mgr = RsyncManager()
    assert mgr is not None

check("RsyncManager instantiates without crash", test_instantiate)

# ── initial state ─────────────────────────────────────────────────────────────

check("_connected starts False", lambda: (None, __builtins__)[0] or (
    setattr(sys, '_v', mgr._connected),
    None
) and not sys._v or not mgr._connected)

def test_initial_state():
    assert mgr._connected is False, f"expected False, got {mgr._connected}"

check("_connected starts False", test_initial_state)

# ── status_changed signal ─────────────────────────────────────────────────────

def test_status_signal():
    received = []
    mgr.status_changed.connect(lambda t, c: received.append((t, c)))
    mgr._emit_status("connecting...", "#ffffff")
    assert len(received) == 1, f"expected 1 emission, got {len(received)}"
    assert received[0][0] == "connecting..."
    assert received[0][1] == "#ffffff"

check("status_changed signal emits (text, color)", test_status_signal)

# ── done / failed signals exist ───────────────────────────────────────────────

check("signal 'done' defined",   lambda: (hasattr(mgr, 'done') or (_ for _ in ()).throw(AttributeError("no 'done' signal"))))
check("signal 'failed' defined", lambda: (hasattr(mgr, 'failed') or (_ for _ in ()).throw(AttributeError("no 'failed' signal"))))
check("signal 'progress' defined", lambda: (hasattr(mgr, 'progress') or (_ for _ in ()).throw(AttributeError("no 'progress' signal"))))

# ── connect() with unreachable host emits failed quickly ──────────────────────

def test_connect_bad_host():
    received = []
    mgr.failed.connect(lambda err: received.append(err))

    loop = QEventLoop()
    QTimer.singleShot(5000, loop.quit)
    mgr.failed.connect(lambda _: loop.quit())

    mgr.connect("user@192.0.2.1", "/no/such/path", password="")
    loop.exec_()

    assert len(received) > 0, "expected failed signal for unreachable host"

check("connect() with bad host emits failed (within 5s)", test_connect_bad_host)

# ── summary ───────────────────────────────────────────────────────────────────

passes = results.count(PASS)
fails  = results.count(FAIL)
print(f"\nResult: {passes} PASS  {fails} FAIL")
sys.exit(0 if fails == 0 else 1)
