import threading

from PyQt5.QtCore import QObject, pyqtSignal

import modules.zaber.motion as motion


# Axis hard limits (mm / degrees)
X_MAX = 150.0
Y_MAX = 40.0
R_MAX = 360.0


class PhantomPanel(QObject):
    """State + hardware layer for Zaber phantom stage control.

    UI widgets stay in RunWidget; this class owns:
      - _phantom_moving  : bool   — True while a move is in progress
      - _vel_conn        : connection object (or None)
      - _pos_poll_result : (x_str, y_str, r_str) tuple from last poll, or None

    Emits stopped() when a move is ended (vel_stop / emergency_stop).
    """

    stopped = pyqtSignal()  # emitted after vel_stop / emergency_stop

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phantom_moving  = False
        self._vel_conn        = None
        self._pos_poll_result = None

    # ── public API ────────────────────────────────────────────────────────────

    def apply(self, x: float, y: float, r: float) -> bool:
        """Validate move coordinates against axis limits.

        Returns False if any value is out of range; True otherwise.
        The caller is responsible for executing the actual move.
        """
        if not (0.0 <= x <= X_MAX):
            return False
        if not (0.0 <= y <= Y_MAX):
            return False
        if not (0.0 <= r <= R_MAX):
            return False
        return True

    def vel_stop(self):
        """Stop an in-progress velocity/move. Safe to call when idle."""
        conn = self._vel_conn
        self._vel_conn = None
        self._phantom_moving = False
        if conn is not None:
            def _stop():
                try:
                    motion.stop_all(conn)
                    conn.close()
                except Exception:
                    pass
            threading.Thread(target=_stop, daemon=True).start()
        self.stopped.emit()

    def emergency_stop(self):
        """Hard stop — always clears _phantom_moving regardless of state."""
        self._phantom_moving = False
        conn = self._vel_conn
        self._vel_conn = None
        if conn is not None:
            def _stop():
                try:
                    motion.stop_all(conn)
                    conn.close()
                except Exception:
                    pass
            threading.Thread(target=_stop, daemon=True).start()
        self.stopped.emit()
