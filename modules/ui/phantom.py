from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QWidget, QSlider, QDial, QLineEdit, QMessageBox, QToolButton,
                             QSpacerItem)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon
import time

import modules.zaber.connect as zaber_connect
import modules.zaber.motion as motion
from modules.serial_connect import get_port

class PhWidget(QWidget):
    def __init__(self, window):
        super(PhWidget, self).__init__()
        self._window = window
        self.setStyleSheet("""
            QWidget {
                background-color: #eef2f7;
                color: #1e2d3d;
            }
            QLabel {
                font-size: 16px;
                color: #1e2d3d;
            }
            QToolButton {
                font-size: 14px;
                background-color: #ffffff;
                color: #1e3a5f;
                border: 1px solid #bcc8d8;
                border-radius: 8px;
                padding: 4px;
            }
            QToolButton:hover {
                background-color: #e3eaf5;
                border-color: #1565C0;
                color: #1565C0;
            }
            QToolButton:pressed {
                background-color: #c8d8ec;
            }
            QLineEdit {
                font-size: 14px;
                font-weight: bold;
                background-color: #ffffff;
                color: #1e2d3d;
                border: 1px solid #bcc8d8;
                border-radius: 4px;
                padding: 4px 8px;
                selection-background-color: #bbdefb;
            }
            QLineEdit:focus {
                border: 1px solid #1565C0;
            }
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                background-color: #1565C0;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 7px 20px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #bcc8d8;
                color: #8898a8;
            }
            QSlider::groove:horizontal {
                height: 5px;
                background: #d0dce8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #1565C0;
                border: 2px solid #1976D2;
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #90caf9;
                border-radius: 2px;
            }
            QSlider::groove:vertical {
                width: 5px;
                background: #d0dce8;
                border-radius: 2px;
            }
            QSlider::handle:vertical {
                background: #1565C0;
                border: 2px solid #1976D2;
                width: 16px;
                height: 16px;
                margin: 0 -6px;
                border-radius: 8px;
            }
            QSlider::sub-page:vertical {
                background: #90caf9;
                border-radius: 2px;
            }
            QDial {
                background-color: #ffffff;
            }
        """)
        self.init_ui()
    
    def init_ui(self):
        ph_layout = QHBoxLayout()
        phl_layout = QHBoxLayout()
        phr_layout = QVBoxLayout()
        
        self._left_button = QToolButton()
        self._left_button.setIcon(QIcon("./images/triangle-left.svg"))
        self._left_button.setIconSize(QSize(200, 200))
        self._right_button = QToolButton()
        self._right_button.setIcon(QIcon("./images/triangle-right.svg"))
        self._right_button.setIconSize(QSize(200, 200))
        self._bottom_button = QToolButton()
        self._bottom_button.setIcon(QIcon("./images/triangle-down.svg"))
        self._bottom_button.setIconSize(QSize(200, 200))
        self._top_button = QToolButton()
        self._top_button.setIcon(QIcon("./images/triangle-up.svg"))
        self._top_button.setIconSize(QSize(200, 200))
        self._cw_button = QToolButton()
        self._cw_button.setIcon(QIcon("./images/triangle-right.svg"))
        self._cw_button.setIconSize(QSize(200, 200))
        self._ccw_button = QToolButton()
        self._ccw_button.setIcon(QIcon("./images/triangle-left.svg"))
        self._ccw_button.setIconSize(QSize(200, 200))
        
        self._x_step_edit = QLineEdit()
        x_step_label = QLabel("X step: ")
        x_step_label.setMaximumWidth(90)
        self._y_step_edit = QLineEdit()
        y_step_label = QLabel("Y step: ")
        y_step_label.setMaximumWidth(90)
        self._r_step_edit = QLineEdit()
        r_step_label = QLabel("Rotate step: ")
        r_step_label.setMaximumWidth(140)
        self._x_step_edit.setMaximumWidth(80)
        self._y_step_edit.setMaximumWidth(80)
        self._r_step_edit.setMaximumWidth(80)
        self._x_step_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._y_step_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._r_step_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._x_step_edit.setText("1")        
        self._y_step_edit.setText("1")        
        self._r_step_edit.setText("1")     
        self._left_button.clicked.connect(lambda x: self.step_ph(0, -1))   
        self._right_button.clicked.connect(lambda x: self.step_ph(0, 1))   
        self._bottom_button.clicked.connect(lambda x: self.step_ph(1, -1))   
        self._top_button.clicked.connect(lambda x: self.step_ph(1, 1))   
        self._ccw_button.clicked.connect(lambda x: self.step_ph(2, -1))   
        self._cw_button.clicked.connect(lambda x: self.step_ph(2, 1))   
        
        x_step_layout = QHBoxLayout()
        x_step_sub_layout = QHBoxLayout()
        x_step_layout.addWidget(self._left_button)
        x_step_sub_layout.addWidget(x_step_label)
        x_step_sub_layout.addWidget(self._x_step_edit)
        x_step_unit_label = QLabel(" mm")
        x_step_unit_label.setStyleSheet("""
        QLabel{
            font-size: 24px;
        }
                                   """)
        x_step_unit_label.setFixedWidth(100)
        x_step_sub_layout.addWidget(x_step_unit_label)
        x_step_layout.addLayout(x_step_sub_layout)
        x_step_layout.addWidget(self._right_button)
        
        r_step_layout = QHBoxLayout()
        r_step_sub_layout = QHBoxLayout()
        r_step_layout.addWidget(self._ccw_button)
        r_step_sub_layout.addWidget(r_step_label)
        r_step_sub_layout.addWidget(self._r_step_edit)
        r_step_unit_label = QLabel(" degree")
        r_step_unit_label.setStyleSheet("""
        QLabel{
            font-size: 24px;
        }
                                   """)
        r_step_unit_label.setFixedWidth(150)
        r_step_sub_layout.addWidget(r_step_unit_label)
        r_step_layout.addLayout(r_step_sub_layout)
        r_step_layout.addWidget(self._cw_button)
        
        y_step_layout = QVBoxLayout()
        y_step_sub_layout = QHBoxLayout()
        y_step_layout.addWidget(self._top_button)
        y_step_sub_layout.addWidget(y_step_label)
        y_step_sub_layout.addWidget(self._y_step_edit)
        y_step_unit_label = QLabel(" mm")
        y_step_unit_label.setStyleSheet("""
        QLabel{
            font-size: 24px;
        }
                                   """)
        y_step_unit_label.setFixedWidth(100)
        y_step_sub_layout.addWidget(y_step_unit_label)
        y_step_layout.addLayout(y_step_sub_layout)
        y_step_layout.addWidget(self._bottom_button)
        
        self._x_slider = QSlider(Qt.Horizontal)
        self._x_slider.setFocusPolicy(Qt.StrongFocus)
        self._x_slider.setTickPosition(QSlider.TicksBothSides)
        self._x_slider.setTickInterval(15)
        self._x_slider.setMaximum(150)
        self._x_slider.setSingleStep(1)
        self._x_slider.setValue(int(float(self._window.orig_loc[0])))
        
        self._r_slider = QDial()
        self._r_slider.setFocusPolicy(Qt.StrongFocus)
        self._r_slider.setNotchesVisible(True)
        self._r_slider.setWrapping(True)
        self._r_slider.setMinimum(0)
        self._r_slider.setMaximum(360)
        self._r_slider.setValue(int(float(self._window.orig_loc[2])))
        
        self._y_slider = QSlider(Qt.Vertical)
        self._y_slider.setFocusPolicy(Qt.StrongFocus)
        self._y_slider.setTickPosition(QSlider.TicksBothSides)
        self._y_slider.setMaximum(40)
        self._y_slider.setTickInterval(10)
        self._y_slider.setSingleStep(1)
        self._y_slider.setValue(int(float(self._window.orig_loc[1])))
        
        btns_widget = QWidget()
        btns_layout = QHBoxLayout()
        phlabel_layout = QHBoxLayout()
        x_layout = QHBoxLayout()
        y_layout = QHBoxLayout()
        r_layout = QHBoxLayout()
        
        x_label = QLabel("X: ")
        y_label = QLabel("Y: ")
        r_label = QLabel("R: ")
  
        x_unit_label = QLabel(" mm")
        y_unit_label = QLabel(" mm")
        r_unit_label = QLabel(" degree")
        
        middle_btn_layout = QHBoxLayout()
        home_btn = QPushButton("Home")
        center_btn = QPushButton("Center")
        home_btn.clicked.connect(lambda x: self.locate_ph("home"))
        center_btn.clicked.connect(lambda x: self.locate_ph("center"))
        self._ph_x_edit = QLineEdit()
        self._ph_y_edit = QLineEdit()
        self._ph_r_edit = QLineEdit()
        self._ph_x_edit.setText(self._window.orig_loc[0])
        self._ph_y_edit.setText(self._window.orig_loc[1])
        self._ph_r_edit.setText(self._window.orig_loc[2])
        self._ph_x_edit.textChanged.connect(lambda x: self.change_line_edit(0))
        self._ph_y_edit.textChanged.connect(lambda x: self.change_line_edit(1))
        self._ph_r_edit.textChanged.connect(lambda x: self.change_line_edit(2))
        self._y_slider.valueChanged.connect(lambda x: self.change_ph(1))
        self._r_slider.valueChanged.connect(lambda x: self.change_ph(2))
        self._x_slider.valueChanged.connect(lambda x: self.change_ph(0))
        
        right_btn_layout = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setDisabled(True)
        clear_btn.clicked.connect(self.clear_ph)
        self._apply_btn.clicked.connect(self.apply_ph)
        
        x_layout.addWidget(x_label)
        x_layout.addWidget(self._ph_x_edit)
        x_layout.addWidget(x_unit_label)
        
        y_layout.addWidget(y_label)
        y_layout.addWidget(self._ph_y_edit)
        y_layout.addWidget(y_unit_label)
        
        r_layout.addWidget(r_label)
        r_layout.addWidget(self._ph_r_edit)
        r_layout.addWidget(r_unit_label)
        
        phlabel_layout.addLayout(x_layout)
        phlabel_layout.addLayout(y_layout)
        phlabel_layout.addLayout(r_layout)
        middle_btn_layout.addWidget(home_btn)
        middle_btn_layout.addWidget(center_btn)
        right_btn_layout.addWidget(clear_btn)
        right_btn_layout.addWidget(self._apply_btn)
        btns_layout.addLayout(phlabel_layout)
        btns_layout.addLayout(middle_btn_layout)
        btns_layout.addLayout(right_btn_layout)
        btns_widget.setLayout(btns_layout)
        
        phl_layout.addWidget(self._y_slider)
        phl_layout.addLayout(y_step_layout)
        phr_layout.addWidget(self._x_slider, stretch=1)
        phr_layout.addSpacerItem(QSpacerItem(1, 20))
        phr_layout.addLayout(x_step_layout, stretch=0)
        phr_layout.addSpacerItem(QSpacerItem(1, 20))
        phr_layout.addWidget(self._r_slider, stretch=1)
        phr_layout.addSpacerItem(QSpacerItem(1, 20))
        phr_layout.addLayout(r_step_layout, stretch=0)
        phr_layout.addSpacerItem(QSpacerItem(1, 20))
        phr_layout.addWidget(btns_widget, stretch=0, alignment=Qt.AlignmentFlag.AlignBottom)
        phr_layout.setSpacing(0)
        ph_layout.addLayout(phl_layout)
        ph_layout.addLayout(phr_layout)
        
        self.setLayout(ph_layout)
        
        # self._main_layout.addLayout(ph_layout)
        # self._main_widget.setLayout(self._main_layout)
        # self.setCentralWidget(self._main_widget)
        
    
    def change_ph(self, axis):
        if axis == 0:
            self._ph_x_edit.setText(str(self._x_slider.value()))
        elif axis == 1:
            self._ph_y_edit.setText(str(self._y_slider.value()))
        else:
            self._ph_r_edit.setText(str(self._r_slider.value()))
        
        if float(self._window.orig_loc[0]) != float(self._ph_x_edit.text()) or\
            float(self._window.orig_loc[1]) != float(self._ph_y_edit.text()) or\
            float(self._window.orig_loc[2]) != float(self._ph_r_edit.text()):
            self._apply_btn.setDisabled(False)
        else:
            self._apply_btn.setDisabled(True)
    
    def locate_ph(self, loc):
        if loc == "home":
            self._ph_x_edit.setText("0")
            self._ph_y_edit.setText("0")
            self._ph_r_edit.setText("0")
        else:
            self._ph_x_edit.setText("{:.1f}".format(99))
            self._ph_y_edit.setText("0")
            self._ph_r_edit.setText("0")
        
        if float(self._window.orig_loc[0]) != float(self._ph_x_edit.text()) or\
            float(self._window.orig_loc[1]) != float(self._ph_y_edit.text()) or\
            float(self._window.orig_loc[2]) != float(self._ph_r_edit.text()):
            self._apply_btn.setDisabled(False)
        else:
            self._apply_btn.setDisabled(True)
    
    def clear_ph(self):
        self._ph_x_edit.setText(self._window.orig_loc[0])
        self._ph_y_edit.setText(self._window.orig_loc[1])
        self._ph_r_edit.setText(self._window.orig_loc[2])
        self._apply_btn.setDisabled(True)
    
    def apply_ph(self):
        self._apply_btn.setDisabled(True)
        # try:
        conn = zaber_connect.connect(get_port("zaber"))
        motion.apply_move(conn, (
            float(self._ph_x_edit.text()),
            float(self._ph_y_edit.text()),
            float(self._ph_r_edit.text())
        ))
        loc = motion.get_current_locations(conn)
        conn.close()
        self.set_all_loc(loc)
        # except:
        #     try:
        #         conn = zaber_connect.connect()
        #         loc = motion.get_current_locations(conn)
        #         conn.close()
        #         self.set_all_loc(loc)
        #     except:
        #         fail_dialog = QMessageBox()
        #         fail_dialog.setIcon(QMessageBox.Icon.Critical)
        #         fail_dialog.setText("Fail to connect devices.")
        #         fail_dialog.setWindowTitle("Connection issue")
        #         fail_dialog.setDetailedText("Please reconnect devices.")
        #         fail_dialog.setStandardButtons(QMessageBox.Ok) 
        #         fail_dialog.exec_()
    
    def change_line_edit(self, axis):
        if axis == 0:
            try:
                self._x_slider.setValue(int(float(self._ph_x_edit.text())))
            except ValueError:
                pass
        elif axis == 1:
            try:
                self._y_slider.setValue(int(float(self._ph_y_edit.text())))
            except ValueError:
                pass
        else:
            try:
                self._r_slider.setValue(int(float(self._ph_r_edit.text())))
            except ValueError:
                pass
            
        if float(self._window.orig_loc[0]) != float(self._ph_x_edit.text()) or\
            float(self._window.orig_loc[1]) != float(self._ph_y_edit.text()) or\
            float(self._window.orig_loc[2]) != float(self._ph_r_edit.text()):
            self._apply_btn.setDisabled(False)
        else:
            self._apply_btn.setDisabled(True)
    
    def step_ph(self, axis, move=1):
        self._apply_btn.setDisabled(True)
        limit_dailog = QMessageBox()
        limit_dailog.setIcon(QMessageBox.Icon.Information)
        limit_dailog.setWindowTitle("Motion information")
        limit_dailog.setStandardButtons(QMessageBox.Ok)
        is_limited = False
        if axis == 0:
            if float(self._ph_x_edit.text()) + float(self._x_step_edit.text())*move > self._x_slider.maximum() or\
                float(self._ph_x_edit.text()) + float(self._x_step_edit.text())*move < self._x_slider.minimum():
                is_limited = True
                limit_dailog.setText("X axis is at limit.")
            else:
                try:
                    conn = zaber_connect.connect(get_port("zaber"))
                    motion.apply_step(conn, 0, move*float(self._x_step_edit.text()))
                    conn.close()
                except:
                    fail_dialog = QMessageBox()
                    fail_dialog.setIcon(QMessageBox.Icon.Critical)
                    fail_dialog.setText("Fail to connect devices.")
                    fail_dialog.setWindowTitle("Connection issue")
                    fail_dialog.setDetailedText("Please reconnect devices.")
                    fail_dialog.setStandardButtons(QMessageBox.Ok) 
                    fail_dialog.exec_()
        elif axis == 1:
            if float(self._ph_y_edit.text()) + float(self._y_step_edit.text())*move > self._y_slider.maximum() or\
                float(self._ph_y_edit.text()) + float(self._y_step_edit.text())*move < self._y_slider.minimum():
                is_limited = True
                limit_dailog.setText("Y axis is at limit.")
            else:
                try:
                    conn = zaber_connect.connect(get_port("zaber"))
                    motion.apply_step(conn, 1, move*float(self._y_step_edit.text()))
                    conn.close()
                except:
                    fail_dialog = QMessageBox()
                    fail_dialog.setIcon(QMessageBox.Icon.Critical)
                    fail_dialog.setText("Fail to connect devices.")
                    fail_dialog.setWindowTitle("Connection issue")
                    fail_dialog.setDetailedText("Please reconnect devices.")
                    fail_dialog.setStandardButtons(QMessageBox.Ok) 
                    fail_dialog.exec_()
        else:
            try:
                conn = zaber_connect.connect(get_port("zaber"))
                motion.apply_step(conn, 2, move*float(self._r_step_edit.text()))
                conn.close()
            except:
                fail_dialog = QMessageBox()
                fail_dialog.setIcon(QMessageBox.Icon.Critical)
                fail_dialog.setText("Fail to connect devices.")
                fail_dialog.setWindowTitle("Connection issue")
                fail_dialog.setDetailedText("Please reconnect devices.")
                fail_dialog.setStandardButtons(QMessageBox.Ok) 
                fail_dialog.exec_()
            
        if is_limited:
            limit_dailog.exec_()
        else:
            try:
                conn = zaber_connect.connect(get_port("zaber"))
                loc = motion.get_current_locations(conn)
                conn.close()
                self.set_all_loc(loc)
            except:
                fail_dialog = QMessageBox()
                fail_dialog.setIcon(QMessageBox.Icon.Critical)
                fail_dialog.setText("Fail to connect devices.")
                fail_dialog.setWindowTitle("Connection issue")
                fail_dialog.setDetailedText("Please reconnect devices.")
                fail_dialog.setStandardButtons(QMessageBox.Ok) 
                fail_dialog.exec_()
        
    def set_all_loc(self, loc):
        self._window.orig_loc = ["{:.2f}".format(l) for l in loc]
        self._ph_x_edit.setText(self._window.orig_loc[0])
        self._ph_y_edit.setText(self._window.orig_loc[1])
        self._ph_r_edit.setText(self._window.orig_loc[2])
        self._x_slider.setValue(int(float(self._ph_x_edit.text())))
        self._y_slider.setValue(int(float(self._ph_y_edit.text())))
        self._r_slider.setValue(int(float(self._ph_r_edit.text())))
        self._window.set_run_ph_loc(self._window.orig_loc)