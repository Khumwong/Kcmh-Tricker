import re as _re
import subprocess
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextEdit, QLineEdit, QPushButton, QPlainTextEdit,
)
from PyQt5.QtCore import QTimer

# ── ANSI → HTML ───────────────────────────────────────────────────────────────

_ANSI_FG = {
    '30':'#4e4e4e','31':'#cc0000','32':'#4e9a06','33':'#c4a000',
    '34':'#3465a4','35':'#75507b','36':'#06989a','37':'#d3d7cf',
    '90':'#888a85','91':'#ef2929','92':'#8ae234','93':'#fce94f',
    '94':'#729fcf','95':'#ad7fa8','96':'#34e2e2','97':'#eeeeec',
}
_ANSI_BG = {
    '40':'#4e4e4e','41':'#cc0000','42':'#4e9a06','43':'#c4a000',
    '44':'#3465a4','45':'#75507b','46':'#06989a','47':'#d3d7cf',
    '100':'#888a85','101':'#ef2929','102':'#8ae234','103':'#fce94f',
    '104':'#729fcf','105':'#ad7fa8','106':'#34e2e2','107':'#eeeeec',
}
_NON_COLOR_ANSI = _re.compile(
    r'\x1b(?:\[[0-9;]*[A-HJKSTfhlnprsu]'
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'
    r'|[^[\]])'
)
_COLOR_ANSI = _re.compile(r'\x1b\[([0-9;]*)m')


def _ansi_to_html(raw: str) -> str:
    import html as _html
    text = _NON_COLOR_ANSI.sub('', raw)
    parts: list = []
    pos = 0
    fg = bg = None
    bold = False
    span_open = False
    for m in _COLOR_ANSI.finditer(text):
        chunk = _html.escape(text[pos:m.start()])
        if chunk:
            parts.append(chunk)
        pos = m.end()
        if span_open:
            parts.append('</span>')
            span_open = False
        codes = m.group(1).split(';') if m.group(1) else ['0']
        for c in codes:
            if c in ('0', ''):
                fg = bg = None; bold = False
            elif c == '1':
                bold = True
            elif c in _ANSI_FG:
                fg = _ANSI_FG[c]
            elif c in _ANSI_BG:
                bg = _ANSI_BG[c]
        styles: list = []
        if fg:   styles.append(f'color:{fg}')
        if bg:   styles.append(f'background-color:{bg}')
        if bold: styles.append('font-weight:bold')
        if styles:
            parts.append(f'<span style="{";".join(styles)}">')
            span_open = True
    chunk = _html.escape(text[pos:])
    if chunk:
        parts.append(chunk)
    if span_open:
        parts.append('</span>')
    body = ''.join(parts)
    return (
        '<html><body style="background-color:#0d1a2e;color:#c8d8e8;margin:4px;">'
        '<pre style="font-family:Monospace,monospace;font-size:10pt;'
        'color:#c8d8e8;margin:0;white-space:pre-wrap;word-wrap:break-word;">'
        + body + '</pre></body></html>'
    )


_STATE_ABBR = {
    'UNINITIALISED': 'UNINIT',
    'UNCONFIGURED':  'UNCONF',
    'CONFIGURED':    'CONFIG',
    'RUNNING':       'RUN',
    'STOPPED':       'STOP',
    'TERMINATED':    'TERM',
    '--ERROR--':     'ERR',
    'WAIT':          'WAIT',
}


def _abbr(s):
    return _STATE_ABBR.get(s, s[:6])


# euRun status-table rows: "│ALPIDE_plane_0   RUN   12345   7   Started│"
# box-drawing delimiters are optional (some tmux captures drop them).
_PROD_ROW_RE = _re.compile(
    r'[│|]?\s*ALPIDE_plane_(\d+)\s+(\S+)\s+(\d+)\s+(\d+)[ \t]*([^\r\n│|]*)',
    _re.MULTILINE,
)
_DC_ROW_RE = _re.compile(
    r'[│|]?\s*dc\s+(\S+)\s+(\d+)\s+(\d+)[ \t]*([^\r\n│|]*)',
    _re.MULTILINE,
)
_CURRENT_RUN_RE = _re.compile(r'Current run:\s+(\S+)\s+events\s+\(([^)]+)\)')
_PLAIN_STATE_RE = _re.compile(r'ALPIDE_plane_\d+\s+(\S+)')


