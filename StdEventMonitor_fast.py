#!/usr/bin/env python3

import os
os.environ["EUDAQ_LOG_LEVEL"] = "ERROR"

import sys
sys.path.insert(0, "/home/sutpct/eudaq2/lib")

import warnings
import argparse
import contextlib
import resource
import multiprocessing as mp

import numpy as np
import uproot
import boost_histogram as bh

warnings.filterwarnings("ignore", category=FutureWarning)

import pyeudaq


ALPIDE_NX = 1024
ALPIDE_NY = 512
N_PLANES_DEFAULT = 6


@contextlib.contextmanager
def suppress_c_output(suppress_stdout=True, suppress_stderr=True):
    devnull_fd = os.open(os.devnull, os.O_WRONLY)

    saved_stdout_fd = None
    saved_stderr_fd = None

    try:
        if suppress_stdout:
            saved_stdout_fd = os.dup(1)
            os.dup2(devnull_fd, 1)

        if suppress_stderr:
            saved_stderr_fd = os.dup(2)
            os.dup2(devnull_fd, 2)

        yield

    finally:
        if saved_stdout_fd is not None:
            os.dup2(saved_stdout_fd, 1)
            os.close(saved_stdout_fd)

        if saved_stderr_fd is not None:
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stderr_fd)

        os.close(devnull_fd)


def default_output_path(raw_file_path):
    base, ext = os.path.splitext(raw_file_path)
    if ext.lower() == ".raw":
        return base + ".root"
    return raw_file_path + ".root"


def get_memory_usage_mb():
    mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return mem / (1024.0 * 1024.0)
    return mem / 1024.0


def make_th1_from_counts(counts, xmin, xmax, xlabel):
    h = bh.Histogram(
        bh.axis.Regular(len(counts), xmin, xmax, metadata=xlabel),
        storage=bh.storage.Double()
    )
    h.axes[0].label = xlabel
    h.view()[:] = counts.astype(np.float64)
    return h


def load_zaber_csv(path):
    """Parse the Zaber position sidecar CSV written by the control GUI.

    Format:
        # run_start_epoch=<float>
        # run_stop_epoch=<float>
        epoch,step_index,x_mm,y_mm,r_deg
        <epoch>,<step_index>,<x>,<y>,<r>
        ...
    Returns (run_start_epoch, run_stop_epoch, rows) where rows is a list of
    (epoch, step_index, x, y, r) tuples sorted by epoch.
    """
    run_start_epoch = None
    run_stop_epoch = None
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
                continue
            if line.startswith("epoch,"):
                continue
            epoch_s, step_s, x_s, y_s, r_s = line.split(",")
            rows.append((float(epoch_s), int(step_s), float(x_s), float(y_s), float(r_s)))
    rows.sort(key=lambda row: row[0])
    if run_start_epoch is None and rows:
        run_start_epoch = rows[0][0]
    if run_stop_epoch is None and rows:
        run_stop_epoch = rows[-1][0]
    return run_start_epoch, run_stop_epoch, rows


def build_event_step_index(min_event_id, max_event_id, run_start_epoch, run_stop_epoch, rows):
    """Map every event ID in [min_event_id, max_event_id] to a Zaber step index.

    EUDAQ triggers fire at a fixed rate (not conditioned on beam hits), so each
    event's wall-clock time is estimated by linear interpolation across the run
    duration, then matched to whichever step window was active at that time.
    """
    n = max_event_id - min_event_id + 1
    offsets = np.arange(n, dtype=np.float64)
    if run_stop_epoch > run_start_epoch and n > 1:
        event_epochs = run_start_epoch + offsets / (n - 1) * (run_stop_epoch - run_start_epoch)
    else:
        event_epochs = np.full(n, run_start_epoch, dtype=np.float64)

    step_starts = np.asarray([row[0] for row in rows], dtype=np.float64)
    step_indices = np.asarray([row[1] for row in rows], dtype=np.int64)

    idx_into_rows = np.searchsorted(step_starts, event_epochs, side="right") - 1
    idx_into_rows = np.clip(idx_into_rows, 0, len(rows) - 1)
    return step_indices[idx_into_rows]


