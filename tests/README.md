# Tests

One script per refactor phase. Run each after finishing that phase.

| Script | Phase | Hardware needed |
|--------|-------|----------------|
| `test_phase0_auxiliary.py` | Move classes out of run.py | ไม่ |
| `test_phase1_config.py`    | RunConfig (config.json)    | ไม่ |
| `test_phase2_notification.py` | NotificationPanel       | ไม่ |
| `test_phase3_rsync.py`     | RsyncManager              | ไม่ (SSH test แยก) |
| `test_phase4_plan.py`      | PlanManager               | ไม่ |
| `test_phase5_phantom.py`   | PhantomPanel              | Zaber (manual) |
| `test_phase6_beam.py`      | BeamController            | FPGA (manual) |

```bash
python3 -u tests/test_phase0_auxiliary.py
python3 -u tests/test_phase1_config.py
python3 -u tests/test_phase2_notification.py
python3 -u tests/test_phase3_rsync.py
python3 -u tests/test_phase4_plan.py
python3 -u tests/test_phase5_phantom.py --sim
python3 -u tests/test_phase6_beam.py
```
