# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A PyQt5 desktop GUI application for controlling a particle beam test setup at KCMH. It coordinates three hardware subsystems:
- **FPGA** (connected via DB-9 serial/USB): sends trigger/beam control bytes
- **Zaber motorized stages** (X/Y/Rotation, connected via USB serial): positions a phantom target
- **ALPIDE pixel sensors** (connected via USB): 6 DAQ boards running EUDAQ2 data acquisition

The application manages run configuration, fires EUDAQ2 (headless via tmux), steps Zaber stages between loops, rsync's raw data to a remote server, and triggers a remote ROOT conversion job.

## Running the Application

```bash
# Real hardware mode (kills any existing ITS3 tmux session on start/exit)
python3 main.py

# Simulation mode — no hardware required, patches all hardware modules
python3 main.py --sim

# Via generated launcher (after running install.sh)
./launch_app.sh
./launch_app.sh --sim
```

## Installation

```bash
bash install.sh
```

Installs Python dependencies (`PyQt5`, `zaber-motion`, `pyserial`, `pyusb`), apt packages (`sshpass`, `tmux`), and creates desktop launchers and `launch_app.sh` (both gitignored — machine-specific absolute paths).

The end-user operating manual is `docs/MANUAL.txt`.

## Data Processing Scripts

All scripts that run **on the remote server** live in `remote_scripts/`. On rsync connect, `RsyncManager` ships every `*.py`, `*.md`, `*.cpp` and `*.sh` in that folder to `<remote_path>/scripts/` — so adding a new server-side script means dropping it in `remote_scripts/`, nothing else. `remote_scripts/README.md` documents every script's CLI and ships with them.

```bash
# Convert a raw EUDAQ file to ROOT, with per-job CPU/RAM/disk/GPU stats to stdout
python3 remote_scripts/run_with_stats.py <raw_file> -o <output.root>
```

**raw → ROOT: two monitors, one wrapper.**
- `StdEventMonitor_faster.cpp` is the primary converter — a C++ port of the Python monitor (same single-pass read + trigger-sync event reassignment), linked against ROOT + EUDAQ, writing native ROOT objects. Its output is a **superset** of the Python one: same histograms plus `EUDAQ Monitor/Hits vs TimeStamp` (10 ms bins) and an `Alignment/` dir (per-sensor Gaussian fits, beam center vs Z, linear fit, beam offset/angle at the collimator). Geometry constants (`kFirstSensorZmm=112`, spacing 25 mm, pitch, collimator z=−60 mm) are hardcoded — verify against the real KCMH setup or the `Alignment/` plots are meaningless (other histograms unaffected). Compile flag `STDEVENTMONITOR_EUDAQ_COMPATIBLE` switches to collector-EventN + TProfile mode; **default build = trigger-sync = matches the Python monitor.**
- `build_monitor.sh` compiles it server-side (needs C++17 + ROOT + an EUDAQ2 build). Auto-probes `EUDAQ_PREFIX` (default `/home/sutpct/eudaq2`); override with `EUDAQ_INC` / `EUDAQ_LIB` / `ROOT_CONFIG` / `CXX`, or `MONITOR_BUILD_CMD` for a verbatim compile line. **Two-ROOT gotcha:** the KCMH server has ROOT at both `/usr/lib64/root` and `/home/sutpct/root`; EUDAQ core is linked to the latter. Building against the wrong one loads two `libCore` into the process and its static teardown corrupts the heap (`munmap_chunk … in _dl_fini`, exit 134) *after* the ROOT file is already written. `build_monitor.sh` avoids this by reading `ldd libeudaq_core.so` and building against the ROOT EUDAQ actually uses. Belt-and-suspenders: the `.cpp` calls `std::_Exit()` once the file is closed, skipping global destructors entirely.
- `StdEventMonitor_fast.py` is the fallback — the original Python monitor (`mp.Pool` per plane), still shipped.
- `run_with_stats.py` is the wrapper the UI SSH-triggers after every run. It rebuilds the C++ binary if the source is newer (`build_monitor.sh`), runs it, and **falls back to `StdEventMonitor_fast.py` if the source/toolchain is missing or the build fails** — runs never break. It samples `psutil` metrics for the job's process tree every 0.5 s; the `Monitor :` line in the Run Stats block records which one actually ran.

