from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG, pyqtSignal, pyqtSlot

import threading
import modules.zaber.connect as zaber_connect
import modules.zaber.motion as motion
from modules.serial_connect import get_port


class ZaberMoveDialog(QDialog):
    """Modal progress dialog while Zaber stages move. Shows indeterminate bar + large emergency stop."""

    STOPPED = 2

    _sig_move_done  = pyqtSignal(float, float, float)
    _sig_move_error = pyqtSignal(str)
    _sig_stop_done  = pyqtSignal()

    def __init__(self, parent, target_str):
        super().__init__(parent)
        self.setWindowTitle("Moving Phantom")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.result_loc   = None
        self.result_error = None
        self._conn      = None
        self._conn_lock = threading.Lock()
        self._stopping  = False

        self._sig_move_done.connect(self._on_move_done)
        self._sig_move_error.connect(self._on_move_error)
        self._sig_stop_done.connect(self._finish_stop)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(28, 24, 28, 24)

        title = QLabel("Moving Phantom")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1a2a3a;")
        layout.addWidget(title)

        target_lbl = QLabel(f"Target:  {target_str}")
        target_lbl.setAlignment(Qt.AlignCenter)
        target_lbl.setStyleSheet("font-size: 12px; color: #4a6078; font-family: monospace;")
        layout.addWidget(target_lbl)

        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet("""
            QProgressBar { background: #dde5ef; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #1565C0; border-radius: 3px; }
        """)
        layout.addWidget(bar)

        self._status_lbl = QLabel("Connecting to Zaber...")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setStyleSheet("font-size: 11px; color: #4a6078;")
        layout.addWidget(self._status_lbl)

        layout.addSpacing(10)

        self._stop_btn = QPushButton("⏹   EMERGENCY STOP")
        self._stop_btn.setFixedHeight(64)
        self._stop_btn.setMinimumWidth(280)
        self._stop_btn.setDefault(True)
        self._stop_btn.setAutoDefault(True)
        self._stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #c62828;
                color: white;
                font-size: 17px;
                font-weight: bold;
                border-radius: 8px;
                border: none;
                letter-spacing: 1px;
            }
            QPushButton:hover   { background-color: #b71c1c; }
            QPushButton:pressed { background-color: #7f0000; }
            QPushButton:disabled { background-color: #888; color: #ccc; }
        """)
        self._stop_btn.clicked.connect(self._emergency_stop)
        layout.addWidget(self._stop_btn)

        hint = QLabel("Press  Enter  or click to stop")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("font-size: 10px; color: #8090a0;")
        layout.addWidget(hint)

        self.setMinimumWidth(340)
        self._stop_btn.setFocus()

    def set_conn(self, conn):
        with self._conn_lock:
            self._conn = conn
        QMetaObject.invokeMethod(
            self._status_lbl, "setText", Qt.QueuedConnection, Q_ARG(str, "Moving...")
        )

    def _emergency_stop(self):
        self._stopping = True
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("Stopping...")
        with self._conn_lock:
            conn = self._conn
        if conn is None:
            self._sig_stop_done.emit()
            return
        def _do_stop():
            try:
                motion.stop_all(conn)
            except Exception:
                pass
            self._sig_stop_done.emit()
        threading.Thread(target=_do_stop, daemon=True).start()

    @pyqtSlot()
    def _finish_stop(self):
        self.done(self.STOPPED)

    @pyqtSlot(float, float, float)
    def _on_move_done(self, x, y, r):
        if self._stopping:
            self.done(self.STOPPED)
        else:
            self.result_loc = (x, y, r)
            self.accept()

    @pyqtSlot(str)
    def _on_move_error(self, err):
        if self._stopping:
            # error is expected when stop_all interrupts apply_move — treat as STOPPED
            self.done(self.STOPPED)
        else:
            self.result_error = err
            self.reject()

    def run_homing(self):
        """Start homing in a background thread and run the dialog event loop."""
        def _do():
            conn = None
            try:
                conn = zaber_connect.connect(get_port("zaber"))
                self.set_conn(conn)
                motion.to_home(conn)
                self._sig_move_done.emit(0.0, 0.0, 0.0)
            except Exception as exc:
                self._sig_move_error.emit(str(exc))
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        threading.Thread(target=_do, daemon=True).start()
        return self.exec_()
