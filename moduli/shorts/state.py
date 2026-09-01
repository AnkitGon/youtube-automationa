"""Thread-safe shorts_state.json I/O."""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
STATE_FILE = "shorts_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def default_state() -> dict:
    return {
        "enabled": True,
        "per_day": 3,
        "runs_today": {},
        "queue": [],
        "last_batch_at": None,
        "last_schedule_decisions": [],
        "_scheduler_cache": {},
        "pipeline_status": None,
        "today_shorts": [],
        "failures": [],
        "pending_upload": None,
    }


def load_state() -> dict:
    with _LOCK:
        return _load()


def save_state(state: dict) -> None:
    with _LOCK:
        _save(state)


def _load() -> dict:
    if not os.path.exists(STATE_FILE):
        return default_state()
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default_state()
        base = default_state()
        base.update(data)
        return base
    except (OSError, json.JSONDecodeError):
        return default_state()


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


def completed_slots_today(
    state: dict | None = None,
    *,
    now_utc: datetime | None = None,
) -> set[int]:
    """Slot indices already produced successfully today."""
    state = state or load_state()
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    slots: set[int] = set()
    for row in state.get("today_shorts") or []:
        if row.get("date") != today:
            continue
        if "slot" in row:
            slots.add(int(row["slot"]))
    return slots


def runs_today(state: dict | None = None, *, now_utc: datetime | None = None) -> int:
    state = state or load_state()
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    return int((state.get("runs_today") or {}).get(today, 0))


def increment_runs_today(state: dict | None = None) -> None:
    state = dict(state or load_state())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    runs = {today: runs_today(state) + 1}
    state["runs_today"] = runs
    save_state(state)


def set_pipeline_status(step: str, slot: int = 0, pct: int | None = None) -> None:
    state = load_state()
    status = {"step": step, "slot": slot, "updated_at": _now()}
    if pct is not None:
        status["pct"] = pct
    state["pipeline_status"] = status
    save_state(state)


def clear_pipeline_status() -> None:
    state = load_state()
    state.pop("pipeline_status", None)
    save_state(state)


def record_failure(slot: int, reason: str, concept: dict | None = None) -> None:
    state = load_state()
    failures = state.get("failures") or []
    failures.append({
        "at": _now(),
        "slot": slot,
        "reason": reason[:500],
        "concept": (concept or {}).get("angle") or (concept or {}).get("topic", ""),
    })
    state["failures"] = failures[-30:]
    save_state(state)


def record_today_short(entry: dict) -> None:
    state = load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [r for r in (state.get("today_shorts") or []) if r.get("date") == today]
    rows.append({**entry, "date": today})
    state["today_shorts"] = rows[-20:]
    state.pop("pending_upload", None)
    save_state(state)


def save_pending_upload(
    slot: int,
    paths: dict,
    content: dict,
    concept: dict,
    schedule: dict,
) -> None:
    state = load_state()
    state["pending_upload"] = {
        "slot": slot,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "paths": paths,
        "content": {
            k: content.get(k)
            for k in (
                "title", "description", "tags", "hashtags", "hook", "script",
                "angle", "key_claims", "source_type",
            )
        },
        "concept": dict(concept or {}),
        "schedule": schedule,
    }
    save_state(state)


def clear_pending_upload() -> None:
    state = load_state()
    state.pop("pending_upload", None)
    save_state(state)


def get_pending_upload(slot: int | None = None) -> dict | None:
    state = load_state()
    pending = state.get("pending_upload")
    if not pending:
        return None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if pending.get("date") != today:
        clear_pending_upload()
        return None
    if slot is not None and pending.get("slot") != slot:
        return None
    video = (pending.get("paths") or {}).get("video")
    if not video or not os.path.exists(video):
        clear_pending_upload()
        return None
    return pending
