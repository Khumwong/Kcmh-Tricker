import json
import os


class RunConfig:
    """Thin JSON-backed config store for RunWidget persistent settings."""

    def __init__(self, config_path: str):
        self._path = config_path
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self._path, 'r') as f:
                self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value

    def save(self):
        try:
            with open(self._path, 'w') as f:
                json.dump(self._data, f, indent=2)
        except Exception:
            pass
