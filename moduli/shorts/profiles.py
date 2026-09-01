"""Shorts performance profiles."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

PROFILES_FILE = "shorts_profiles.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def load_profiles() -> list[dict]:
    if not os.path.exists(PROFILES_FILE):
        return []
    try:
        with open(PROFILES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("profiles", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_profiles(profiles: list[dict]) -> None:
    tmp = f"{PROFILES_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PROFILES_FILE)


def upsert_profile(profile: dict) -> None:
    profiles = load_profiles()
    vid = profile.get("video_id")
    if not vid:
        return
    profiles = [p for p in profiles if p.get("video_id") != vid]
    profile.setdefault("content_type", "short")
    profile["updated_at"] = _now()
    profiles.append(profile)
    profiles.sort(key=lambda p: p.get("published_at") or "", reverse=True)
    save_profiles(profiles[:200])


def profile_by_id(video_id: str) -> dict | None:
    for p in load_profiles():
        if p.get("video_id") == video_id:
            return p
    return None
