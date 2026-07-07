"""
Phase 2 — NotificationPanel
Run: python3 -u tests/test_phase2_notification.py

Checks:
  - import NotificationPanel
  - instantiate without crash
  - show_toast() appends to _notifications
  - show_toast() with error icon appends correctly
  - clear() empties _notifications and resets _unread_count
  - _unread_count increments on show_toast
  - bell button and badge are accessible
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

from modules.ui.notification_panel import NotificationPanel

# ── instantiate (parent=None → toasts become top-level windows, ok for test) ──

panel = None

def test_instantiate():
    global panel
    panel = NotificationPanel(parent_widget=None)
    assert panel is not None

check("NotificationPanel instantiates without crash", test_instantiate)

# ── initial state ─────────────────────────────────────────────────────────────

def test_initial_state():
    assert panel._notifications == []
    assert panel._unread_count == 0

check("_notifications starts empty, _unread_count starts 0", test_initial_state)

# ── show_toast() appends to history ──────────────────────────────────────────

def test_toast_appends():
    panel.show_toast("Title A", "Body A")
    assert len(panel._notifications) == 1
    assert panel._notifications[0]["title"] == "Title A"
    assert panel._notifications[0]["message"] == "Body A"
    assert panel._notifications[0]["icon"] == "✓"

check("show_toast() appends to _notifications", test_toast_appends)

def test_toast_error_icon():
    panel.show_toast("Error", "Something failed", icon="✗", icon_color="#ef5350")
    assert panel._notifications[0]["icon"] == "✗"
    assert panel._notifications[0]["icon_color"] == "#ef5350"

check("show_toast() with error icon stores correct icon", test_toast_error_icon)

# ── _unread_count increments ──────────────────────────────────────────────────

def test_unread_count():
    before = panel._unread_count
    panel.show_toast("Another", "msg")
    assert panel._unread_count == before + 1, f"expected {before+1}, got {panel._unread_count}"

check("_unread_count increments on show_toast()", test_unread_count)

# ── bell widgets exist ────────────────────────────────────────────────────────

check("_bell_btn attribute exists", lambda: (
    None if hasattr(panel, '_bell_btn')
    else (_ for _ in ()).throw(AttributeError("no _bell_btn"))
))
check("_bell_badge attribute exists", lambda: (
    None if hasattr(panel, '_bell_badge')
    else (_ for _ in ()).throw(AttributeError("no _bell_badge"))
))

# ── clear() resets everything ─────────────────────────────────────────────────

def test_clear():
    panel.show_toast("extra", "msg")
    panel.clear()
    assert panel._notifications == [], f"expected [], got {panel._notifications}"
    assert panel._unread_count == 0, f"expected 0, got {panel._unread_count}"

check("clear() empties _notifications and resets _unread_count", test_clear)

# ── summary ───────────────────────────────────────────────────────────────────

passes = results.count(PASS)
fails  = results.count(FAIL)
print(f"\nResult: {passes} PASS  {fails} FAIL")
sys.exit(0 if fails == 0 else 1)
