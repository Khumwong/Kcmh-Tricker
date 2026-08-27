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
    first_trigger = {}
    first_data_event_id = None
    sync_total_hits = {}
    sync_active_planes = {}
    reassigned_plane_events = 0

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
            if first_data_event_id is None:
                first_data_event_id = event_id

            # ITS3DataCollector groups events by queue position, not by trigger or
            # timestamp.  Preserve each producer's metadata so a skipped frame in
            # one producer does not permanently shift that plane in all later
            # collector packets.
            subevent_meta = {}
            for subev in ev.GetSubEvents():
                device_id = int(subev.GetDeviceN())
                trigger = int(subev.GetTriggerN())
                first_trigger.setdefault(device_id, trigger)
                subevent_meta[device_id] = trigger

            stdev = pyeudaq.StandardEvent()
            pyeudaq.StdEventConverter.Convert(ev, stdev, None)

            num_planes = stdev.NumPlanes()
            total_hits_this_event = 0
            active_planes_this_event = 0

            for i in range(num_planes):
                plane = stdev.GetPlane(i)
                plane_id = int(plane.ID())
                nhits = int(plane.HitPixels())

                plane_event_id = event_id
                if plane_id in subevent_meta:
                    trigger = subevent_meta[plane_id]
                    plane_event_id = first_data_event_id + trigger - first_trigger[plane_id]
                if plane_event_id != event_id:
                    reassigned_plane_events += 1

                if plane_id > max_plane_id:
                    max_plane_id = plane_id

                if plane_id not in plane_hit_sums:
                    plane_hit_sums[plane_id] = 0
                    plane_event_ids[plane_id] = []
                    plane_event_nhits[plane_id] = []
                    plane_x_chunks[plane_id] = []
                    plane_y_chunks[plane_id] = []

                plane_hit_sums[plane_id] += nhits
                plane_event_ids[plane_id].append(plane_event_id)
                plane_event_nhits[plane_id].append(nhits)

                sync_total_hits[plane_event_id] = sync_total_hits.get(plane_event_id, 0) + nhits
                if nhits > 0:
                    sync_active_planes.setdefault(plane_event_id, set()).add(plane_id)

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

            n_events += 1

            if n_events % 10000 == 0:
                print(f"Processed {n_events} events...", end="\r")

    print()

    if n_events == 0:
        raise RuntimeError("No data events found in the raw file.")
    if max_plane_id < 0:
        raise RuntimeError("No valid planes found.")

    # Rebuild global per-event quantities after plane reassignment.
    event_ids = np.asarray(sorted(sync_total_hits), dtype=np.int64)
    event_total_hits = np.asarray(
        [sync_total_hits[eid] for eid in event_ids], dtype=np.int64
    )
    event_nplanes = np.asarray(
        [len(sync_active_planes.get(eid, ())) for eid in event_ids], dtype=np.int64
    )

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
        "reassigned_plane_events": reassigned_plane_events,
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
        "reassigned_plane_events": collected["reassigned_plane_events"],
    }

    return monitor_histograms, plane_monitor_histograms, alpide_histograms, summary


def save_histograms_to_root(output_root_path, monitor_histograms, plane_monitor_histograms, alpide_histograms, max_plane_id):
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
    print("Synchronization   : trigger")
    print(f"Plane entries moved: {summary['reassigned_plane_events']}")

    print("\nTotal hits per plane")
    for plane_id in range(summary["max_plane_id"] + 1):
        print(f"  Plane {plane_id}: {summary['plane_hit_sums'][plane_id]}")

    save_histograms_to_root(
        output_root_path,
        monitor_histograms,
        plane_monitor_histograms,
        alpide_histograms,
        summary["max_plane_id"]
    )

    print("\nMemory usage")
    print("-" * 80)
    print(f"Peak resident memory: {get_memory_usage_mb():.2f} MB")

    print("\nDone.")
    print(f"ROOT file written to: {output_root_path}")


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)
    main()