def _format_its3_log(content: str) -> str:
    """Convert raw ITS3 terminal snapshots into per-snapshot blocks.

    Preferred output is the full euRun producer table per snapshot (per-plane
    Data EV# / Stat EV# / Message, incl. the DataCollector "Out of sync"
    warnings). If a snapshot has no parseable table, fall back to a one-line
    state summary for that snapshot.
    """
    content = _NON_COLOR_ANSI.sub('', content)
    content = _COLOR_ANSI.sub('', content)

    _snap_re = _re.compile(r'\[(\d{2}:\d{2}:\d{2})\]\n')
    parts = _snap_re.split(content)

    _DETAIL_HDR = ('Plane', 'State', 'Data EV#', 'Stat EV#', 'Message')
    lines = []
    n_snap = 0
    n_detailed = 0
    i = 1
    while i + 1 < len(parts):
        ts   = parts[i].strip()
        body = parts[i + 1]
        i += 2
        n_snap += 1

        producers = {}
        for m in _PROD_ROW_RE.finditer(body):
            producers[int(m.group(1))] = {
                'state':   _abbr(m.group(2)),
                'data_ev': m.group(3),
                'stat_ev': m.group(4),
                'message': m.group(5).strip(),
            }

        if not producers:
            # fallback: one-line summary for this snapshot
            states = _PLAIN_STATE_RE.findall(body)
            summary = ' '.join(_abbr(s) for s in states) if states else '—'
            lines.append(f"  {ts}  {summary}")
            continue

        n_detailed += 1
        dc_m = _DC_ROW_RE.search(body)
        dc_info = {
            'state':   _abbr(dc_m.group(1)) if dc_m else '-',
            'data_ev': dc_m.group(2) if dc_m else '-',
            'stat_ev': dc_m.group(3) if dc_m else '-',
            'message': dc_m.group(4).strip() if dc_m else '',
        }

        ev_m = _CURRENT_RUN_RE.search(body)
        events = f"{ev_m.group(1)} ({ev_m.group(2)})" if ev_m else '-'

        p_vals = {v['state'] for v in producers.values()}
        dc_st  = dc_info['state']
        if any('ERR' in v for v in p_vals) or dc_st == 'ERR':
            overall = 'ERROR'
        elif p_vals <= {'RUN'} and dc_st == 'RUN':
            overall = 'RUNNING'
        elif p_vals <= {'CONFIG', 'RUN'} and dc_st in ('CONFIG', 'RUN'):
            overall = 'CONFIG'
        elif p_vals <= {'UNINIT'} and dc_st in ('UNINIT', '-'):
            overall = 'UNINIT'
        elif p_vals <= {'UNCONF', 'UNINIT'}:
            overall = 'UNCONF'
        else:
            overall = '/'.join(sorted(p_vals)) if p_vals else '-'

        lines.append(f"  {ts}  {overall}  {events}")
        rows = []
        for n in range(6):
            p = producers.get(n, {'state': '-', 'data_ev': '-', 'stat_ev': '-', 'message': ''})
            rows.append((f'P{n}', p['state'], p['data_ev'], p['stat_ev'], p['message']))
        rows.append(('dc', dc_info['state'], dc_info['data_ev'], dc_info['stat_ev'], dc_info['message']))

        w = [max(len(_DETAIL_HDR[c]), max(len(r[c]) for r in rows)) for c in range(5)]
        fmt = '    ' + '  '.join(f'{{:<{w[c]}}}' for c in range(5))
        sep = '    ' + '  '.join('-' * w[c] for c in range(5))
        lines.append(fmt.format(*_DETAIL_HDR))
        lines.append(sep)
        for r in rows:
            lines.append(fmt.format(*r).rstrip())
        lines.append('')

    header = [
        f"ITS3 Log — {n_snap} snapshots ({n_detailed} with producer detail)",
        "=" * 40,
    ]
    return '\n'.join(header + lines + [f"  Total: {n_snap} snapshots"]) + '\n'


