import serial

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

# ── CRITICAL: FPGA serial byte constants ─────────────────────────────────────
# These exact values are expected by the FPGA firmware.
# NEVER change them without verifying with the FPGA team.
RESET_BYTE   = b'\x00'   # sent twice before enable/disable
ENABLE_BYTE  = b'\x02'   # activates trigger output
DISABLE_BYTE = b'\xF2'   # deactivates trigger output


class BeamController(QObject):
    """Owns FPGA beam-enable state and the auto-kill countdown timer.

    UI widgets (checkboxes, buttons) stay in RunWidget.
    Byte writes stay in RunWidget.enable_beam() / stop_run().
    This class provides: state tracking, auto-kill countdown, and
    the static FPGA serial port parameters.
    """

    beam_enabled   = pyqtSignal()       # beam was enabled (\x02 sent)
    beam_disabled  = pyqtSignal()       # beam was disabled (\xF2 sent)
    countdown_tick = pyqtSignal(int)    # seconds remaining in auto-kill

    def __init__(self, parent=None):
        super().__init__(parent)
        self._beam_on              = False
        self._auto_kill_countdown  = 0
        self._auto_kill_timer      = QTimer(self)
        self._auto_kill_timer.setInterval(1000)

    # ── public API ────────────────────────────────────────────────────────────

    def get_fpga_data(self) -> dict:
        """Return static FPGA serial port parameters.

        Callers that also need byte_start_list (trigger freq, beam delay)
        should extend this dict with the dynamic values from the UI.
        """
        return {
            "baudrate": 115200,
            "parity":   serial.PARITY_NONE,
            "bytesize": serial.EIGHTBITS,
            "stopbits": serial.STOPBITS_ONE,
        }

    def set_beam_on(self):
        """Mark beam as enabled. Emits beam_enabled."""
        self._beam_on = True
        self.beam_enabled.emit()

    def set_beam_off(self):
        """Mark beam as disabled. Emits beam_disabled."""
        self._beam_on = False
        self.beam_disabled.emit()

    def disable(self, ser=None):
        """Send DISABLE_BYTE to FPGA and clear beam state.

        Safe to call when beam is already off (no-op).
        ser: open serial.Serial object, or None (e.g. in tests).
        """
        if not self._beam_on:
            return
        self._beam_on = False
        self._auto_kill_timer.stop()
        if ser is not None:
            try:
                ser.write(DISABLE_BYTE)
            except Exception:
                pass
        self.beam_disabled.emit()
