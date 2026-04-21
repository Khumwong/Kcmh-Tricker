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

Installs Python dependencies (`PyQt5`, `zaber-motion`, `pyserial`, `pyusb`), apt packages (`sshpass`, `tmux`), and creates desktop launchers and `launch_app.sh`.

## Data Processing Scripts

```bash
# Convert a raw EUDAQ file to ROOT (run on remote server via SSH)
python3 StdEventMonitor_fast.py <raw_file> -o <output.root>

# Same, with per-job CPU/RAM/disk/GPU stats logged to stdout
python3 run_with_stats.py <raw_file> -o <output.root>
```

`run_with_stats.py` is a wrapper that spawns `StdEventMonitor_fast.py` as a subprocess and samples `psutil` metrics every 0.5 s. The UI triggers this remotely via SSH after each run.

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
The largest module (~1800+ lines). Contains:
- Run parameter form (num ALPIDEs, events, strobe, threshold, energy, MU, loops, step sizes, etc.)
- Phantom positioning card (delegates to `PhWidget`)
- Connection status buttons for FPGA / Zaber / ALPIDE
- Beam enable/disable via `enable_beam()` — **see critical note below**
- rsync configuration (SSH address + remote path + optional password)
- After a run completes: rsync raw file to remote, then SSH-trigger ROOT conversion via `run_with_stats.py`
- `EmbeddedTerminal`: polls `tmux capture-pane` on a 400 ms QTimer to display ITS3 session output inline

### Run Progress (`modules/ui/run_progress.py` → `RunProgress`)
- Opened when a run starts; runs acquisition loops in `QThreadPool`
- Each loop: fires EUDAQ (`eudaq.default_run`), waits, stops EUDAQ, steps Zaber, repeats
- `force_stop` module-level flag allows emergency abort

### Phantom Positioning (`modules/ui/phantom.py` → `PhWidget`)
- Jog controls for X/Y/Rotation Zaber axes
- Calls `modules.zaber.motion` functions directly

### Hardware Modules
- `modules/serial_connect.py`: `get_port(device)` — identifies serial ports by USB hardware serial number (`"zaber"` → `AB0NSAIM`, `"fpga"` → `210183B5A8D0`). For FPGA, returns the last port in the list (DB-9 adapter enumeration order).
- `modules/fpga/connect.py`: `check_connection(port)` — opens/closes port to verify FPGA is present
- `modules/zaber/connect.py`: wraps `zaber_motion.ascii.Connection.open_serial_port()`
- `modules/zaber/motion.py`: all Zaber moves use `asyncio.gather` for parallel X/Y/R movement. Limits: X ≤ 150 mm, Y ≤ 40 mm, R ≤ 360°.
- `modules/alpide.py`: detects ALPIDE DAQs by USB VID/PID. Three states: raw (unprogrammed, VID `0x04B4` PID `0x00F3`), programmed (VID `0x1556` PID `0x01B8`), or absent. Six specific DAQ serial numbers are hardcoded.
- `modules/eudaq.py`: generates EUDAQ2 `.ini`/`.conf` files in `/home/santa/eudaq2/user/ITS3/misc/`, then launches `ITS3start_auto_gen.sh` via `subprocess.Popen`. EUDAQ dir and ALPIDE serial numbers are hardcoded constants.

### Simulation Mode (`modules/sim.py`)
- `apply_sim()` monkey-patches every hardware module at runtime (serial port detection, FPGA, Zaber, ALPIDE, EUDAQ)
- Creates a realistic fake tmux ITS3 session with simulated per-pane output
- `ControlRoomWindow` (`modules/ui/control_room.py`) is a secondary window only shown in sim mode — provides a fake beam lamp + intensity slider
- `apply_hw_mode()` / `apply_sim_mode()` toggle between real and simulated hardware at runtime from the Control Room

### Persistent Config (`config.json`)
Loaded and saved by `RunWidget`. Stores: output path, rsync address/path, all run parameter field values, and ctrl fields (Planned MU, MU/min).

### Toast Popups
- `modules/ui/firmware_toast.py` (`FirmwareToast`): modal indeterminate progress dialog during ALPIDE firmware flash
- `modules/ui/rsync_toast.py` (`RsyncToast`): non-modal progress dialog with % and speed during rsync; updated via `QMetaObject.invokeMethod` from a background thread

## Critical Hardware Rule

**Never modify the DB-9 serial communication block in `modules/ui/run.py` `enable_beam()` at lines ~1789-1816 (the `serial.Serial(...)` open call and all `.write(b'\x...')` calls).** This controls the physical FPGA serial port — opening the port, sending reset bytes (`\x00 \x00`), enable byte (`\x02`), and disable byte (`\xF2`). These are the exact bytes expected by the FPGA firmware. Wrong bytes = incorrect beam control.