# ── EmbeddedTerminal ──────────────────────────────────────────────────────────

class EmbeddedTerminal(QWidget):
    """Multi-pane tmux terminal: ANSI color, 1000-line scrollback, send-keys, per-pane tabs."""

    POLL_MS    = 400
    SCROLLBACK = 1000

    _STATE_RE = _re.compile(r'ALPIDE_plane_\d+\s+(\S+)')

    _PLACEHOLDER_STYLE = (
        "QTextEdit { background-color:#0d1a2e; color:#3a5878; border:none; padding:4px; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session      = None
        self._pane_widgets: dict = {}
        self._pane_timers:  dict = {}
        self._last_texts:   dict = {}
        self._last_states        = None
        self._last_log_time      = None
        self._last_snapshot_text = None
        self._log_file           = None
        self.log_path            = None
        self._has_placeholder    = False
        self._frozen             = False  # run ended — last frame kept until clear()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._pane_tabs = QTabWidget()
        self._pane_tabs.setStyleSheet("""
            QTabWidget::pane { background:#0d1a2e; border:none; }
            QTabBar::tab {
                background:#1a2e44; color:#8aaac8;
                border:1px solid #2a3f58; border-bottom:none;
                padding:2px 10px; font-size:9pt; font-family:monospace;
            }
            QTabBar::tab:selected { background:#0d1a2e; color:#c8d8e8; }
            QTabBar::tab:hover:!selected { background:#243650; }
        """)
        layout.addWidget(self._pane_tabs, 1)
        self._show_placeholder()

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 2, 0, 0)
        input_row.setSpacing(4)
        self._input_line = QLineEdit()
        self._input_line.setPlaceholderText("send-keys → active pane  (Enter to send)")
        self._input_line.setStyleSheet("""
            QLineEdit {
                background:#0d1a2e; color:#c8d8e8;
                border:1px solid #2a3f58; border-radius:3px;
                font-family:monospace; font-size:10pt; padding:2px 6px;
            }
        """)
        self._send_btn = QPushButton("Send")
        self._send_btn.setFixedWidth(52)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background:#1a3a5c; color:#c8d8e8; border:1px solid #2a3f58;
                border-radius:3px; font-size:10pt; padding:2px 6px;
            }
            QPushButton:hover { background:#24507c; }
            QPushButton:pressed { background:#0d2a44; }
        """)
        self._send_btn.clicked.connect(self._send_keys)
        self._input_line.returnPressed.connect(self._send_keys)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedWidth(52)
        self._clear_btn.setToolTip("Dismiss the ended ITS3 session")
        self._clear_btn.setStyleSheet(self._send_btn.styleSheet())
        self._clear_btn.clicked.connect(self.clear)
        self._clear_btn.setVisible(False)
        input_row.addWidget(self._input_line)
        input_row.addWidget(self._send_btn)
        input_row.addWidget(self._clear_btn)
        layout.addLayout(input_row)

        self._discover_timer = QTimer(self)
        self._discover_timer.setInterval(2000)
        self._discover_timer.timeout.connect(self._discover_panes)

    def launch(self, session_name: str = "ITS3", delay_ms: int = 1500):
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
        self._session = session_name
        self._clear_all_panes()
        import tempfile as _tf, os as _os
        fd, self.log_path = _tf.mkstemp(prefix="its3_run_", suffix=".log")
        _os.close(fd)
        self._log_file = open(self.log_path, 'w', encoding='utf-8')
        QTimer.singleShot(delay_ms, self._start_poll)

    def _start_poll(self):
        self._discover_panes()
        self._discover_timer.start()

    def _discover_panes(self):
        if not self._session:
            return
        result = subprocess.run(
            ['tmux', 'list-panes', '-t', self._session,
             '-F', '#{pane_index} #{pane_current_command}'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return
        current: dict = {}
        for line in result.stdout.strip().splitlines():
            parts = line.split(' ', 1)
            idx = parts[0]
            cmd = (parts[1] if len(parts) > 1 else '').strip() or f"pane {idx}"
            current[idx] = cmd
        for idx, cmd in current.items():
            if idx not in self._pane_widgets:
                self._add_pane(idx, cmd)
        for idx in list(self._pane_widgets):
            if idx not in current:
                self._remove_pane(idx)

    def _show_placeholder(self):
        if self._has_placeholder:
            return
        ph = QTextEdit()
        ph.setReadOnly(True)
        ph.setStyleSheet(self._PLACEHOLDER_STYLE)
        self._pane_tabs.addTab(ph, "ITS3")
        self._has_placeholder = True

    def _hide_placeholder(self):
        if not self._has_placeholder:
            return
        self._pane_tabs.removeTab(0)
        self._has_placeholder = False

    def _make_display(self) -> QTextEdit:
        w = QTextEdit()
        w.setReadOnly(True)
        w.setStyleSheet(
            "QTextEdit { background-color:#0d1a2e; color:#c8d8e8; border:none; padding:4px; }"
        )
        return w

    def _add_pane(self, pane_idx: str, title: str):
        self._hide_placeholder()
        display = self._make_display()
        self._pane_widgets[pane_idx] = display
        self._last_texts[pane_idx]   = ""
        timer = QTimer(self)
        timer.setInterval(self.POLL_MS)
        timer.timeout.connect(lambda idx=pane_idx: self._refresh_pane(idx))
        timer.start()
        self._pane_timers[pane_idx] = timer
        self._pane_tabs.addTab(display, f"[{pane_idx}] {title}")

    def _remove_pane(self, pane_idx: str):
        if pane_idx in self._pane_timers:
            self._pane_timers.pop(pane_idx).stop()
        if pane_idx in self._pane_widgets:
            w = self._pane_widgets.pop(pane_idx)
            i = self._pane_tabs.indexOf(w)
            if i >= 0:
                self._pane_tabs.removeTab(i)
        self._last_texts.pop(pane_idx, None)

    def _clear_all_panes(self):
        self._discover_timer.stop()
        for t in self._pane_timers.values():
            t.stop()
        self._pane_timers.clear()
        self._pane_widgets.clear()
        self._last_texts.clear()
        self._has_placeholder = False
        while self._pane_tabs.count():
            self._pane_tabs.removeTab(0)
        self._show_placeholder()
        self._frozen = False
        self._last_states = None
        self._last_snapshot_text = None
        self._clear_btn.setVisible(False)
        self._input_line.setEnabled(True)
        self._send_btn.setEnabled(True)

    def freeze(self):
        """Run ended: stop polling, keep the last RunControl frame on screen with
        an 'ended' banner, and reveal the Clear button. Idempotent."""
        if self._frozen:
            return
        self._frozen = True
        self._discover_timer.stop()
        for t in self._pane_timers.values():
            t.stop()
        from datetime import datetime as _dt
        ts = _dt.now().strftime('%H:%M:%S')
        banner = f"──────── ITS3 session ended · {ts} · press Clear ────────"
        w = self._pane_widgets.get('0')
        if w is not None:
            w.append("")
            w.append(banner)
            sb = w.verticalScrollBar()
            sb.setValue(sb.maximum())
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
        self._input_line.setEnabled(False)
        self._send_btn.setEnabled(False)
        self._clear_btn.setVisible(True)

    def clear(self):
        """Dismiss the frozen session (Clear button / Enable unchecked / new run)."""
        self._clear_all_panes()
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
        self._session = None

    def _refresh_pane(self, pane_idx: str):
        if self._frozen:
            return
        target = f"{self._session}:{pane_idx}"
        result = subprocess.run(
            ['tmux', 'capture-pane', '-p', '-e', '-S', f'-{self.SCROLLBACK}', '-t', target],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return
        text = result.stdout
        if text == self._last_texts.get(pane_idx):
            return
        self._last_texts[pane_idx] = text
        settled = False
        error_frame = False
        if pane_idx == '0':
            from datetime import datetime as _dt
            # capture-pane -e leaves ANSI colour codes around the state cell, so
            # strip them before matching state names (STOPPED/TERMINATED/...)
            plain = _COLOR_ANSI.sub('', _NON_COLOR_ANSI.sub('', text))
            states = tuple(self._STATE_RE.findall(plain))
            now = _dt.now()
            state_changed = states != self._last_states
            time_elapsed = (
                self._last_log_time is None or
                (now - self._last_log_time).total_seconds() >= 5
            )
            if (state_changed or time_elapsed) and self._log_file and not self._log_file.closed:
                self._last_states = states
                self._last_log_time = now
                self._log_file.write(f"[{now.strftime('%H:%M:%S')}]\n{text}\n")
                self._log_file.flush()
            # classify the RunControl frame by the producer table
            plane_rows = _PROD_ROW_RE.findall(plain)
            plane_msgs = [r[4].strip().lower() for r in plane_rows]
            # producers disconnected → table collapsed to ERR / XXX / 0: never show
            # this, never freeze on it
            error_frame = bool(plane_rows) and all(m == 'xxx' for m in plane_msgs)
            # freeze only on the real TERMINATED frame — every producer reporting
            # "Terminated". RunControl gets there on its own (wait_replicas has a
            # timeout for a slow DataCollector), so don't shortcut on STOPPED /
            # converged counts or the big status text is never seen to flip.
            settled = bool(plane_rows) and all('terminat' in m for m in plane_msgs)
        widget = self._pane_widgets.get(pane_idx)
        if widget is not None and not error_frame:
            sb = widget.verticalScrollBar()
            at_bottom = sb.value() >= sb.maximum() - 4
            widget.setHtml(_ansi_to_html(text))
            if at_bottom:
                sb.setValue(sb.maximum())
        if settled:
            self.freeze()

    def _send_keys(self):
        text = self._input_line.text()
        if not text or not self._session:
            return
        pane_idx = self._active_pane_idx()
        subprocess.run(
            ['tmux', 'send-keys', '-t', f"{self._session}:{pane_idx}", text, 'Enter']
        )
        self._input_line.clear()

    def _active_pane_idx(self) -> str:
        widget = self._pane_tabs.currentWidget()
        for idx, w in self._pane_widgets.items():
            if w is widget:
                return idx
        return '0'

    def force_snapshot(self):
        """Force-write a log snapshot for pane 0 immediately (e.g. at end of each
        loop). Skips the write if the pane text is identical to the last snapshot."""
        if self._frozen or not self._session or not self._log_file or self._log_file.closed:
            return
        target = f"{self._session}:0"
        result = subprocess.run(
            ['tmux', 'capture-pane', '-p', '-e', '-S', f'-{self.SCROLLBACK}', '-t', target],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return
        text = result.stdout
        if text == self._last_snapshot_text:
            return
        from datetime import datetime as _dt
        now = _dt.now()
        self._last_snapshot_text = text
        plain = _COLOR_ANSI.sub('', _NON_COLOR_ANSI.sub('', text))
        self._last_states = tuple(self._STATE_RE.findall(plain))
        self._last_log_time = now
        self._log_file.write(f"[{now.strftime('%H:%M:%S')}]\n{text}\n")
        self._log_file.flush()

    # back-compat alias
    def terminate(self):
        self.clear()


# ── AppLogWidget ──────────────────────────────────────────────────────────────

class AppLogWidget(QWidget):
    """Activity log — แสดง action ที่ user/โปรแกรมทำ พร้อม timestamp."""

    _LOG_STYLE = """
        QPlainTextEdit {
            background-color: #0d1a2e;
            color: #c8d8e8;
            font-family: 'Monospace', monospace;
            font-size: 10pt;
            border: none;
            padding: 4px;
            selection-background-color: #1e5080;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._display = QPlainTextEdit()
        self._display.setReadOnly(True)
        self._display.setStyleSheet(self._LOG_STYLE)
        layout.addWidget(self._display)

    def append(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}]  {message}"
        self._display.appendPlainText(line)
        sb = self._display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear(self):
        self._display.setPlainText("")
