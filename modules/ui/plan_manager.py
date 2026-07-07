import csv

from PyQt5.QtCore import QObject, pyqtSignal


class PlanManager(QObject):
    """Pure data model for run plans loaded from CSV.

    Holds rows, status, run counts, and current index.
    UI widgets stay in RunWidget; this class emits plan_changed
    whenever the data model changes so RunWidget can repaint.
    """

    plan_changed = pyqtSignal()    # data or status updated
    run_selected = pyqtSignal(int) # step_to() called with row index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data:       list = []   # list of lists (one per CSV row)
        self.status:     list = []   # "pending" / "current" / "done"
        self.run_counts: list = []   # int: how many times each run was loaded
        self.run_done:   list = []   # bool: user-checked checkbox
        self.current:    int  = -1
        self.path:       str | None = None

    # ── public API ────────────────────────────────────────────────────────────

    def load_file(self, path: str):
        """Load plan from CSV file. Resets all state. Emits plan_changed."""
        try:
            with open(path, newline="") as f:
                rows = list(csv.reader(f))
        except (FileNotFoundError, OSError):
            self.data = []
            self.status = []
            self.run_counts = []
            self.run_done = []
            self.current = -1
            self.path = None
            return

        self.data       = rows
        self.status     = ["pending"] * len(rows)
        self.run_counts = [0] * len(rows)
        self.run_done   = [False] * len(rows)
        self.current    = -1
        self.path       = path
        self.plan_changed.emit()

    def load_file_as_dicts(self, path: str):
        """Load plan from CSV with header row. Stores rows as list of dicts.
        Used by RunWidget._load_plan_from_file for real plan files.
        """
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.data       = rows
        self.status     = ["pending"] * len(rows)
        self.run_counts = [0] * len(rows)
        self.run_done   = [False] * len(rows)
        self.current    = -1
        self.path       = path
        self.plan_changed.emit()

    def close(self):
        """Reset all plan state. Emits plan_changed."""
        self.data       = []
        self.status     = []
        self.run_counts = []
        self.run_done   = []
        self.current    = -1
        self.path       = None
        self.plan_changed.emit()

    def step_to(self, idx: int):
        """Mark idx as current, previous current as done. Emits run_selected + plan_changed."""
        if idx < 0 or idx >= len(self.data):
            return
        if 0 <= self.current < len(self.status):
            if self.status[self.current] == "current":
                self.status[self.current] = "done"
        self.current = idx
        self.status[idx] = "current"
        if idx < len(self.run_counts):
            self.run_counts[idx] += 1
        self.run_selected.emit(idx)
        self.plan_changed.emit()
