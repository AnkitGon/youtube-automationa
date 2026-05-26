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


def load_state() -> dict:
    with _LOCK:
        return _load()


def save_state(state: dict) -> None:
    with _LOCK:
        _save(state)


def _load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = f.read().strip()
        return json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError):
        backup = f"{STATE_FILE}.bak"
        if os.path.exists(backup):
            try:
                with open(backup, encoding="utf-8") as f:
                    data = f.read().strip()
                return json.loads(data) if data else {}
            except Exception:
                pass
        return {}


def _save(state: dict) -> None:
    backup = f"{STATE_FILE}.bak"
    tmp = f"{STATE_FILE}.tmp"
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                json.load(f)
            shutil.copy2(STATE_FILE, backup)
        except Exception:
            pass
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)
