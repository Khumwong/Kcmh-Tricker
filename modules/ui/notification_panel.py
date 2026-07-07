from datetime import datetime

from PyQt5.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer, QObject


class NotificationPanel(QObject):
    """Toast + notification history panel + bell button.

    parent_widget: the QWidget toasts and the panel float over (RunWidget).
                   Pass None only in tests.
    """

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self._parent          = parent_widget
        self._notifications   = []
        self._unread_count    = 0
        self._notif_panel     = None
        self._notif_scroll    = None
        self._notif_list_widget  = None
        self._notif_list_layout  = None

        self._bell_btn = QPushButton("🔔")
        self._bell_btn.setFixedSize(36, 36)
        self._bell_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bell_btn.setToolTip("Notification history")
        self._bell_btn.setStyleSheet("""
            QPushButton {
                font-size: 17px;
                background-color: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 7px;
                color: #ffffff;
            }
            QPushButton:hover { background-color: rgba(255,255,255,0.18); }
            QPushButton:pressed { background-color: rgba(255,255,255,0.06); }
        """)
        self._bell_btn.clicked.connect(self._toggle)

        self._bell_badge = QLabel("")
        self._bell_badge.setAlignment(Qt.AlignCenter)
        self._bell_badge.setFixedSize(16, 16)
        self._bell_badge.setVisible(False)
        self._bell_badge.setStyleSheet("""
            QLabel {
                background-color: #ff4757;
                color: white;
                font-size: 9px;
                font-weight: bold;
                border-radius: 8px;
            }
        """)

    # ── public API ────────────────────────────────────────────────────────────

    def show_toast(self, title, message, duration_ms=3000, icon="✓", icon_color="#00e676"):
        """Show floating toast and record in history."""
        self._notifications.insert(0, {
            "time":       datetime.now().strftime("%H:%M:%S"),
            "title":      title,
            "message":    message,
            "icon_color": icon_color,
            "icon":       icon,
        })
        self._unread_count += 1
        self._update_bell_badge()
        if self._notif_panel and self._notif_panel.isVisible():
            self._rebuild_notif_list()

        if self._parent is None:
            return

        existing = [c for c in self._parent.children()
                    if isinstance(c, QFrame) and c.objectName() == "toast"]
        offset_y = 56 + sum(c.height() + 10 for c in existing)

        toast = QFrame(self._parent)
        toast.setObjectName("toast")
        toast.setFixedWidth(300)

        accent = QFrame(toast)
        accent.setFixedHeight(4)
        accent.setStyleSheet(f"QFrame {{ background-color: {icon_color}; border: none; border-radius: 0px; }}")

        toast.setStyleSheet("""
            QFrame#toast {
                background-color: #0d1a2e;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
            }
        """)

        outer = QVBoxLayout(toast)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(accent)

        inner = QVBoxLayout()
        inner.setContentsMargins(14, 10, 14, 12)
        inner.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        badge = QLabel(icon)
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"""
            QLabel {{
                color: {icon_color};
                font-size: 15px;
                font-weight: bold;
                background-color: rgba(255,255,255,0.07);
                border-radius: 14px;
                border: none;
            }}
        """)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"QLabel {{ color: {icon_color}; font-size: 13px; font-weight: bold; border: none; }}")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton { color: rgba(255,255,255,0.35); font-size: 12px; border: none; background: transparent; }
            QPushButton:hover { color: #ffffff; background: rgba(255,255,255,0.1); border-radius: 11px; }
        """)
        close_btn.clicked.connect(toast.deleteLater)

        header.addWidget(badge)
        header.addWidget(title_lbl)
        header.addStretch()
        header.addWidget(close_btn)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("QFrame { background-color: rgba(255,255,255,0.08); border: none; }")

        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("QLabel { color: #b0c8e8; font-size: 12px; border: none; }")
        msg_lbl.setWordWrap(True)

        inner.addLayout(header)
        inner.addWidget(div)
        inner.addWidget(msg_lbl)
        outer.addLayout(inner)

        toast.adjustSize()
        toast.move(self._parent.width() - toast.width() - 20, offset_y)
        toast.show()
        toast.raise_()

        QTimer.singleShot(duration_ms, toast.deleteLater)

    def clear(self):
        self._notifications.clear()
        self._unread_count = 0
        self._update_bell_badge()
        if self._notif_panel and self._notif_panel.isVisible():
            self._rebuild_notif_list()

    def handle_resize(self):
        """Call from RunWidget.resizeEvent — repositions toasts and panel."""
        if self._parent is None:
            return
        existing = [c for c in self._parent.children()
                    if isinstance(c, QFrame) and c.objectName() == "toast"]
        for i, t in enumerate(existing):
            t.move(self._parent.width() - t.width() - 20, 56 + i * (t.height() + 10))
        if self._notif_panel and self._notif_panel.isVisible():
            self._reposition_panel()

    # ── bell + panel internals ────────────────────────────────────────────────

    def _update_bell_badge(self):
        if self._unread_count > 0:
            self._bell_badge.setText(str(min(self._unread_count, 99)))
            self._bell_badge.setVisible(True)
            self._bell_btn.setStyleSheet("""
                QPushButton {
                    font-size: 17px;
                    background-color: rgba(255,71,87,0.25);
                    border: 1px solid #ff4757;
                    border-radius: 7px;
                    color: #ffffff;
                }
                QPushButton:hover { background-color: rgba(255,71,87,0.38); }
            """)
        else:
            self._bell_badge.setVisible(False)
            self._bell_btn.setStyleSheet("""
                QPushButton {
                    font-size: 17px;
                    background-color: rgba(255,255,255,0.08);
                    border: 1px solid rgba(255,255,255,0.18);
                    border-radius: 7px;
                    color: #ffffff;
                }
                QPushButton:hover { background-color: rgba(255,255,255,0.18); }
                QPushButton:pressed { background-color: rgba(255,255,255,0.06); }
            """)

    def _toggle(self):
        if self._notif_panel is None:
            self._build_panel()
        if self._notif_panel.isVisible():
            self._notif_panel.hide()
        else:
            self._unread_count = 0
            self._update_bell_badge()
            self._rebuild_notif_list()
            self._reposition_panel()
            self._notif_panel.show()
            self._notif_panel.raise_()

    def _reposition_panel(self):
        if self._notif_panel is None or self._parent is None:
            return
        panel_w = self._notif_panel.width()
        x = self._parent.width() - panel_w - 12
        y = 60
        self._notif_panel.move(x, y)

    def _build_panel(self):
        panel = QFrame(self._parent)
        panel.setObjectName("notifPanel")
        panel.setFixedWidth(360)
        panel.setStyleSheet("""
            QFrame#notifPanel {
                background-color: #0d1a2e;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 10px;
            }
        """)

        outer_layout = QVBoxLayout(panel)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        header_bar = QFrame()
        header_bar.setFixedHeight(42)
        header_bar.setStyleSheet("""
            QFrame {
                background-color: #1e3a5f;
                border-radius: 10px 10px 0px 0px;
                border: none;
            }
            QLabel { border: none; color: #e0e8f8; font-size: 13px; font-weight: bold; }
        """)
        hb_layout = QHBoxLayout(header_bar)
        hb_layout.setContentsMargins(14, 0, 10, 0)
        hb_layout.addWidget(QLabel("🔔  Notifications"))
        hb_layout.addStretch()
        clear_btn = QPushButton("Clear all")
        clear_btn.setFixedHeight(26)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255,255,255,0.1);
                color: #b0c8e8;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 5px;
                font-size: 11px;
                padding: 0px 10px;
            }
            QPushButton:hover { background-color: rgba(255,255,255,0.2); color: #ffffff; }
        """)
        clear_btn.clicked.connect(self.clear)
        hb_layout.addWidget(clear_btn)
        outer_layout.addWidget(header_bar)

        self._notif_scroll = QScrollArea()
        self._notif_scroll.setWidgetResizable(True)
        self._notif_scroll.setFrameShape(QFrame.NoFrame)
        self._notif_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._notif_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: #0d1a2e; width: 6px; margin: 0; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.2); border-radius: 3px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._notif_list_widget = QWidget()
        self._notif_list_widget.setStyleSheet("QWidget { background: transparent; }")
        self._notif_list_layout = QVBoxLayout(self._notif_list_widget)
        self._notif_list_layout.setContentsMargins(8, 8, 8, 8)
        self._notif_list_layout.setSpacing(6)
        self._notif_list_layout.addStretch()
        self._notif_scroll.setWidget(self._notif_list_widget)
        outer_layout.addWidget(self._notif_scroll)

        panel.hide()
        self._notif_panel = panel

    def _rebuild_notif_list(self):
        layout = self._notif_list_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._notifications:
            empty_lbl = QLabel("No notifications yet")
            empty_lbl.setAlignment(Qt.AlignCenter)
            empty_lbl.setStyleSheet("QLabel { color: rgba(255,255,255,0.3); font-size: 12px; padding: 24px; border: none; }")
            layout.insertWidget(0, empty_lbl)
        else:
            for i, n in enumerate(self._notifications):
                layout.insertWidget(i, self._make_notif_row(n))

        self._notif_list_widget.adjustSize()
        desired = min(max(self._notif_list_widget.sizeHint().height() + 52, 90), 420)
        self._notif_panel.setFixedHeight(desired)

    def _make_notif_row(self, n):
        row = QFrame()
        row.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-left: 3px solid {n['icon_color']};
                border-radius: 6px;
            }}
            QLabel {{ border: none; }}
        """)
        rl = QVBoxLayout(row)
        rl.setContentsMargins(10, 7, 10, 7)
        rl.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        icon_lbl = QLabel(n["icon"])
        icon_lbl.setStyleSheet(f"QLabel {{ color: {n['icon_color']}; font-size: 13px; }}")
        title_lbl = QLabel(n["title"])
        title_lbl.setStyleSheet(f"QLabel {{ color: {n['icon_color']}; font-size: 12px; font-weight: bold; }}")
        time_lbl = QLabel(n["time"])
        time_lbl.setStyleSheet("QLabel { color: rgba(255,255,255,0.3); font-size: 10px; }")
        top_row.addWidget(icon_lbl)
        top_row.addWidget(title_lbl)
        top_row.addStretch()
        top_row.addWidget(time_lbl)
        rl.addLayout(top_row)

        if n["message"]:
            msg_lbl = QLabel(n["message"])
            msg_lbl.setStyleSheet("QLabel { color: #8898a8; font-size: 11px; }")
            msg_lbl.setWordWrap(True)
            rl.addWidget(msg_lbl)

        return row
