# modules/sim.py — minimal state holder for --sim mode
# --sim is identical to real mode, plus a Control Room window.
# No monkey-patching; hardware modules run as-is.

main_window  = None   # reference to MyWindow (set from main.py)
control_room = None   # reference to ControlRoomWindow (set from main.py)
_log         = None   # unused; guards in run_progress.py check: if _sim._log is not None
