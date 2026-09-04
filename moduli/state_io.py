"""
Shared state.json I/O with threading lock.
Imported by both agent.py and telegram_handler.py so concurrent
reads/writes between pipeline thread and bot thread don't corrupt the file.
"""
import json
import os
import shutil
import threading

_LOCK = threading.Lock()
STATE_FILE = "state.json"


def _state_path() -> str:
    from moduli.paths import config_path
    return config_path(STATE_FILE)


def load_state() -> dict:
    with _LOCK:
        return _load()


def save_state(state: dict) -> None:
    with _LOCK:
        _save(state)


def _load() -> dict:
    path = _state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = f.read().strip()
        return json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError):
        backup = f"{path}.bak"
        if os.path.exists(backup):
            try:
                with open(backup, encoding="utf-8") as f:
                    data = f.read().strip()
                return json.loads(data) if data else {}
            except Exception:
                pass
        return {}


def _save(state: dict) -> None:
    path = _state_path()
    backup = f"{path}.bak"
    tmp = f"{path}.tmp"
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
            shutil.copy2(path, backup)
        except Exception:
            pass
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
