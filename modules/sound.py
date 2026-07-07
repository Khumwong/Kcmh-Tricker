# modules/sound.py — non-blocking audio playback via QMediaPlayer
import os
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtCore import QUrl, QTimer

_player = None

def _get():
    global _player
    if _player is None:
        _player = QMediaPlayer()
    return _player

def play(path, stop_after_ms=None):
    """Play an audio file. Must be called from the main Qt thread."""
    try:
        p = _get()
        p.stop()
        p.setMedia(QMediaContent(QUrl.fromLocalFile(os.path.abspath(path))))
        p.play()
        if stop_after_ms is not None:
            QTimer.singleShot(stop_after_ms, p.stop)
    except Exception as e:
        print(f"[sound] play error: {e}")

def stop():
    if _player is not None:
        _player.stop()
