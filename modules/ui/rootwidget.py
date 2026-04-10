from PyQt5.QtWidgets import (
    QWidget, QPushButton, QLineEdit, QApplication, QMainWindow,
    QVBoxLayout, QHBoxLayout, QFrame, QSpacerItem, QSizePolicy,
    QMessageBox, QFileDialog,
    QLabel, QAction, qApp, QDialog
    )
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QIcon

class RootWidget(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        m_layout = QVBoxLayout()
        self._source_label = QLineEdit()
        self._dest_label = QLineEdit()
        self._source_label.setReadOnly(True)
        self._dest_label.setReadOnly(True)
        self._source_label.setFixedWidth(400)
        self._dest_label.setFixedWidth(400)
        self._source_btn = QPushButton("Source")
        self._dest_btn = QPushButton("Destination")
        self._source_btn.setFixedWidth(100)
        self._dest_btn.setFixedWidth(100)
        self._from_evt_label = QLabel("From event: ")
        self._to_evt_label = QLabel("To event: ")
        self._from_evt_edit = QLineEdit()
        self._to_evt_edit = QLineEdit()
        self._from_evt_label.setFixedWidth(100)
        self._from_evt_edit.setFixedWidth(100)
        self._to_evt_label.setFixedWidth(100)
        self._to_evt_edit.setFixedWidth(100)
        self._export_btn = QPushButton("Export")
        
        
        h_layout = QHBoxLayout()
        hh_box = QHBoxLayout()
        hh_box.addWidget(self._from_evt_label)
        hh_box.addWidget(self._from_evt_edit)
        h_layout.addLayout(hh_box)
        hh_box = QHBoxLayout()
        hh_box.addWidget(self._to_evt_label)
        hh_box.addWidget(self._to_evt_edit)
        h_layout.addLayout(hh_box)
        m_layout.addLayout(h_layout)
        
        h_layout = QHBoxLayout()
        h_layout.addWidget(self._source_label)
        h_layout.addWidget(self._source_btn)
        m_layout.addLayout(h_layout)        
        h_layout = QHBoxLayout()
        h_layout.addWidget(self._dest_label)
        h_layout.addWidget(self._dest_btn)        
        m_layout.addLayout(h_layout)
        
        m_layout.addWidget(self._export_btn)
        
        self.setLayout(m_layout)
        self.setModal(True)