def detect_varying_zaber_axes(rows, eps=1e-6):
    """Which of X/Y/R actually moved during the run (most runs scan one axis at a time)."""
    axes = []
    for key, label, col in (("x", "Zaber X (mm)", 2), ("y", "Zaber Y (mm)", 3), ("r", "Zaber R (deg)", 4)):
        vals = np.asarray([row[col] for row in rows], dtype=np.float64)
        if vals.max() - vals.min() > eps:
            axes.append((key, label, vals))
    return axes


def variable_bin_edges(values):
    """Bin edges centered on each distinct commanded position, spaced by the real (possibly uneven) step gaps."""
    vals = np.unique(np.asarray(values, dtype=np.float64))
    if len(vals) == 1:
        v = vals[0]
        return np.array([v - 0.5, v + 0.5])
    mids = (vals[:-1] + vals[1:]) / 2.0
    first_half = (vals[1] - vals[0]) / 2.0
    last_half = (vals[-1] - vals[-2]) / 2.0
    return np.concatenate(([vals[0] - first_half], mids, [vals[-1] + last_half]))


def build_zaber_step_histograms(collected, min_event_id, max_event_id, max_plane_id, zaber_csv_path):
    run_start_epoch, run_stop_epoch, rows = load_zaber_csv(zaber_csv_path)
    if not rows:
        return None

    n_steps = max(row[1] for row in rows) + 1
    step_index_by_offset = build_event_step_index(
        min_event_id, max_event_id, run_start_epoch, run_stop_epoch, rows
    )

    event_ids = collected["event_ids"]
    event_total_hits = collected["event_total_hits"]

    varying_axes = detect_varying_zaber_axes(rows)
    position_axes = []
    for axis_key, axis_label, _ in varying_axes:
        col = {"x": 2, "y": 3, "r": 4}[axis_key]
        step_value = np.zeros(n_steps, dtype=np.float64)
        for row in rows:
            step_value[row[1]] = row[col]
        edges = variable_bin_edges(step_value)
        name_suffix = "" if len(varying_axes) == 1 else f" ({axis_key.upper()})"

        def _new_hist(edges=edges, axis_label=axis_label):
            h = bh.Histogram(
                bh.axis.Variable(edges, metadata=axis_label),
                bh.axis.Regular(
                    max_event_id - min_event_id + 1, min_event_id - 0.5, max_event_id + 0.5,
                    metadata="Event ID"
                ),
                storage=bh.storage.Weight()
            )
            h.axes[0].label = axis_label
            h.axes[1].label = "Event ID"
            return h

        def _new_hist_1d(edges=edges, axis_label=axis_label):
            h = bh.Histogram(bh.axis.Variable(edges, metadata=axis_label), storage=bh.storage.Weight())
            h.axes[0].label = axis_label
            return h

        h_global = _new_hist()
        event_axis_value = step_value[step_index_by_offset[event_ids - min_event_id]]
        h_global.fill(event_axis_value, event_ids, weight=event_total_hits)

        h_global_1d = _new_hist_1d()
        h_global_1d.fill(event_axis_value, weight=event_total_hits)

        plane_hists = {}
        plane_hists_1d = {}
        for plane_id in range(max_plane_id + 1):
            ev_ids = np.asarray(collected["plane_event_ids"].get(plane_id, []), dtype=np.int64)
            nhits = np.asarray(collected["plane_event_nhits"].get(plane_id, []), dtype=np.float64)
            h = _new_hist()
            h1d = _new_hist_1d()
            if len(ev_ids) > 0:
                axis_value = step_value[step_index_by_offset[ev_ids - min_event_id]]
                h.fill(axis_value, ev_ids, weight=nhits)
                h1d.fill(axis_value, weight=nhits)
            plane_hists[plane_id] = h
            plane_hists_1d[plane_id] = h1d

        position_axes.append({
            "name_suffix": name_suffix,
            "hits_vs_event": h_global,
            "plane_hits": plane_hists,
            "hits_vs_position": h_global_1d,
            "plane_hits_vs_position": plane_hists_1d,
        })

    h_x = bh.Histogram(bh.axis.Regular(n_steps, -0.5, n_steps - 0.5, metadata="Zaber Step"))
    h_y = bh.Histogram(bh.axis.Regular(n_steps, -0.5, n_steps - 0.5, metadata="Zaber Step"))
    h_r = bh.Histogram(bh.axis.Regular(n_steps, -0.5, n_steps - 0.5, metadata="Zaber Step"))
    h_x.axes[0].label = h_y.axes[0].label = h_r.axes[0].label = "Zaber Step"
    for _, step_index, x, y, r in rows:
        h_x.view()[step_index] = x
        h_y.view()[step_index] = y
        h_r.view()[step_index] = r

    return {
        "position_axes": position_axes,
        "zaber_x_per_step": h_x,
        "zaber_y_per_step": h_y,
        "zaber_r_per_step": h_r,
    }


