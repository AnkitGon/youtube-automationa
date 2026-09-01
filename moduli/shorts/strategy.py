"""Compact learned Shorts strategy for prompts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

STRATEGY_FILE = "shorts_strategy.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def default_strategy() -> dict:
    return {
        "updated_at": None,
        "cycles": 0,
        "rollup": {
            "winning_hooks": [],
            "losing_hooks": [],
            "winning_angles": [],
            "losing_angles": [],
            "winning_categories": [],
            "losing_categories": [],
            "winning_durations": [],
            "winning_publish_hours": [],
            "avoid_patterns": [],
            "lessons": [],
        },
    }


def load_strategy() -> dict:
    if not os.path.exists(STRATEGY_FILE):
        return default_strategy()
    try:
        with open(STRATEGY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        base = default_strategy()
        base.update(data)
        base.setdefault("rollup", default_strategy()["rollup"])
        return base
    except (OSError, json.JSONDecodeError):
        return default_strategy()


def save_strategy(data: dict) -> None:
    data["updated_at"] = _now()
    tmp = f"{STRATEGY_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STRATEGY_FILE)


def guidance_block(strategy: dict | None = None) -> str:
    strategy = strategy or load_strategy()
    rollup = strategy.get("rollup") or {}
    lines = ["SHORTS STRATEGY (learned from channel performance):"]

    for label, key in (
        ("Winning hooks", "winning_hooks"),
        ("Winning angles", "winning_angles"),
        ("Winning categories", "winning_categories"),
        ("Avoid", "avoid_patterns"),
        ("Lessons", "lessons"),
    ):
        items = rollup.get(key) or []
        if items:
            if isinstance(items[0], dict):
                vals = [str(i.get("value", i))[:80] for i in items[:5]]
            else:
                vals = [str(i)[:80] for i in items[:5]]
            lines.append(f"- {label}: {', '.join(vals)}")

    hours = rollup.get("winning_publish_hours") or []
    if hours:
        lines.append(f"- Best publish hours (local): {hours[:5]}")

    if len(lines) == 1:
        lines.append("- Insufficient Shorts data yet — prioritize strong hooks and standalone insights.")
    return "\n".join(lines)
