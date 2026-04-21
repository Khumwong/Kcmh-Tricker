#!/usr/bin/env python3
"""
Wrapper: runs StdEventMonitor_fast.py and logs per-job CPU/RAM/IO stats every 0.5 s.
Tracks only THIS job's process tree (main + mp.Pool workers), not the whole server.
All output goes to stdout so it ends up in _std.log.
Usage: run_with_stats.py <raw_file> -o <root_file>
"""

import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime

import psutil

STATS_INTERVAL = 0.5  # seconds — short enough to catch mp.Pool workers


def _gpu_stats():
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            util, mem_used, mem_total, temp = [x.strip() for x in r.stdout.strip().split(",")]
            return f"util={util}%  mem={mem_used}/{mem_total} MiB  temp={temp}°C"
    except Exception:
        pass
    return "N/A"


def _collect_job(main_proc):
    """รวม CPU% และ RSS ของ process หลัก + mp.Pool children ทั้งหมด"""
    job_cpu = 0.0
    job_rss = 0
    n_workers = 0
    try:
        procs = [main_proc] + main_proc.children(recursive=True)
        for p in procs:
            try:
                job_cpu += p.cpu_percent()
                job_rss += p.memory_info().rss
                if p.pid != main_proc.pid:
                    n_workers += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return job_cpu, job_rss / 1024 / 1024, n_workers


def _collect_job_io(main_proc):
    """รวม disk read/write bytes ของ process tree"""
    read_b = write_b = 0
    try:
        procs = [main_proc] + main_proc.children(recursive=True)
        for p in procs:
            try:
                io = p.io_counters()
                read_b  += io.read_bytes
                write_b += io.write_bytes
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return read_b, write_b


def _stats_loop(stop_event, main_proc, last_stats):
    total_cores = psutil.cpu_count(logical=True)
    # warm-up — first cpu_percent call always returns 0
    try:
        main_proc.cpu_percent()
        for c in main_proc.children(recursive=True):
            try: c.cpu_percent()
            except Exception: pass
    except Exception:
        pass

    io_start_r, io_start_w = _collect_job_io(main_proc)
    peak_cpu = 0.0
    peak_ram = 0.0
    peak_workers = 0

    while not stop_event.is_set():
        job_cpu, job_rss_mb, n_workers = _collect_job(main_proc)
        job_cores = job_cpu / 100.0
        io_r, io_w = _collect_job_io(main_proc)
        disk_r = (io_r - io_start_r) / 1024 / 1024
        disk_w = (io_w - io_start_w) / 1024 / 1024
        gpu = _gpu_stats()

        peak_cpu     = max(peak_cpu, job_cpu)
        peak_ram     = max(peak_ram, job_rss_mb)
        peak_workers = max(peak_workers, n_workers)

        line = (
            f"[STATS]  job_cpu={job_cpu:.1f}%  job_cores≈{job_cores:.1f}"
            f"  workers={n_workers}  job_ram={job_rss_mb:.0f} MiB"
            f"  disk_read={disk_r:.1f} MiB  disk_write={disk_w:.1f} MiB"
            f"  GPU {gpu}"
        )
        print(line, flush=True)
        last_stats['cpu']          = job_cpu
        last_stats['cores']        = job_cores
        last_stats['ram_mb']       = job_rss_mb
        last_stats['workers']      = n_workers
        last_stats['disk_r_mb']    = disk_r
        last_stats['disk_w_mb']    = disk_w
        last_stats['total_cores']  = total_cores
        last_stats['io_r']         = io_r
        last_stats['io_w']         = io_w
        last_stats['peak_cpu']     = peak_cpu
        last_stats['peak_ram_mb']  = peak_ram
        last_stats['peak_workers'] = peak_workers
        stop_event.wait(STATS_INTERVAL)


def _root_file_size(argv):
    """Parse -o <path> from argv and return file size string, or ''."""
    try:
        idx = argv.index('-o')
        path = argv[idx + 1]
        size_mb = os.path.getsize(path) / 1024 / 1024
        return f"  Root size   : {size_mb:.1f} MiB  ({path})\n"
    except (ValueError, IndexError, OSError):
        return ""


def main():
    script_dir     = os.path.dirname(os.path.abspath(__file__))
    monitor_script = os.path.join(script_dir, "StdEventMonitor_fast.py")
    cmd = [sys.executable, monitor_script] + sys.argv[1:]

    t_start     = time.monotonic()
    t_start_abs = datetime.now()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    main_proc = psutil.Process(proc.pid)

    last_stats = {}
    stop_event   = threading.Event()
    stats_thread = threading.Thread(
        target=_stats_loop, args=(stop_event, main_proc, last_stats), daemon=True
    )
    stats_thread.start()

    for line in proc.stdout:
        print(line, end="", flush=True)
    proc.wait()
    elapsed   = time.monotonic() - t_start
    t_end_abs = datetime.now()

    stop_event.set()
    stats_thread.join(timeout=2)

    gpu          = _gpu_stats()
    m, s         = divmod(elapsed, 60)
    cores        = last_stats.get('cores', 0)
    total        = last_stats.get('total_cores', psutil.cpu_count(logical=True))
    peak_cpu     = last_stats.get('peak_cpu', 0)
    peak_cores   = peak_cpu / 100.0
    peak_ram     = last_stats.get('peak_ram_mb', 0)
    peak_workers = last_stats.get('peak_workers', 0)
    root_size    = _root_file_size(sys.argv)
    raw_file     = sys.argv[1] if len(sys.argv) > 1 else "?"
    hostname     = socket.gethostname()
    exit_code    = proc.returncode
    print(
        f"\n--- Run Stats ---\n"
        f"  Host        : {hostname}\n"
        f"  Input       : {raw_file}\n"
        f"  Start       : {t_start_abs.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"  End         : {t_end_abs.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"  Elapsed     : {int(m):02d}:{s:05.2f}\n"
        f"  Exit code   : {exit_code}\n"
        f"  Job CPU     : {last_stats.get('cpu', 0):.1f}%  (≈{cores:.1f}/{total} cores)\n"
        f"  Peak CPU    : {peak_cpu:.1f}%  (≈{peak_cores:.1f} cores)  peak workers={peak_workers}\n"
        f"  Job RAM     : {last_stats.get('ram_mb', 0):.0f} MiB  (peak {peak_ram:.0f} MiB)\n"
        f"  Disk read   : {last_stats.get('disk_r_mb', 0):.1f} MiB  (0 = served from OS cache)\n"
        f"  Disk write  : {last_stats.get('disk_w_mb', 0):.1f} MiB\n"
        + root_size +
        f"  GPU         : {gpu}\n"
        f"-----------------",
        flush=True,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
