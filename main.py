# main.py
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
import sys
from modules.window import MyWindow
import subprocess
import serial
from modules.serial_connect import get_port

GLOBAL_STYLE = """
QMainWindow, QDialog, QWidget {
    font-family: 'Segoe UI', Arial, sans-serif;
}
QMainWindow {
    background-color: #eef2f7;
    color: #1e2d3d;
}
QTabWidget::pane {
    border: none;
    border-top: 1px solid #c0cfe0;
    background-color: #eef2f7;
}
QTabWidget > QWidget {
    background-color: #1e3a5f;
}
QTabBar {
    background-color: #1e3a5f;
}
QTabBar::tab {
    background-color: transparent;
    color: rgba(255, 255, 255, 0.55);
    padding: 10px 36px;
    border: none;
    border-bottom: 3px solid transparent;
    font-size: 14px;
    min-width: 100px;
}
QTabBar::tab:selected {
    color: #ffffff;
    border-bottom: 3px solid #42a5f5;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    color: rgba(255, 255, 255, 0.8);
}
QMenuBar {
    background-color: #162d4a;
    color: rgba(255,255,255,0.75);
    font-size: 14px;
    padding: 2px;
}
QMenuBar::item:selected {
    background-color: #1e3a5f;
    color: #ffffff;
}
QMenu {
    background-color: #ffffff;
    color: #1e2d3d;
    border: 1px solid #c0cfe0;
    padding: 4px;
}
QMenu::item:selected {
    background-color: #e3eaf5;
    color: #1e3a5f;
}
QToolTip {
    background-color: #1e3a5f;
    color: #ffffff;
    border: none;
    font-size: 13px;
    padding: 4px 8px;
    border-radius: 4px;
}
QScrollBar:vertical {
    background: #dce4ef;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #90aac8;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QMessageBox {
    background-color: #ffffff;
    color: #1e2d3d;
}
QMessageBox QPushButton {
    background-color: #1565C0;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 20px;
    font-size: 14px;
    min-width: 80px;
}
QMessageBox QPushButton:hover {
    background-color: #1976D2;
}
"""

class _StderrFilter:
    """Suppress spurious tracebacks from zaber_motion and pyusb."""
    _SUPPRESS = (
        'filter_connection_event',
        "'RunWidget' object has no attribute 'interface_id'",
        'libusb_fill_iso_transfer',
    )

    def __init__(self, orig):
        self._orig = orig
        self._pending = []    # buffered traceback lines
        self._in_tb = False   # currently inside a Traceback block
        self._drop_tb = False # True when a suppress pattern was found in this block

    def write(self, s):
        if s.startswith('Traceback (most recent call last'):
            self._in_tb = True
            self._drop_tb = False
            self._pending = [s]
            return
        if self._in_tb:
            self._pending.append(s)
            if any(pat in s for pat in self._SUPPRESS):
                self._drop_tb = True
            if s and not s[0].isspace():
                # end of traceback block — flush or discard
                if not self._drop_tb:
                    for line in self._pending:
                        self._orig.write(line)
                self._pending.clear()
                self._in_tb = False
                self._drop_tb = False
            return
        # outside traceback: suppress matching standalone lines too
        if any(pat in s for pat in self._SUPPRESS):
            return
        self._orig.write(s)

    def flush(self): self._orig.flush()
    def __getattr__(self, name): return getattr(self._orig, name)

sys.stderr = _StderrFilter(sys.stderr)

if __name__ == "__main__":
    sim_mode = "--sim" in sys.argv

    subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'], capture_output=True)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("./images/clipart4808976.png"))
    app.setStyleSheet(GLOBAL_STYLE)

    if sim_mode:
        from modules.ui.control_room import ControlRoomWindow
        import modules.sim as _sim_mod
        _sim_mod.control_room = ControlRoomWindow()
        _sim_mod.control_room.show()

    w = MyWindow(sim_mode=sim_mode)
    if sim_mode:
        import modules.sim as _sim_mod
        _sim_mod.main_window = w
    w.showMaximized()
    app.exec_()

    subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'], capture_output=True)

    baudrate = 115200
    parity = serial.PARITY_NONE
    bytesize = serial.EIGHTBITS
    stopbits = serial.STOPBITS_ONE

    try:
        ser = serial.Serial(port=get_port("fpga"), baudrate=baudrate, parity=parity,
                            bytesize=bytesize, stopbits=stopbits, timeout=1)
        ser.write(b'\x00')
        ser.write(b'\x00')
        ser.close()
    except:
        pass
    