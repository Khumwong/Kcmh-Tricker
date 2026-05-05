# modules/windows.py
from PyQt5.QtWidgets import QMainWindow, QAction, qApp
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon

from modules.ui.run import RunWidget

import modules.zaber.connect as zaber_connect
import modules.fpga.connect as fpga_connect
import modules.zaber.motion as motion
from modules.serial_connect import get_port
import modules.alpide as alpide

class MyWindow(QMainWindow):
    def __init__(self):
        super(MyWindow, self).__init__()
        self._fpga_connect = False
        self._zaber_connect = False
        self._alpide_connect = False
        self._camera_connect = False
        self.init_connect_devices()
        
        try:
            conn = zaber_connect.connect(get_port("zaber"))
            loc = motion.get_current_locations(conn)
            conn.close()
            self.orig_loc = ["{:.2f}".format(l) for l in loc]
        except:
            self._zaber_connect = False
            self.orig_loc = ["0"]*3
        
        self.init_ui()
    
    def init_ui(self):
        self._run_widget = RunWidget(self)
        self.setCentralWidget(self._run_widget)
        self.initMenuBar()
        
    def initMenuBar(self):
        # new action
        newAction = QAction(QIcon("./images/file.svg"), 'New', self) 
        newAction.setShortcut('Ctrl+N')
        newAction.triggered.connect(lambda x: self.run_widget_fn("New"))

        # open action
        openAction = QAction(QIcon("./images/folder-open.svg"), 'Open', self)
        openAction.setShortcut('Ctrl+O')
        openAction.setStatusTip("Open new file")
        openAction.triggered.connect(lambda x: self.run_widget_fn("Open"))

        # save action
        saveAction = QAction(QIcon("./images/save.svg"), 'Save', self)
        saveAction.setShortcut('Ctrl+S')
        saveAction.setStatusTip("Save a file")
        saveAction.triggered.connect(lambda x: self.run_widget_fn("Save"))

        # save as action
        saveAsAction = QAction(QIcon("./images/save-all.svg"), 'Save As', self)
        saveAsAction.setShortcut('Ctrl+Shift+S')
        saveAsAction.setStatusTip("Save a file as")
        saveAsAction.triggered.connect(lambda x: self.run_widget_fn("SaveAs"))

        # exit action
        exitAct = QAction(QIcon('./images/log-out.svg'), 'Exit', self)
        exitAct.setShortcut('Ctrl+Q')
        exitAct.setStatusTip('Exit application')
        exitAct.triggered.connect(qApp.quit)
        
        viewRecentAction = QAction(QIcon('./images/view.svg'), 'View recent', self)
        viewRecentAction.setShortcut('Ctrl+M')
        viewRecentAction.setStatusTip('View current raw')
        viewRecentAction.triggered.connect(lambda x: self.run_widget_fn("ViewRecent"))

        viewFile = QAction(QIcon('./images/scan-eye.svg'), 'View file', self)
        viewFile.setShortcut('Ctrl+Shift+M')
        viewFile.setStatusTip('View raw file')
        viewFile.triggered.connect(lambda x: self.run_widget_fn("ViewFile"))

        expRoot = QAction(QIcon('./images/file-up.svg'), 'Export root', self)
        expRoot.setShortcut('Ctrl+R')
        expRoot.setStatusTip('Export to root file')
        expRoot.triggered.connect(lambda x: self.run_widget_fn("ExportROOT"))
        
        fpga_connect = QAction(QIcon('./images/view.svg'), 'Connect FPGA', self)
        fpga_connect.setStatusTip('Connect FPGA')
        fpga_connect.triggered.connect(lambda x: self.reconnect_devices("fpga"))

        zaber_connect = QAction(QIcon('./images/scan-eye.svg'), 'Connec ZABERs', self)
        zaber_connect.setStatusTip('Connec ZABERs')
        zaber_connect.triggered.connect(lambda x: self.reconnect_devices("zaber"))

        alpide_connect = QAction(QIcon('./images/file-up.svg'), 'Connect ALPIDEs', self)
        alpide_connect.setStatusTip('Connect ALPIDEs')
        alpide_connect.triggered.connect(lambda x: self.reconnect_devices("alpide"))
        
        all_connect = QAction(QIcon('./images/file-up.svg'), 'Connect All', self)
        all_connect.setStatusTip('Connect all devices')
        all_connect.triggered.connect(lambda x: self.reconnect_devices("all"))

        createPlanAction = QAction('Create Plan...', self)
        createPlanAction.setStatusTip('Create a new run plan (CSV)')
        createPlanAction.triggered.connect(lambda: self.run_widget_fn("CreatePlan"))

        loadPlanAction = QAction('Load Plan...', self)
        loadPlanAction.setStatusTip('Load a run plan from CSV')
        loadPlanAction.triggered.connect(lambda: self.run_widget_fn("LoadPlan"))

        closePlanAction = QAction('Close Plan', self)
        closePlanAction.setStatusTip('Close current plan')
        closePlanAction.triggered.connect(lambda: self.run_widget_fn("ClosePlan"))

        menubar = self.menuBar()

        fileMenu = menubar.addMenu('&File')
        fileMenu.addAction(newAction)
        fileMenu.addAction(openAction)
        fileMenu.addAction(saveAction)
        fileMenu.addAction(saveAsAction)
        fileMenu.addAction(exitAct)

        monitorFile = menubar.addMenu('&Monitor')
        monitorFile.addAction(viewRecentAction)
        monitorFile.addAction(viewFile)
        monitorFile.addAction(expRoot)

        planMenu = menubar.addMenu('&Plan')
        planMenu.addAction(createPlanAction)
        planMenu.addAction(loadPlanAction)
        planMenu.addSeparator()
        planMenu.addAction(closePlanAction)
                
        # connectionMenu = menubar.addMenu('&Connection')
        # connectionMenu.addAction(alpide_connect)
        # connectionMenu.addAction(zaber_connect)
        # connectionMenu.addAction(fpga_connect)
        # connectionMenu.addAction(all_connect)
    
    def init_connect_devices(self):
        if alpide.found_daqs():
            if not alpide.is_programmed():
                self._alpide_connect = True
                if "_run_widget" in self.__dict__:
                    self._run_widget._update_firmware_label()
                import modules.eudaq as eudaq
                eudaq.install_firmware_auto(parent_widget=self)
            self._alpide_connect = True
        else:
            self._alpide_connect = False
            
        if self.check_zaber():
            self._zaber_connect = True
        else:
            self._zaber_connect = False
            
        if self.check_fpga():
            self._fpga_connect = True
        else:
            self._fpga_connect = False

        try:
            import cv2, os
            _devnull = os.open(os.devnull, os.O_WRONLY)
            _old_stderr = os.dup(2)
            os.dup2(_devnull, 2)
            os.close(_devnull)
            try:
                _cap = cv2.VideoCapture(0)
                self._camera_connect = _cap.isOpened()
                _cap.release()
            finally:
                os.dup2(_old_stderr, 2)
                os.close(_old_stderr)
        except Exception:
            self._camera_connect = False

    def reconnect_devices(self, device):
        if device in ["zaber", "fpga", "alpide"]:
            self._run_widget.check_connection(device)
        else: 
            if alpide.found_daqs():
                self._alpide_connect = True
            else:
                self._alpide_connect = False
                
            if self.check_zaber():
                self._zaber_connect = True
            else:
                self._zaber_connect = False
                
            if self.check_fpga():
                self._fpga_connect = True
            else:
                self._fpga_connect = False
            
            self._run_widget.check_connections()
                
    def check_camera(self):
        try:
            import cv2, os
            _devnull = os.open(os.devnull, os.O_WRONLY)
            _old_stderr = os.dup(2)
            os.dup2(_devnull, 2)
            os.close(_devnull)
            try:
                _cap = cv2.VideoCapture(0)
                ok = _cap.isOpened()
                _cap.release()
            finally:
                os.dup2(_old_stderr, 2)
                os.close(_old_stderr)
            self._camera_connect = ok
            return ok
        except Exception:
            self._camera_connect = False
            return False

    def check_zaber(self):
        try:
            conn = zaber_connect.connect(get_port("zaber"))
            loc = motion.get_current_locations(conn)
            if "_run_widget" in self.__dict__:
                self._run_widget.set_ph_loc_full(["{:.2f}".format(l) for l in loc])
            conn.close()
            return True
        except:
            return False
    
    def check_fpga(self):
        try:
            connection = fpga_connect.check_connection(get_port("fpga"))
            return connection
        except:
            return False
    
    def run_widget_fn(self, menu):
        if menu == "New":
            self._run_widget.clear_for_new()
        elif menu == "Open":
            self._run_widget.open_file()
        elif menu == "Save":
            self._run_widget.save_file()
        elif menu == "SaveAs":
            self._run_widget.save_file(True)
        elif menu == "ViewRecent":
            self._run_widget.viewRecentRaw()
        elif menu == "ViewFile":
            self._run_widget.viewRawFile()
        elif menu == "ExportROOT":
            self._run_widget.exportToRoot()
        elif menu == "CreatePlan":
            self._run_widget.create_plan()
        elif menu == "LoadPlan":
            self._run_widget.load_plan()
        elif menu == "ClosePlan":
            self._run_widget.close_plan()
    
    def set_run_ph_loc(self, loc):
        self._run_widget.set_ph_loc(loc)
    
    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_size_locked'):
            self._size_locked = True
            QTimer.singleShot(0, lambda: self.setFixedSize(self.size()))

    def running(self, is_running):
        rw = self._run_widget
        if is_running:
            rw._phantom_card.setDisabled(True)
            rw._outpath_btn.setDisabled(True)
            rw._rsync_addr_edit.setDisabled(True)
            rw._rsync_path_edit.setDisabled(True)
            rw._rsync_connect_btn.setDisabled(True)
            for k, v in rw._connection.items():
                if k != 'camera':
                    v.setDisabled(True)
            for ledit in rw._line_edits.values():
                ledit.setDisabled(True)
            # lock plan panel — cannot switch runs while beam is enabled
            rw._plan_table.setDisabled(True)
            rw._load_run_btn.setDisabled(True)
        else:
            rw._phantom_card.setDisabled(False)
            rw._outpath_btn.setDisabled(False)
            rw._rsync_addr_edit.setDisabled(False)
            rw._rsync_path_edit.setDisabled(False)
            rw._rsync_connect_btn.setDisabled(False)
            for v in rw._connection.values():
                v.setDisabled(False)
            for ledit in rw._line_edits.values():
                ledit.setDisabled(False)
            # unlock plan panel
            rw._plan_table.setDisabled(False)
            if rw._plan_table.currentRow() >= 0:
                rw._load_run_btn.setEnabled(True)