def make_th2_from_counts(counts2d, xlabel, ylabel):
    h = bh.Histogram(
        bh.axis.Regular(counts2d.shape[0], -0.5, counts2d.shape[0] - 0.5, metadata="X"),
        bh.axis.Regular(counts2d.shape[1], -0.5, counts2d.shape[1] - 0.5, metadata="Y"),
        storage=bh.storage.Double()
    )
    h.axes[0].label = xlabel
    h.axes[1].label = ylabel
    h.view()[:, :] = counts2d.astype(np.float64)
    return h


def process_plane_worker(task):
    plane_id, xvals, yvals = task

    raw_counts = np.zeros((ALPIDE_NX, ALPIDE_NY), dtype=np.uint32)

    if len(xvals) > 0:
        np.add.at(raw_counts, (xvals, yvals), 1)
        xproj = np.bincount(xvals, minlength=ALPIDE_NX).astype(np.uint32)
        yproj = np.bincount(yvals, minlength=ALPIDE_NY).astype(np.uint32)
    else:
        xproj = np.zeros(ALPIDE_NX, dtype=np.uint32)
        yproj = np.zeros(ALPIDE_NY, dtype=np.uint32)

    return {
        "plane_id": plane_id,
        "raw_counts": raw_counts,
        "xproj": xproj,
        "yproj": yproj,
        "max_bin": int(raw_counts.max()) if raw_counts.size > 0 else 0,
        "total_hits": int(len(xvals)),
    }


def read_raw_collect_arrays(raw_file_path, n_planes_hint=N_PLANES_DEFAULT):
    event_ids = []
    event_total_hits = []
    event_nplanes = []

    plane_hit_sums = {pid: 0 for pid in range(n_planes_hint)}
    plane_event_ids = {pid: [] for pid in range(n_planes_hint)}
    plane_event_nhits = {pid: [] for pid in range(n_planes_hint)}

    plane_x_chunks = {pid: [] for pid in range(n_planes_hint)}
    plane_y_chunks = {pid: [] for pid in range(n_planes_hint)}

    max_plane_id = -1
    run_number = None
    n_events = 0
    n_bore = 0
    n_eore = 0

    with suppress_c_output(suppress_stdout=True, suppress_stderr=True):
        reader = pyeudaq.FileReader("native", raw_file_path)

        while True:
            ev = reader.GetNextEvent()
            if not ev:
                break

            if ev.IsBORE():
                n_bore += 1
                continue

            if ev.IsEORE():
                n_eore += 1
                continue

            if run_number is None:
                run_number = ev.GetRunN()

            event_id = int(ev.GetEventN())

            stdev = pyeudaq.StandardEvent()
            pyeudaq.StdEventConverter.Convert(ev, stdev, None)

            num_planes = stdev.NumPlanes()
            total_hits_this_event = 0
            active_planes_this_event = 0

            for i in range(num_planes):
                plane = stdev.GetPlane(i)
                plane_id = int(plane.ID())
                nhits = int(plane.HitPixels())

                if plane_id > max_plane_id:
                    max_plane_id = plane_id

                if plane_id not in plane_hit_sums:
                    plane_hit_sums[plane_id] = 0
                    plane_event_ids[plane_id] = []
                    plane_event_nhits[plane_id] = []
                    plane_x_chunks[plane_id] = []
                    plane_y_chunks[plane_id] = []

                plane_hit_sums[plane_id] += nhits
                plane_event_ids[plane_id].append(event_id)
                plane_event_nhits[plane_id].append(nhits)

                total_hits_this_event += nhits

                if nhits > 0:
                    active_planes_this_event += 1

                    xvals = np.fromiter(
                        (plane.GetX(ihit) for ihit in range(nhits)),
                        dtype=np.int32,
                        count=nhits
                    )
                    yvals = np.fromiter(
                        (plane.GetY(ihit) for ihit in range(nhits)),
                        dtype=np.int32,
                        count=nhits
                    )

                    plane_x_chunks[plane_id].append(xvals)
                    plane_y_chunks[plane_id].append(yvals)

            event_ids.append(event_id)
            event_total_hits.append(total_hits_this_event)
            event_nplanes.append(active_planes_this_event)
            n_events += 1

            if n_events % 10000 == 0:
                print(f"Processed {n_events} events...", end="\r")

    print()

    if n_events == 0:
        raise RuntimeError("No data events found in the raw file.")
    if max_plane_id < 0:
        raise RuntimeError("No valid planes found.")

    event_ids = np.asarray(event_ids, dtype=np.int64)
    event_total_hits = np.asarray(event_total_hits, dtype=np.int64)
    event_nplanes = np.asarray(event_nplanes, dtype=np.int64)

    plane_xy = {}
    for plane_id in range(max_plane_id + 1):
        xchunks = plane_x_chunks.get(plane_id, [])
        ychunks = plane_y_chunks.get(plane_id, [])
        if len(xchunks) > 0:
            plane_xy[plane_id] = (
                np.concatenate(xchunks).astype(np.int32, copy=False),
                np.concatenate(ychunks).astype(np.int32, copy=False),
            )
        else:
            plane_xy[plane_id] = (
                np.empty(0, dtype=np.int32),
                np.empty(0, dtype=np.int32),
            )

    return {
        "run_number": run_number,
        "n_events": n_events,
        "n_bore": n_bore,
        "n_eore": n_eore,
        "max_plane_id": max_plane_id,
        "event_ids": event_ids,
        "event_total_hits": event_total_hits,
        "event_nplanes": event_nplanes,
        "plane_hit_sums": plane_hit_sums,
        "plane_event_ids": plane_event_ids,
        "plane_event_nhits": plane_event_nhits,
        "plane_xy": plane_xy,
    }