`check_gating_consistency.py` and `ocr_video.py` are also in `remote_scripts/` and run server-side only.

## Architecture

### Entry Point and Application Startup (`main.py`)
- Checks for `--sim` flag; if set, calls `modules.sim.apply_sim()` before anything else
- Applies a global QSS stylesheet
- In sim mode, also instantiates `ControlRoomWindow` as a secondary window
- On exit (non-sim), opens the FPGA serial port and sends two `\x00` reset bytes

### Main Window (`modules/window.py` → `MyWindow`)
- Connects to all three hardware subsystems at startup via `init_connect_devices()`
- Holds three boolean flags: `_fpga_connect`, `_zaber_connect`, `_alpide_connect`
- Central widget is `RunWidget`
- On ALPIDE DAQs found but unprogrammed: calls `eudaq.install_firmware_auto()` blocking popup
- `running(True/False)` disables/re-enables all UI controls during a run

### Run Widget (`modules/ui/run.py` → `RunWidget`)
The largest module (~4100+ lines). Contains:
- Run parameter form (num ALPIDEs, events, strobe, threshold, energy, MU, loops, step sizes, etc.)
- Phantom positioning card (delegates to `PhWidget`)
- Connection status buttons for FPGA / Zaber / ALPIDE / Camera
- Beam enable/disable via `enable_beam()` — **see critical note below**
- rsync configuration (SSH address + remote path + optional password)
- After a run completes: rsync raw file to remote, then SSH-trigger ROOT conversion via `run_with_stats.py`
- `EmbeddedTerminal`: polls `tmux capture-pane` on a 400 ms QTimer to display ITS3 session output inline
- `_update_firmware_label()`: 2-second QTimer that polls hardware status. **Zaber and Camera checks run in background threads** (`_zaber_checking` / `_camera_checking` flags + `_on_zaber_poll_slot` / `_on_camera_poll_slot`) to avoid blocking the UI. Zaber uses `get_port("zaber")` (USB presence scan only — no serial port open) so it can poll without conflicting with phantom moves or velocity runs. FPGA still checks on main thread (deferred — see Known Deferred Issues).

