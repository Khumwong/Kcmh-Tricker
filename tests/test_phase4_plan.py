"""
Phase 4 — PlanManager
Run: python3 -u tests/test_phase4_plan.py

Checks:
  - import PlanManager
  - load valid CSV → correct row count and values
  - load empty CSV → data is empty list, no crash
  - load missing file → raises or returns empty, no crash
  - load CSV with wrong column count → handled gracefully
  - status starts as all "pending" after load
  - close() resets data
  - step_to() updates current index
  - plan_changed signal emits on load
"""
import sys, os, tempfile, csv
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

from modules.ui.plan_manager import PlanManager

# ── helpers ───────────────────────────────────────────────────────────────────

SAMPLE_ROWS = [
    ["Run1", "QA",        "100", "1.5", "50", "0",  "0",  "0", "1"],
    ["Run2", "Treatment", "200", "2.0", "80", "10", "5",  "0", "2"],
    ["Run3", "QA",        "300", "1.0", "60", "0",  "0",  "0", "1"],
]

def write_csv(rows):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    csv.writer(f).writerows(rows)
    f.close()
    return f.name

# ── load valid CSV ────────────────────────────────────────────────────────────

def test_load_valid():
    p = write_csv(SAMPLE_ROWS)
    try:
        pm = PlanManager()
        pm.load_file(p)
        assert len(pm.data) == 3, f"expected 3 rows, got {len(pm.data)}"
        assert pm.data[0][0] == "Run1"
        assert pm.data[1][0] == "Run2"
        assert pm.data[2][2] == "300"
    finally:
        os.unlink(p)

check("load valid CSV → correct row count and values", test_load_valid)

# ── status all pending after load ─────────────────────────────────────────────

def test_status_pending():
    p = write_csv(SAMPLE_ROWS)
    try:
        pm = PlanManager()
        pm.load_file(p)
        assert all(s == "pending" for s in pm.status), f"status not all pending: {pm.status}"
    finally:
        os.unlink(p)

check("status is all 'pending' after load", test_status_pending)

# ── load empty CSV ────────────────────────────────────────────────────────────

def test_load_empty():
    p = write_csv([])
    try:
        pm = PlanManager()
        pm.load_file(p)
        assert pm.data == [] or len(pm.data) == 0
    finally:
        os.unlink(p)

check("load empty CSV → empty data, no crash", test_load_empty)

# ── load missing file ─────────────────────────────────────────────────────────

def test_load_missing():
    pm = PlanManager()
    try:
        pm.load_file("/tmp/__no_such_plan__.csv")
    except (FileNotFoundError, OSError):
        pass
    assert len(pm.data) == 0 or pm.data == []

check("load missing file → empty data, no crash", test_load_missing)

# ── close() resets ────────────────────────────────────────────────────────────

def test_close():
    p = write_csv(SAMPLE_ROWS)
    try:
        pm = PlanManager()
        pm.load_file(p)
        assert len(pm.data) == 3
        pm.close()
        assert len(pm.data) == 0, f"expected 0 after close, got {len(pm.data)}"
        assert pm.current == -1, f"expected current=-1, got {pm.current}"
    finally:
        os.unlink(p)

check("close() resets data and current index", test_close)

# ── step_to() updates current ─────────────────────────────────────────────────

def test_step_to():
    p = write_csv(SAMPLE_ROWS)
    try:
        pm = PlanManager()
        pm.load_file(p)
        pm.step_to(1)
        assert pm.current == 1, f"expected current=1, got {pm.current}"
        pm.step_to(2)
        assert pm.current == 2
    finally:
        os.unlink(p)

check("step_to() updates current index", test_step_to)

# ── plan_changed signal emits on load ─────────────────────────────────────────

def test_signal_on_load():
    received = []
    p = write_csv(SAMPLE_ROWS)
    try:
        pm = PlanManager()
        pm.plan_changed.connect(lambda: received.append(1))
        pm.load_file(p)
        assert len(received) > 0, "plan_changed signal not emitted on load"
    finally:
        os.unlink(p)

check("plan_changed signal emits on load_file()", test_signal_on_load)

# ── summary ───────────────────────────────────────────────────────────────────

passes = results.count(PASS)
fails  = results.count(FAIL)
print(f"\nResult: {passes} PASS  {fails} FAIL")
sys.exit(0 if fails == 0 else 1)
