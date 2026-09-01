"""Shorts content history and deduplication registry."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from moduli.shorts.config import load_config

HISTORY_FILE = "shorts_history.json"
MAX_ENTRIES = 500

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "how", "why", "what", "when", "where", "who", "that", "this", "is",
    "was", "are", "were", "be", "been", "it", "its", "you", "your", "we", "our",
})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def content_fingerprint(script: str) -> str:
    norm = normalize_text(script)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {"version": 1, "entries": []}
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "entries": []}
        data.setdefault("entries", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "entries": []}


def _save(data: dict) -> None:
    data["updated_at"] = _now()
    tmp = f"{HISTORY_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, HISTORY_FILE)


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()
    overlap = len(ta & tb)
    return overlap / max(len(ta), len(tb), 1)


def is_summary_of(source_topic: str, candidate: str) -> bool:
    """Detect lazy 'X in 60 seconds' summaries of long-form topics."""
    low = normalize_text(candidate)
    patterns = (
        r"\b\d+\s*second",
        r"\b60\s*second",
        r"\bin\s*60\b",
        r"\bquick\s+summary\b",
        r"\bsummary\s+of\b",
        r"\bfull\s+story\b",
    )
    if any(re.search(p, low) for p in patterns):
        src = _tokens(source_topic)
        cand = _tokens(candidate)
        if src and cand and (src & cand):
            return True
        if src and similarity(source_topic, candidate) >= 0.5:
            return True
    return False


def find_duplicate(
    *,
    topic: str,
    angle: str = "",
    hook: str = "",
    title: str = "",
    script: str = "",
    source_topic: str = "",
) -> tuple[bool, str, str]:
    """Returns (is_duplicate, matched_field, reason)."""
    cfg = load_config()
    threshold = cfg.similarity_threshold
    fp = content_fingerprint(script) if script else ""
    entries = load_history().get("entries") or []

    for entry in reversed(entries):
        if fp and entry.get("content_fingerprint") == fp:
            return True, entry.get("title", ""), "identical script fingerprint"

        for field, value in (
            ("hook", hook),
            ("angle", angle),
            ("topic", topic),
            ("title", title),
        ):
            if not value:
                continue
            for ef, ev in (
                ("hook", entry.get("hook", "")),
                ("angle", entry.get("angle", "")),
                ("topic", entry.get("topic", "")),
                ("title", entry.get("title", "")),
            ):
                if not ev:
                    continue
                # Same entity with a clearly different angle is allowed
                if field == "topic" and angle and entry.get("angle"):
                    if similarity(angle, entry.get("angle", "")) < 0.45:
                        continue
                if similarity(value, ev) >= threshold:
                    return True, ev, f"similar {field} to prior short"

        if source_topic and is_summary_of(source_topic, topic):
            return True, source_topic, "lazy summary of long-form topic"

    # Cross-check long-form titles (block same title, allow angles)
    if title:
        try:
            from moduli.topic_history import load_topic_history
            for entry in load_topic_history():
                lt = (entry.get("title") or "").strip()
                if lt and similarity(title, lt) >= 0.92:
                    return True, lt, "title matches long-form video"
        except Exception:
            pass

    return False, "", ""


def record_entry(
    *,
    topic: str,
    angle: str,
    hook: str,
    title: str,
    script: str,
    key_claims: list | None = None,
    source_type: str = "evergreen",
    source_topic: str = "",
    source_longform_video_id: str = "",
    video_id: str = "",
    duration_seconds: float = 0,
    status: str = "published",
) -> None:
    data = load_history()
    entries = data.get("entries") or []
    entries.append({
        "topic": topic,
        "normalized_topic": normalize_text(topic),
        "angle": angle,
        "hook": hook,
        "title": title,
        "key_claims": key_claims or [],
        "content_fingerprint": content_fingerprint(script),
        "source_type": source_type,
        "source_topic": source_topic,
        "source_longform_video_id": source_longform_video_id,
        "video_id": video_id,
        "published_at": _now(),
        "duration_seconds": duration_seconds,
        "status": status,
        "recorded_at": _now(),
    })
    data["entries"] = entries[-MAX_ENTRIES:]
    _save(data)


def recent_entries(limit: int = 20) -> list[dict]:
    return list(reversed((load_history().get("entries") or [])[-limit:]))