### Run Progress (`modules/ui/run_progress.py` → `RunProgress`)
- Opened when a run starts; runs acquisition loops in `QThreadPool`
- Each loop: fires EUDAQ (`eudaq.default_run`), waits, stops EUDAQ, steps Zaber, repeats
- Per-loop Zaber step: always `apply_steps_loop_vel` with `_current_move_speeds()` (the Speed fields `_vel_x/y/r_edit`, shared with QA, clamped per axis to `motion.SPEED_FLOOR` … `SPEED_CEIL` = **(2.5, 2.5, 6) … (40, 40, 80)** mm/s·mm/s·°/s). Never a bare max-speed move — every step has a real velocity ≥ the floor. `_zaber_velocities` is always set for Treatment.
- Treatment per-loop gate-open window = `Beam on delay (ms)` + `Exposure time (ms)` + `Beam off delay (ms)` (`_window_ms_per_loop()`). `Beam on delay` is a front pad (gate open before the exposure so the trigger is running when the beam arrives — KCMH turn-on lag ~300 ms); `Beam off delay` a back pad (trigger runs past the exposure so ALPIDE can confirm the beam is gone before `\xEF` closes the gate and the phantom steps — trailing edge is a hard cut with no FPGA-side delay). Both are GUI window timing only, uncapped. **`Beam delay (ms)` is separate** — it is the FPGA `alpide_delay` byte (0–255, one byte, `enable_beam`'s `byte_start_list`), NOT part of the window. QA mode ignores all three.
- `force_stop` module-level flag allows emergency abort

### Phantom Positioning (`modules/ui/phantom.py` → `PhWidget`)
- Jog controls for X/Y/Rotation Zaber axes
- Calls `modules.zaber.motion` functions directly
- `_ph_apply` (Apply / GO TO), `_ph_step` (jog +/-) and `_load_run`'s plan start-position move all pass `_current_move_speeds()` to `motion.apply_move` / `motion.apply_step` — so a move at speed N actually runs at N (Apply is a valid "check the speed before running" step). `_current_move_speeds()` clamps each axis to `[SPEED_FLOOR, SPEED_CEIL]`; a value over the ceiling is capped, under the floor is raised. `set_zaber_max_speeds` paints the `default … · max …` label from those constants.

### Hardware Modules
- `modules/serial_connect.py`: `get_port(device)` — identifies serial ports by USB hardware serial number (`"zaber"` → `AB0NSAIM`, `"fpga"` → `210183B5A8D0`). For FPGA, returns the last port in the list (DB-9 adapter enumeration order) — the FPGA is a dual-interface FT2232 that enumerates as two `/dev/ttyUSB*` nodes (interface .0 and .1) with the same serial `210183B5A8D0`; `get_port` picks the `.1` node. `python3 tools/find_device.py` lists the 6 ALPIDE DAQ indices found; for serial ports run `python3 -c "import serial.tools.list_ports as l; [print(p.device, p.hwid) for p in l.comports()]"`.
- `modules/fpga/connect.py`: `check_connection(port)` — opens/closes port to verify FPGA is present
- `modules/zaber/connect.py`: wraps `zaber_motion.ascii.Connection.open_serial_port()`
- `modules/zaber/motion.py`: all Zaber moves use `asyncio.gather` for parallel X/Y/R movement. Position limits: X ≤ 150 mm, Y ≤ 40 mm, R ≤ 360°. Speed: `SPEED_FLOOR`/`SPEED_CEIL` constants; `apply_move(loc, speeds=None)`, `apply_step(axis, step, speed=None)`, `apply_steps_loop_vel` take per-axis velocity overrides (0/None = no override → device `maxspeed`). `ensure_maxspeed(conn)` pins each axis' `maxspeed` setting to `SPEED_CEIL` (40/40/80) on every Zaber connect (`window.check_zaber`) so the ceiling is deterministic regardless of Zaber Launcher edits / controller resets — actual move speed is still the per-move override. Hardware datasheet max is 53/48/115 (X-LSQ150A / X-VSR40A / X-RSW60A-E03). Homing (`to_home`, the connect-dialog Home button) uses `maxspeed`, so it now runs at the ceiling. `get_max_speeds()` reads the current settings.
- `modules/alpide.py`: detects ALPIDE DAQs by USB VID/PID. Three states: raw (unprogrammed, VID `0x04B4` PID `0x00F3`), programmed (VID `0x1556` PID `0x01B8`), or absent. Six specific DAQ serial numbers are hardcoded.
- `modules/eudaq.py`: generates EUDAQ2 `.ini`/`.conf` files in `EUDAQ_DIR` (`/home/kobdaj/eudaq2/user/ITS3/misc/`), then launches `ITS3start_auto_gen.sh` via `subprocess.Popen`. EUDAQ dir and ALPIDE serial numbers are hardcoded constants. `stop()` sends `T` (terminate) to the RunControl TUI, waits (pumping Qt events so the UI stays live) for it to reach `TERMINATED`, then `kill-session` + `pkill -9` any orphan `ITS3RunControl.py` / `ALPIDEProducer.py` / `ITS3DataCollector.py` — orphans from a previous run hold the ALPIDE USB and hang the next run's DataCollector. **Depends on the local EUDAQ patch — see below.** Raw files are written to `<outpath>/raw/` (created by `gen_its3_conf`) to mirror the remote server layout; `get_new_outfile()` in `run.py` scans that subdir. Recorded MU videos go to `<outpath>/video/` (`video_window.py` `_start_recording`) and the local copy of each run log to `<outpath>/log/` — all mirroring the server's `raw/ video/ log/` layout.

### Simulation Mode (`modules/sim.py`)
- `apply_sim()` monkey-patches every hardware module at runtime (serial port detection, FPGA, Zaber, ALPIDE, EUDAQ)
- Creates a realistic fake tmux ITS3 session with simulated per-pane output
- `ControlRoomWindow` (`modules/ui/control_room.py`) is a secondary window only shown in sim mode — provides a fake beam lamp + intensity slider
- `apply_hw_mode()` / `apply_sim_mode()` toggle between real and simulated hardware at runtime from the Control Room

### Persistent Config (`config.json`)
Loaded and saved by `RunWidget`. Stores: output path, rsync address/path, all run parameter field values, and ctrl fields (Planned MU, MU/min).

### Run Plan CSV (`PlanManager` / `_load_plan_from_file`)
User picks a CSV; `load_file_as_dicts()` reads it with `csv.DictReader` and every field is looked up with `.get(col, default)`, so extra/missing columns are tolerated. **`plan/plan_format_example.csv` is the canonical schema** (the one tracked file in the otherwise-gitignored `plan/`) — copy it and edit. Columns: `run`, `label`, `mode` (`treatment` | `qa`, default `treatment`), `start_x/start_y/start_r`, the 16 run-form values (`num_alpides`, `num_events`, `strobe`, `ithr`, `energy`, `MU`, `current`, `Exposure time (ms)`, `Beam delay (ms)`, `Beam on delay (ms)`, `Beam off delay (ms)`, `Loops`, `Trigger Freq. (Hz)`, `X step (mm)`, `Y step (mm)`, `R step (degree)`), then `qa_pos_x/qa_pos_y/qa_pos_r` (QA sweep target — QA rows only) + `vel_x/vel_y/vel_r` (axis speed: QA = sweep speed toward target, 0 = axis stays still; **Treatment = per-loop step / Apply / jog speed**, clamped to `[SPEED_FLOOR, SPEED_CEIL]` = 2.5–40 / 2.5–40 / 6–80). Your own working plan files also go in `plan/` (gitignored except the example).

### Toast Popups
- `modules/ui/firmware_toast.py` (`FirmwareToast`): modal indeterminate progress dialog during ALPIDE firmware flash. Has a **Cancel button, Esc handler, and hard timeout** (`eudaq.FIRMWARE_TIMEOUT_S`, default 180 s) — all three route through `_FirmwareWorker.cancel()`, which `terminate()`s then `kill()`s `alpide-daq-program`. This exists because if the DAQ boards fail to re-enumerate after the FX3 load, `alpide-daq-program` blocks forever in `select()` on its udev monitor; without a timeout that froze the whole app at startup (`install_firmware_auto()` is called from `init_connect_devices()`, before `app.exec_()`). On timeout a `QMessageBox` tells the user to power-cycle the USB hub and DAQ boards and verify with `lsusb | grep -E "04b4|1556"`. Never remove the post-`exec()` `worker.cancel()` — it's the backstop against leaving an orphan process holding the udev socket.
- `modules/ui/rsync_toast.py` (`RsyncToast`): non-modal progress dialog with % and speed during rsync; updated via `QMetaObject.invokeMethod` from a background thread

## Tests

One standalone script per refactor phase in `tests/` (run directly, not via pytest — each `sys.exit()`s):

```bash
python3 -u tests/test_phase0_auxiliary.py     # class extraction
python3 -u tests/test_phase1_config.py        # RunConfig / config.json
python3 -u tests/test_phase2_notification.py  # NotificationPanel
python3 -u tests/test_phase3_rsync.py         # RsyncManager
python3 -u tests/test_phase4_plan.py          # PlanManager
python3 -u tests/test_phase5_phantom.py --sim # PhantomPanel (needs Zaber)
python3 -u tests/test_phase6_beam.py          # BeamController (needs FPGA)
```

Phases 0-4 need no hardware and print `PASS` / `FAIL` lines. See `tests/README.md`.

## Critical Hardware Rule

**Never modify the DB-9 serial communication block in `modules/ui/run.py` `enable_beam()` at lines ~1789-1816 (the `serial.Serial(...)` open call and all `.write(b'\x...')` calls).** This controls the physical FPGA serial port — opening the port, sending reset bytes (`\x00 \x00`), enable byte (`\x02`), and disable byte (`\xF2`). These are the exact bytes expected by the FPGA firmware. Wrong bytes = incorrect beam control.

## Local EUDAQ Patch (required, not tracked by this repo)

The EUDAQ2 install lives at `/home/kobdaj/eudaq2/` (`EUDAQ_DIR` in `modules/eudaq.py` = its `user/ITS3/misc/`). It is a **separate git repo** whose `origin` is CERN's shared `alice-its3-wp3/eudaq2` — so a patch there is invisible to this repo's `git` and must be re-applied on any fresh machine/setup.

**`user/ITS3/python/ITS3RunControl.py` — `wait_replicas()` STOPPED timeout.** On back-to-back runs a slow DataCollector can sit in `OnStopRun`→`StopListen` draining its receive queue and never broadcast `STATE_STOPPED`, so `wait_replicas(STATE_STOPPED)` spins forever and the RunControl TUI never reaches `TERMINATED`. The patch gives `wait_replicas` an optional `timeout=` and calls the STOPPED wait with `timeout=13` — on expiry it `EUDAQ_WARN`s and proceeds to `STOPPED`→`TERMINATED`→`Terminate()` (the collector's data is already written by then).

`modules/eudaq.py` `stop()` depends on this: it waits up to ~20 s after sending `T` for the terminal to freeze on the real `TERMINATED` frame. Without the patch, slow-dc runs hang the ITS3 panel at `RUNNING` again. Applied on branch `kcmh-runcontrol-stopped-timeout` in the eudaq2 repo (commit `8d587f7`); revert with `git checkout master -- user/ITS3/python/ITS3RunControl.py`. `ITS3RunControl.py` is launched fresh by `ITS3start_auto_gen.sh` each run, so edits take effect with no app restart.

## Known Deferred Issues

### QA long-run trigger desync (hardware)
Consecutive QA runs with continuous windows ≥ ~20 s at 9750 Hz desync — planes' `Data EV#` diverge and the DataCollector logs `Warning! Out of sync!`. Short (~7 s) treatment runs at the same rate stay converged. Root cause is the free-running trigger vs. per-plane busy (a trigger lost during one plane's busy is a permanent offset that accumulates over tens of seconds), not the GUI. Fix direction: gate the wavegen/FPGA trigger with global busy, or drop the frequency for long runs. The GUI stop sequence now reaches `TERMINATED` on these runs anyway, and the frozen frame shows the per-plane counts so a bad run is visible at a glance.

### FPGA poll on main thread (low priority)
`_update_firmware_label()` in `modules/ui/run.py` calls `fpga_connect.check_connection()` which opens `serial.Serial(port, timeout=1)` on the main thread every 2 seconds. Could block UI up to ~1 second per cycle. Not fixed yet — wait until lag is confirmed in real usage before addressing.

**Fix when needed:** move to background thread using the same pattern as Zaber/camera (`_zaber_checking` / `_camera_checking` flags + `QMetaObject.invokeMethod` slot). Replace `check_connection()` with `get_port("fpga")` USB presence check to avoid opening the port.
