#!/usr/bin/env python3
"""
Draw a 'Hits vs Event' plot with a second X-axis below it showing the Zaber
position that was active at each Event ID — same data as the
'Hits vs Event with Zaber Position' / 'Hits vs Zaber Position' ROOT objects,
just rendered as a single annotated figure instead of a separate histogram.

Usage:
  python3 plot_hits_with_position_axis.py <root_file> <zaber_csv> [--plane N] [-o out.png]
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import uproot

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from StdEventMonitor_fast import load_zaber_csv, build_event_step_index, detect_varying_zaber_axes

_AXIS_COL = {"x": 2, "y": 3, "r": 4}


def default_zaber_csv_path(root_file_path):
    """<rpath>/root/<base>.root -> <rpath>/zaber/<base>_zaber.csv, matching rsync_manager.py's layout."""
    root_file_path = os.path.abspath(root_file_path)
    base = os.path.splitext(os.path.basename(root_file_path))[0]
    dirname = os.path.dirname(root_file_path)
    zaber_dir = os.path.join(os.path.dirname(dirname), "zaber") if os.path.basename(dirname) == "root" else dirname
    return os.path.join(zaber_dir, f"{base}_zaber.csv")


def compute_step_transitions(zaber_csv_path, min_event_id, max_event_id):
    """Event ID + position value at the start of every step (not a sampled few)."""
    run_start_epoch, run_stop_epoch, rows = load_zaber_csv(zaber_csv_path)
    if not rows:
        raise SystemExit(f"No rows found in {zaber_csv_path}")

    varying = detect_varying_zaber_axes(rows)
    if not varying:
        raise SystemExit("No Zaber axis varied during this run — nothing to annotate.")
    axis_key, axis_label, _ = varying[0]

    n_steps = max(row[1] for row in rows) + 1
    step_value = np.zeros(n_steps, dtype=np.float64)
    for row in rows:
        step_value[row[1]] = row[_AXIS_COL[axis_key]]

    step_index_by_offset = build_event_step_index(
        min_event_id, max_event_id, run_start_epoch, run_stop_epoch, rows
    )

    # offsets where the active step actually changes, plus the very first event (step 0's start)
    transition_offsets = np.flatnonzero(np.diff(step_index_by_offset)) + 1
    boundary_offsets = np.concatenate(([0], transition_offsets))
    boundary_event_ids = boundary_offsets + min_event_id
    boundary_values = step_value[step_index_by_offset[boundary_offsets]]

    return boundary_event_ids, boundary_values, axis_label


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root_file")
    parser.add_argument("zaber_csv", nargs="?", default=None,
                         help="Default: auto-derived from root_file's .../root/<base>.root -> .../zaber/<base>_zaber.csv")
    parser.add_argument("--plane", type=int, default=None,
                         help="Plane ID -> 'Hits Sensor Plane N' (default: global 'Hits vs Event')")
    parser.add_argument("-o", "--output", default=None,
                         help="Default: <base>_hits_with_position.png next to the root file")
    args = parser.parse_args()

    zaber_csv = args.zaber_csv or default_zaber_csv_path(args.root_file)
    if not os.path.isfile(zaber_csv):
        raise SystemExit(
            f"Zaber CSV not found: {zaber_csv}\n"
            f"Pass it explicitly as the second argument if it lives somewhere else."
        )

    output_path = args.output
    if output_path is None:
        base = os.path.splitext(os.path.basename(args.root_file))[0]
        output_path = f"{base}_hits_with_position.png"

    f = uproot.open(args.root_file)
    key = ("EUDAQ Monitor/Hits vs Event" if args.plane is None
           else f"EUDAQ Monitor/Planes/Hits Sensor Plane {args.plane}")
    h = f[key]
    counts, edges = h.to_numpy()

    min_event_id = int(round(edges[0] + 0.5))
    max_event_id = int(round(edges[-1] - 0.5))
    centers = (edges[:-1] + edges[1:]) / 2.0
    width = edges[1] - edges[0]

    boundary_event_ids, boundary_values, axis_label = compute_step_transitions(
        zaber_csv, min_event_id, max_event_id
    )

    fig_width = max(11, len(boundary_event_ids) * 0.45)
    fig, ax = plt.subplots(figsize=(fig_width, 6))
    ax.bar(centers, counts, width=width, color="navy", linewidth=0)
    ax.set_xlabel("Event ID")
    ax.set_ylabel("Hits")
    ax.set_title(key.split("/")[-1], pad=40)
    ax.set_xlim(min_event_id, max_event_id)

    # dashed red line per step, running the full height of the plot, with its value
    # labeled just ABOVE the plot (not sitting on the Event ID axis) — every step
    # gets one, not a sampled few
    trans = ax.get_xaxis_transform()  # x in data coords, y in axes-fraction (0=bottom, 1=top)
    for x, v in zip(boundary_event_ids, boundary_values):
        ax.axvline(x, color="red", linestyle="--", linewidth=0.8, alpha=0.55)
        ax.text(x, 1.02, f"{v:.0f}", transform=trans, color="red",
                ha="center", va="bottom", fontsize=8, rotation=90)
    ax.text(1.005, 1.02, axis_label, transform=ax.transAxes, color="red",
            ha="left", va="bottom", fontsize=10)

    fig.subplots_adjust(top=0.80, right=0.85)
    fig.savefig(output_path, dpi=150)
    print(f"Saved -> {output_path}")


if __name__ == "__main__":
    main()