def build_histograms_parallel(collected, n_workers=None):
    event_ids = collected["event_ids"]
    event_total_hits = collected["event_total_hits"]
    event_nplanes = collected["event_nplanes"]
    max_plane_id = collected["max_plane_id"]

    min_event_id = int(event_ids.min())
    max_event_id = int(event_ids.max())
    max_nplanes = int(event_nplanes.max())

    monitor_histograms = {}

    h_number_of_planes = bh.Histogram(
        bh.axis.Regular(max_nplanes + 1, -0.5, max_nplanes + 0.5, metadata="Active Planes")
    )
    h_number_of_planes.axes[0].label = "Active Planes"
    h_number_of_planes.fill(event_nplanes)
    monitor_histograms["Number of Planes"] = h_number_of_planes

    h_hits_vs_event = bh.Histogram(
        bh.axis.Regular(
            max_event_id - min_event_id + 1,
            min_event_id - 0.5,
            max_event_id + 0.5,
            metadata="Event ID"
        ),
        storage=bh.storage.Weight()
    )
    h_hits_vs_event.axes[0].label = "Event ID"
    h_hits_vs_event.fill(event_ids, weight=event_total_hits)
    monitor_histograms["Hits vs Event"] = h_hits_vs_event

    h_hits_vs_plane = bh.Histogram(
        bh.axis.Regular(max_plane_id + 1, -0.5, max_plane_id + 0.5, metadata="Plane ID"),
        storage=bh.storage.Weight()
    )
    h_hits_vs_plane.axes[0].label = "Plane ID"
    for plane_id in range(max_plane_id + 1):
        h_hits_vs_plane.fill(plane_id, weight=collected["plane_hit_sums"].get(plane_id, 0))
    monitor_histograms["Hits vs Plane"] = h_hits_vs_plane

    plane_monitor_histograms = {}
    for plane_id in range(max_plane_id + 1):
        h = bh.Histogram(
            bh.axis.Regular(
                max_event_id - min_event_id + 1,
                min_event_id - 0.5,
                max_event_id + 0.5,
                metadata="Event ID"
            ),
            storage=bh.storage.Weight()
        )
        h.axes[0].label = "Event ID"

        ev_ids = collected["plane_event_ids"].get(plane_id, [])
        nhits = collected["plane_event_nhits"].get(plane_id, [])
        if len(ev_ids) > 0:
            h.fill(
                np.asarray(ev_ids, dtype=np.int64),
                weight=np.asarray(nhits, dtype=np.float64)
            )
        plane_monitor_histograms[plane_id] = h

    tasks = []
    for plane_id in range(max_plane_id + 1):
        xvals, yvals = collected["plane_xy"][plane_id]
        tasks.append((plane_id, xvals, yvals))

    if n_workers is None:
        n_workers = min(max_plane_id + 1, os.cpu_count() or 1)
    n_workers = max(1, min(n_workers, max_plane_id + 1))

    if n_workers == 1:
        results = [process_plane_worker(task) for task in tasks]
    else:
        with mp.Pool(processes=n_workers) as pool:
            results = pool.map(process_plane_worker, tasks)

    alpide_histograms = {}

    print("\nALPIDE RawHitmap diagnostics")
    print("-" * 80)

    for res in sorted(results, key=lambda d: d["plane_id"]):
        plane_id = res["plane_id"]

        h_raw = make_th2_from_counts(res["raw_counts"], "X Pixel", "Y Pixel")
        h_x = make_th1_from_counts(res["xproj"], -0.5, ALPIDE_NX - 0.5, "X Pixel")
        h_y = make_th1_from_counts(res["yproj"], -0.5, ALPIDE_NY - 0.5, "Y Pixel")

        alpide_histograms[plane_id] = {
            "RawHitmap": h_raw,
            "Hitmap X Projection": h_x,
            "Hitmap Y Projection": h_y,
        }

        print(
            f"  ALPIDE {plane_id}: "
            f"total hits = {res['total_hits']}, "
            f"max RawHitmap bin = {res['max_bin']}"
        )

    summary = {
        "run_number": collected["run_number"],
        "n_events": collected["n_events"],
        "n_bore": collected["n_bore"],
        "n_eore": collected["n_eore"],
        "min_event_id": min_event_id,
        "max_event_id": max_event_id,
        "max_plane_id": max_plane_id,
        "max_hits_event": int(event_total_hits.max()),
        "max_nplanes": max_nplanes,
        "plane_hit_sums": {
            pid: collected["plane_hit_sums"].get(pid, 0)
            for pid in range(max_plane_id + 1)
        },
    }

    return monitor_histograms, plane_monitor_histograms, alpide_histograms, summary


