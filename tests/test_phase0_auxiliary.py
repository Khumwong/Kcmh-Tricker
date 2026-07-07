"""
Phase 0 — Auxiliary classes moved out of run.py
Run: python3 -u tests/test_phase0_auxiliary.py

Checks:
  - ZaberMoveDialog importable from new location
  - EmbeddedTerminal importable from new location
  - AppLogWidget importable from new location
  - _QACompleteDialog importable from new location
  - run.py still works (backward-compat re-exports)
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

# ── imports from new locations ────────────────────────────────────────────────

check("ZaberMoveDialog importable from ui/zaber_dialog",
      lambda: __import__("modules.ui.zaber_dialog", fromlist=["ZaberMoveDialog"]))

check("EmbeddedTerminal importable from ui/terminal",
      lambda: __import__("modules.ui.terminal", fromlist=["EmbeddedTerminal"]))

check("AppLogWidget importable from ui/terminal",
      lambda: __import__("modules.ui.terminal", fromlist=["AppLogWidget"]))

check("_QACompleteDialog importable from ui/qa_dialog",
      lambda: __import__("modules.ui.qa_dialog", fromlist=["_QACompleteDialog"]))

# ── backward-compat: run.py still exports these ───────────────────────────────

check("ZaberMoveDialog still importable from run (re-export)",
      lambda: __import__("modules.ui.run", fromlist=["ZaberMoveDialog"]))

check("EmbeddedTerminal still importable from run (re-export)",
      lambda: __import__("modules.ui.run", fromlist=["EmbeddedTerminal"]))

# ── classes are actually the same object (not duplicated) ─────────────────────

def check_same_class():
    from modules.ui.zaber_dialog import ZaberMoveDialog as A
    from modules.ui.run import ZaberMoveDialog as B
    assert A is B, "ZaberMoveDialog is duplicated, not re-exported"

check("ZaberMoveDialog is same class (not copied)", check_same_class)

# ── summary ───────────────────────────────────────────────────────────────────

passes = results.count(PASS)
fails  = results.count(FAIL)
print(f"\nResult: {passes} PASS  {fails} FAIL")
sys.exit(0 if fails == 0 else 1)
