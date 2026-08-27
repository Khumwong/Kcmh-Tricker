import re
import subprocess
import threading

from PyQt5.QtCore import QObject, pyqtSignal


_PWD_SSH_OPTS = [
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'PreferredAuthentications=keyboard-interactive,password',
    '-o', 'PubkeyAuthentication=no',
]
_KEY_SSH_OPTS = ['-o', 'StrictHostKeyChecking=no']
_SSH_TIMEOUT_OPTS = ['-o', 'ConnectTimeout=10']
_RSYNC_PCT_RE = re.compile(r'(\d+)%\s+([\d.]+\S+/s)')


class RsyncManager(QObject):
    """Manages rsync/SSH operations for RunWidget.

    All network ops run in daemon threads; results arrive via signals.
    """

    status_changed = pyqtSignal(str, str)   # text, color
    done           = pyqtSignal(str, str)   # kind ("ok"/"error"/"monitor_ok"/"monitor_error"), detail
    failed         = pyqtSignal(str)        # error message (connect failures)
    progress       = pyqtSignal(str, str)   # pct, speed
    proc_created   = pyqtSignal(object)     # Popen object, emitted after rsync starts

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False
        self._password  = None

    # ── public API ────────────────────────────────────────────────────────────

    def _emit_status(self, text: str, color: str):
        """Emit status_changed; callable from any thread."""
        self.status_changed.emit(text, color)

    def connect(self, addr: str, rpath: str, password):
        """SSH mkdir + script upload. Emits status_changed('rsync connected') or failed(err)."""
        self._emit_status("connecting...", "#ffd740")
        threading.Thread(
            target=self._do_connect, args=(addr, rpath, password), daemon=True
        ).start()

    def upload(self, filepath: str, dest: str, log_content: str, fname_short: str,
               addr: str, rpath: str, gating_csv_content: str = None):
        """rsync file to dest, then upload log + gating CSV + run ROOT conversion.

        Emits proc_created(proc) on the GUI thread shortly after rsync starts,
        so callers can attach the proc to RsyncToast for cancel support.
        """
        threading.Thread(
            target=self._do_rsync,
            args=(filepath, dest, log_content, fname_short, addr, rpath, self._password, gating_csv_content),
            daemon=True
        ).start()

    # ── connect internals ─────────────────────────────────────────────────────

    def _do_connect(self, addr, rpath, password):
        import os as _os
        _test_timeout = ['-o', 'ConnectTimeout=3']
        mkdir_cmd = (
            f'mkdir -p "{rpath}/raw" "{rpath}/root" "{rpath}/scripts" "{rpath}/log" "{rpath}/gating"'
        )
        if password:
            result = subprocess.run(
                ['sshpass', '-p', password, 'ssh']
                + _PWD_SSH_OPTS + _test_timeout + [addr, mkdir_cmd],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        else:
            result = subprocess.run(
                ['ssh'] + _KEY_SSH_OPTS + _test_timeout + [addr, mkdir_cmd],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        err = result.stderr.decode(errors='replace').strip()
        if result.returncode != 0:
            self._connected = False
            self._password  = None
            self.failed.emit(err)
            return

        _proj_root = _os.path.normpath(
            _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')
        )
        scripts = [
            _os.path.join(_proj_root, 'StdEventMonitor_fast.py'),
            _os.path.join(_proj_root, 'run_with_stats.py'),
            _os.path.join(_proj_root, 'check_gating_consistency.py'),
        ]
        script_dest = f"{addr}:{rpath}/scripts/"
        if password:
            rsync_result = subprocess.run(
                ['sshpass', '-p', password, 'rsync', '-az',
                 '-e', 'ssh ' + ' '.join(_PWD_SSH_OPTS)]
                + scripts + [script_dest],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        else:
            rsync_result = subprocess.run(
                ['rsync', '-az'] + scripts + [script_dest],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        if rsync_result.returncode != 0:
            err = rsync_result.stderr.decode(errors='replace').strip()
            self._connected = False
            self._password  = None
            self.failed.emit(f"Script upload failed: {err}")
            return

        self._password  = password
        self._connected = True
        self.status_changed.emit("rsync connected", "#69f0ae")

    # ── upload internals ──────────────────────────────────────────────────────

    def _stream_rsync(self, proc):
        for raw in proc.stdout:
            line = raw.decode('utf-8', errors='replace').rstrip()
            m = _RSYNC_PCT_RE.search(line)
            if m:
                self.progress.emit(m.group(1), m.group(2))
        proc.wait()
        return proc.returncode, proc.stderr.read()

    def _do_rsync(self, filepath, dest, log_content, fname_short, addr, rpath, password, gating_csv_content=None):
        import time as _time
        t0 = _time.monotonic()
        if password:
            proc = subprocess.Popen(
                ['sshpass', '-p', password, 'rsync', '-az', '--progress',
                 '-e', 'ssh ' + ' '.join(_PWD_SSH_OPTS + _SSH_TIMEOUT_OPTS),
                 filepath, dest],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        else:
            proc = subprocess.Popen(
                ['rsync', '-az', '--progress',
                 '-e', 'ssh ' + ' '.join(_SSH_TIMEOUT_OPTS),
                 filepath, dest],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        self.proc_created.emit(proc)

        returncode, err = self._stream_rsync(proc)
        elapsed = _time.monotonic() - t0
        rm, rs = divmod(elapsed, 60)
        elapsed_str = f"{int(rm):02d}:{rs:04.1f}"

        if returncode == 0:
            ok_detail = f"Sent to {dest.split(':')[0]}  ({elapsed_str})"
            self.done.emit("ok", ok_detail)
            threading.Thread(
                target=self._upload_log_and_monitor,
                args=(fname_short, log_content, addr, rpath, password, gating_csv_content),
                daemon=True
            ).start()
        else:
            err_msg = err.decode(errors='replace').strip()
            if (returncode == 23
                    or 'auth' in err_msg.lower()
                    or 'permission denied' in err_msg.lower()
                    or 'password' in err_msg.lower()):
                detail = f"Authentication failed — reconnect required\n{err_msg[:120]}"
            else:
                detail = f"Exit code {returncode}\n{err_msg[:120]}"
            self._connected = False
            self._password  = None
            self.status_changed.emit("rsync fail", "#ef5350")
            self.done.emit("error", detail)

    def _upload_log_and_monitor(self, fname, log_content, addr, rpath, password, gating_csv_content=None):
        import os as _os, tempfile as _tempfile
        fname_base     = _os.path.splitext(fname)[0]
        remote_log     = f"{rpath}/log/{fname_base}.log"
        remote_raw     = f"{rpath}/raw/{fname}"
        remote_root    = f"{rpath}/root/{fname_base}.root"
        remote_gating  = f"{rpath}/gating/{fname_base}_gating.csv"
        remote_wrapper = f"{rpath}/scripts/run_with_stats.py"

        # step 1: rsync program log
        with _tempfile.NamedTemporaryFile(
            mode='w', suffix='.log', delete=False, encoding='utf-8'
        ) as tf:
            tf.write(log_content)
            tmp_path = tf.name
        log_dest = f"{addr}:{remote_log}"
        if password:
            r = subprocess.run(
                ['sshpass', '-p', password, 'rsync', '-az',
                 '-e', 'ssh ' + ' '.join(_PWD_SSH_OPTS),
                 tmp_path, log_dest],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        else:
            r = subprocess.run(
                ['rsync', '-az', tmp_path, log_dest],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        _os.unlink(tmp_path)
        if r.returncode == 0:
            print(f"[log] done → {remote_log}")
        else:
            print(f"[log] ERROR: {r.stderr.decode(errors='replace').strip()}")

        # step 1b: rsync FPGA-gating position CSV (\\xFE/\\xEF timestamps + Zaber position)
        if gating_csv_content:
            with _tempfile.NamedTemporaryFile(
                mode='w', suffix='.csv', delete=False, encoding='utf-8'
            ) as gf:
                gf.write(gating_csv_content)
                gating_tmp_path = gf.name
            gating_dest = f"{addr}:{remote_gating}"
            if password:
                gr = subprocess.run(
                    ['sshpass', '-p', password, 'rsync', '-az',
                     '-e', 'ssh ' + ' '.join(_PWD_SSH_OPTS),
                     gating_tmp_path, gating_dest],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            else:
                gr = subprocess.run(
                    ['rsync', '-az', gating_tmp_path, gating_dest],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
            _os.unlink(gating_tmp_path)
            if gr.returncode == 0:
                print(f"[gating] done → {remote_gating}")
            else:
                print(f"[gating] ERROR: {gr.stderr.decode(errors='replace').strip()}")

        # step 2: SSH run_with_stats
        cmd = (
            f'set -o pipefail; ~/sutpct-env/bin/python3 "{remote_wrapper}"'
            f' "{remote_raw}" -o "{remote_root}"'
            f' 2>&1 | tee -a "{remote_log}"'
        )
        if password:
            result = subprocess.run(
                ['sshpass', '-p', password, 'ssh'] + _PWD_SSH_OPTS + [addr, cmd],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        else:
            result = subprocess.run(
                ['ssh'] + _KEY_SSH_OPTS + [addr, cmd],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        if result.returncode == 0:
            self.done.emit("monitor_ok", f"{fname_base}.root")
        else:
            err_msg = result.stdout.decode(errors='replace').strip()
            self.done.emit("monitor_error", err_msg[:200])
