#!/usr/bin/env python3
"""
Check whether the FPGA beam gate (\\xFE/\\xEF) is actually stopping the EUDAQ
trigger during the CLOSE window, by comparing the *actual* number of recorded
events (from the run's conversion .log) against two predictions:

  - "gate has no effect on triggering": Trigger Freq (Hz) x full run duration
  - "gate fully stops triggering"     : Trigger Freq (Hz) x total OPEN duration

If the actual count matches the second prediction closely, the gate is doing
its job (no events are recorded while it's closed) — see the memory note /
conversation this was built from for why that does NOT prove the beam itself
stops (ALPIDE cannot see anything while ungated, whether or not beam is
present). This script only checks DAQ-side gating discipline, run over run —
it is not a beam-bleed detector.

Usage:
  python3 check_gating_consistency.py <run.log> <gating.csv>
"""

import argparse
import re
import sys


def load_gating_csv_header(path):
    run_start_epoch = None
    run_stop_epoch = None
    trigger_freq_hz = None
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if "run_start_epoch=" in line:
                    run_start_epoch = float(line.split("=", 1)[1])
                elif "run_stop_epoch=" in line:
                    run_stop_epoch = float(line.split("=", 1)[1])
                elif "trigger_freq_hz=" in line:
                    val = line.split("=", 1)[1].strip()
                    trigger_freq_hz = float(val) if val else None
                continue
            if line.startswith("epoch,"):
                continue
            parts = line.split(",")
            # epoch, datetime, step_index, gate_state, x_mm, y_mm, r_mm
            epoch = float(parts[0])
            step_index = int(parts[2])
            gate_state = parts[3]
            rows.append((epoch, step_index, gate_state))
    return run_start_epoch, run_stop_epoch, trigger_freq_hz, rows


def total_open_duration(rows):
    total = 0.0
    open_epoch = None
    for epoch, step_index, state in rows:
        if state == "OPEN":
            open_epoch = epoch
        elif state == "CLOSE" and open_epoch is not None:
            total += epoch - open_epoch
            open_epoch = None
    return total


def parse_data_events(log_path):
    with open(log_path, "r", errors="replace") as f:
        content = f.read()
    m = re.search(r"Data events\s*:\s*(\d+)", content)
    if not m:
        raise RuntimeError(f"'Data events' not found in {log_path}")
    return int(m.group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_log", help="Run's conversion .log (has 'Data events : N')")
    parser.add_argument("gating_csv", help="<run>_gating.csv sidecar")
    parser.add_argument("--trigger-freq", type=float, default=None,
                         help="Override Trigger Freq (Hz) if not present in the CSV header")
    args = parser.parse_args()

    run_start_epoch, run_stop_epoch, trigger_freq_hz, rows = load_gating_csv_header(args.gating_csv)
    trigger_freq_hz = args.trigger_freq or trigger_freq_hz
    if trigger_freq_hz is None:
        raise SystemExit(
            "Trigger Freq (Hz) not found in CSV header and not given via --trigger-freq. "
            "(Older gating CSVs made before this field was added need --trigger-freq.)"
        )
    if not rows:
        raise SystemExit(f"No rows found in {args.gating_csv}")

    full_duration = run_stop_epoch - run_start_epoch
    open_duration = total_open_duration(rows)
    actual_events = parse_data_events(args.run_log)

    predicted_if_gate_ignored = trigger_freq_hz * full_duration
    predicted_if_gate_works = trigger_freq_hz * open_duration

    err_ignored = abs(actual_events - predicted_if_gate_ignored) / predicted_if_gate_ignored * 100
    err_works = abs(actual_events - predicted_if_gate_works) / predicted_if_gate_works * 100 if predicted_if_gate_works else float("inf")

    print("=" * 70)
    print("Gating consistency check")
    print("=" * 70)
    print(f"Trigger Freq (Hz)          : {trigger_freq_hz}")
    print(f"Full run duration (s)      : {full_duration:.3f}")
    print(f"Total OPEN duration (s)    : {open_duration:.3f}")
    print(f"Actual Data events         : {actual_events}")
    print()
    print(f"Predicted if gate has NO effect (trigger runs the whole time):")
    print(f"  {trigger_freq_hz} x {full_duration:.3f} = {predicted_if_gate_ignored:.0f}  (actual is {err_ignored:.1f}% off)")
    print()
    print(f"Predicted if gate fully stops triggering while CLOSE:")
    print(f"  {trigger_freq_hz} x {open_duration:.3f} = {predicted_if_gate_works:.0f}  (actual is {err_works:.1f}% off)")
    print()
    if err_works < 5.0:
        print("Verdict: gate looks HEALTHY — actual event count matches 'fully gated' prediction closely.")
    elif err_works < err_ignored:
        print("Verdict: closer to 'fully gated' than 'ungated', but the gap is larger than expected — worth a second look.")
    else:
        print("Verdict: closer to 'ungated' than 'fully gated' — trigger may not be stopping during CLOSE. Investigate.")


if __name__ == "__main__":
    main()
