"""
Phase 1 — RunConfig (config.json persistence)
Run: python3 -u tests/test_phase1_config.py

Checks:
  - import RunConfig
  - save → reload → values preserved
  - missing file → defaults returned, no crash
  - corrupted JSON → defaults returned, no crash
  - set/get round-trip for all expected keys
"""
import sys, os, tempfile, json
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

# ── import ────────────────────────────────────────────────────────────────────

from modules.run_config import RunConfig

# ── save → reload ─────────────────────────────────────────────────────────────

def test_save_reload():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        p = f.name
    try:
        cfg = RunConfig(p)
        cfg.set("outpath", "/tmp/beam_output")
        cfg.set("num_events", "5000")
        cfg.set("rsync_address", "user@host")
        cfg.save()

        cfg2 = RunConfig(p)
        assert cfg2.get("outpath") == "/tmp/beam_output", f"outpath wrong: {cfg2.get('outpath')}"
        assert cfg2.get("num_events") == "5000", f"num_events wrong: {cfg2.get('num_events')}"
        assert cfg2.get("rsync_address") == "user@host", f"rsync_address wrong"
    finally:
        os.unlink(p)

check("save → reload preserves values", test_save_reload)

# ── missing file → defaults ───────────────────────────────────────────────────

def test_missing_file():
    cfg = RunConfig("/tmp/__nonexistent_kcmh__.json")
    val = cfg.get("outpath", "DEFAULT")
    assert val == "DEFAULT", f"expected DEFAULT, got {val}"

check("missing file returns default", test_missing_file)

# ── corrupted JSON → no crash ─────────────────────────────────────────────────

def test_corrupted():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        f.write("{ not valid json {{")
        p = f.name
    try:
        cfg = RunConfig(p)
        val = cfg.get("outpath", "FALLBACK")
        assert val == "FALLBACK"
    finally:
        os.unlink(p)

check("corrupted JSON returns default, no crash", test_corrupted)

# ── get with no default → None ────────────────────────────────────────────────

def test_get_none():
    cfg = RunConfig("/tmp/__nonexistent_kcmh__.json")
    assert cfg.get("nonexistent_key") is None

check("get() missing key with no default → None", test_get_none)

# ── all expected keys survive round-trip ──────────────────────────────────────

EXPECTED_KEYS = [
    "outpath", "rsync_address", "rsync_path",
    "num_alpides", "num_events", "strobe", "ithr", "energy",
    "MU", "current", "Loops", "Trigger Freq. (Hz)",
    "X step (mm)", "Y step (mm)", "R step (degree)",
    "Exposure time (ms)", "Beam delay (ms)",
]

def test_all_keys():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        p = f.name
    try:
        cfg = RunConfig(p)
        for k in EXPECTED_KEYS:
            cfg.set(k, f"val_{k}")
        cfg.save()
        cfg2 = RunConfig(p)
        for k in EXPECTED_KEYS:
            assert cfg2.get(k) == f"val_{k}", f"key '{k}' lost after reload"
    finally:
        os.unlink(p)

check("all expected config keys survive round-trip", test_all_keys)

# ── summary ───────────────────────────────────────────────────────────────────

passes = results.count(PASS)
fails  = results.count(FAIL)
print(f"\nResult: {passes} PASS  {fails} FAIL")
sys.exit(0 if fails == 0 else 1)