def save_histograms_to_root(output_root_path, monitor_histograms, plane_monitor_histograms, alpide_histograms,
                             max_plane_id, zaber_histograms=None):
    with uproot.recreate(output_root_path) as root_file:
        root_file["EUDAQ Monitor/Number of Planes"] = monitor_histograms["Number of Planes"]
        root_file["EUDAQ Monitor/Hits vs Event"] = monitor_histograms["Hits vs Event"]
        root_file["EUDAQ Monitor/Hits vs Plane"] = monitor_histograms["Hits vs Plane"]

        for plane_id in range(max_plane_id + 1):
            root_file[f"EUDAQ Monitor/Planes/Hits Sensor Plane {plane_id}"] = plane_monitor_histograms[plane_id]

        for plane_id in range(max_plane_id + 1):
            root_file[f"ALPIDE/Sensor {plane_id}/RawHitmap"] = alpide_histograms[plane_id]["RawHitmap"]
            root_file[f"ALPIDE/Sensor {plane_id}/Hitmap X Projection"] = alpide_histograms[plane_id]["Hitmap X Projection"]
            root_file[f"ALPIDE/Sensor {plane_id}/Hitmap Y Projection"] = alpide_histograms[plane_id]["Hitmap Y Projection"]

        if zaber_histograms is not None:
            root_file["EUDAQ Monitor/Zaber X per Step (mm)"] = zaber_histograms["zaber_x_per_step"]
            root_file["EUDAQ Monitor/Zaber Y per Step (mm)"] = zaber_histograms["zaber_y_per_step"]
            root_file["EUDAQ Monitor/Zaber R per Step (deg)"] = zaber_histograms["zaber_r_per_step"]
            for entry in zaber_histograms["position_axes"]:
                suffix = entry["name_suffix"]
                root_file[f"EUDAQ Monitor/Hits vs Event with Zaber Position{suffix}"] = entry["hits_vs_event"]
                root_file[f"EUDAQ Monitor/Hits vs Zaber Position{suffix}"] = entry["hits_vs_position"]
                for plane_id in range(max_plane_id + 1):
                    root_file[f"EUDAQ Monitor/Planes/Hits Sensor Plane {plane_id} with Zaber Position{suffix}"] = \
                        entry["plane_hits"][plane_id]
                    root_file[f"EUDAQ Monitor/Planes/Hits Sensor Plane {plane_id} vs Zaber Position{suffix}"] = \
                        entry["plane_hits_vs_position"][plane_id]


def main():
    parser = argparse.ArgumentParser(
        description="Read one EUDAQ raw file, then build ALPIDE histograms in parallel by plane."
    )
    parser.add_argument("raw_file", help="Input .raw file")
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output ROOT file (default: same as input, but .raw -> .root)"
    )
    parser.add_argument(
        "--nplanes",
        type=int,
        default=N_PLANES_DEFAULT,
        help=f"Initial number of planes to prepare (default: {N_PLANES_DEFAULT})"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes for ALPIDE histogram building (default: min(nplanes, cpu_count))"
    )
    parser.add_argument(
        "--zaber-csv",
        default=None,
        help="Optional Zaber position sidecar CSV (epoch,step_index,x_mm,y_mm,r_deg) — "
             "adds 'Hits vs Event with Zaber Position' histograms"
    )
    args = parser.parse_args()

    raw_file_path = args.raw_file
    output_root_path = args.output if args.output is not None else default_output_path(raw_file_path)

    if not os.path.isfile(raw_file_path):
        raise FileNotFoundError(f"Input file not found: {raw_file_path}")

    print("=" * 80)
    print("Read raw once, build ALPIDE histograms in parallel by plane")
    print("=" * 80)
    print(f"Input   : {raw_file_path}")
    print(f"Output  : {output_root_path}")
    print(f"Planes  : {args.nplanes}")
    print(f"Workers : {args.workers if args.workers is not None else 'auto'}")
    print("=" * 80)

    collected = read_raw_collect_arrays(raw_file_path, n_planes_hint=args.nplanes)

    print("\nAfter raw read")
    print("-" * 80)
    print(f"Peak resident memory so far: {get_memory_usage_mb():.2f} MB")

    monitor_histograms, plane_monitor_histograms, alpide_histograms, summary = \
        build_histograms_parallel(collected, n_workers=args.workers)

    print("\nSummary")
    print("-" * 80)
    print(f"Run number        : {summary['run_number']}")
    print(f"Data events       : {summary['n_events']}")
    print(f"BORE skipped      : {summary['n_bore']}")
    print(f"EORE skipped      : {summary['n_eore']}")
    print(f"Event ID range    : {summary['min_event_id']} -> {summary['max_event_id']}")
    print(f"Max plane ID      : {summary['max_plane_id']}")
    print(f"Max hits / event  : {summary['max_hits_event']}")
    print(f"Max active planes : {summary['max_nplanes']}")

    print("\nTotal hits per plane")
    for plane_id in range(summary["max_plane_id"] + 1):
        print(f"  Plane {plane_id}: {summary['plane_hit_sums'][plane_id]}")

    zaber_histograms = None
    if args.zaber_csv:
        if os.path.isfile(args.zaber_csv):
            print(f"\nZaber position CSV: {args.zaber_csv}")
            zaber_histograms = build_zaber_step_histograms(
                collected, summary["min_event_id"], summary["max_event_id"],
                summary["max_plane_id"], args.zaber_csv
            )
            if zaber_histograms is None:
                print("  no rows found — skipping Zaber histograms")
        else:
            print(f"\nZaber CSV not found, skipping: {args.zaber_csv}")

    save_histograms_to_root(
        output_root_path,
        monitor_histograms,
        plane_monitor_histograms,
        alpide_histograms,
        summary["max_plane_id"],
        zaber_histograms=zaber_histograms
    )

    print("\nMemory usage")
    print("-" * 80)
    print(f"Peak resident memory: {get_memory_usage_mb():.2f} MB")

    print("\nDone.")
    print(f"ROOT file written to: {output_root_path}")


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)
    main()