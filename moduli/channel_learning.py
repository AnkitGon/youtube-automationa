"""
Persistent channel learning rollup — complements strategy_memory.json.

Summarizes scheduling outcomes, retention lessons, subscriber insights,
and topic-source performance without unbounded growth.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

CHANNEL_LEARNING_FILE = "channel_learning.json"
MAX_SCHEDULE_HISTORY = 40
MAX_SOURCE_STATS = 20

CATEGORY_REUSE_RULE = """=== CATEGORY vs SUBJECT (CRITICAL) ===
You MAY reuse a winning CATEGORY, FORMAT, TITLE PATTERN, or STORY TYPE.
You must NEVER reuse the same underlying SUBJECT, company, or story arc.

GOOD (same category, different subjects):
- How Nokia Lost the Smartphone War
- Why BlackBerry Lost to the iPhone
- How Kodak Missed the Digital Revolution

BAD (same subject — FORBIDDEN even with different wording):
- How Nokia Lost the Smartphone War
- Why Nokia Failed in the Smartphone Market
- The Real Reason Nokia Lost to Apple"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _empty() -> dict:
    return {
        "updated_at": None,
        "cycles": 0,
        "learning_stage": "cold_start",
        "publish_timing": {},
        "scheduling_history": [],
        "topic_source_stats": {},
        "retention_lessons": [],
        "subscriber_insights": {},
        "clickbait_traps": [],
        "content_quality_lessons": [],
    }


def save_channel_learning(data: dict) -> None:
    _save(data)


def load_channel_learning() -> dict:
    if not os.path.exists(CHANNEL_LEARNING_FILE):
        return _empty()
    try:
        with open(CHANNEL_LEARNING_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {**_empty(), **data}
    except Exception:
        return _empty()


def _save(data: dict) -> None:
    data["updated_at"] = _now()
    tmp = CHANNEL_LEARNING_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CHANNEL_LEARNING_FILE)


def describe_learning_stage(video_count: int) -> str:
    n = max(0, int(video_count))
    if n == 0:
        return (
            "Cold start — no published videos yet; strategy from preferences only. "
            "First video will seed topic memory + performance profiles."
        )
    if n == 1:
        return (
            "Video 1 complete — baseline collected. Topic + strategy registered; "
            "next run will analyze this video and adapt."
        )
    if n <= 2:
        return (
            f"Early learning (n={n}) — analyze prior video(s), weak signals only. "
            "Do not overfit; topic dedup is always enforced."
        )
    if n <= 5:
        return (
            f"Growing sample (n={n}) — compare performers, identify patterns. "
            "Reuse categories, never repeat subjects."
        )
    if n <= 9:
        return (
            f"Maturing channel (n={n}) — exploit winning formats with NEW entities. "
            "Controlled experiments active."
        )
    if n < 50:
        return (
            f"Established channel (n={n}) — statistical patterns drive strategy; "
            "exploit winners + test new ideas. Never repeat a topic."
        )
    return (
        f"Deep channel memory (n={n}) — audience-specific understanding accumulated."
    )


def category_reuse_reminder() -> str:
    return CATEGORY_REUSE_RULE


def run_daily_learning_update(
    profiles: list[dict],
    insights: dict,
    strategy: dict,
    state: dict | None = None,
) -> dict:
    """
    Called each pipeline cycle after analytics — updates channel_learning.json.
    """
    from moduli.publish_optimization import analyze_publish_timing, build_publish_strategy
    from moduli.subscriber_learning import analyze_subscriber_patterns
    from moduli.title_learning import analyze_title_patterns, refresh_clickbait_traps
    from moduli.script_optimization import analyze_script_optimization

    data = load_channel_learning()
    data["cycles"] = int(data.get("cycles", 0)) + 1
    vc = insights.get("video_count") or len(profiles)
    data["learning_stage"] = describe_learning_stage(vc)

    publish_analysis = analyze_publish_timing(profiles)
    pub_strategy = build_publish_strategy(profiles, state=state)
    data["publish_timing"] = {
        "best_hours_utc": pub_strategy.get("best_hours_utc", []),
        "best_time_window_utc": pub_strategy.get("best_time_window_utc"),
        "confidence": pub_strategy.get("confidence"),
        "sample_size": pub_strategy.get("sample_size"),
        "reason": pub_strategy.get("reason"),
        "windows": (publish_analysis.get("windows") or [])[:5],
    }

    sub = analyze_subscriber_patterns(profiles)
    data["subscriber_insights"] = {
        "has_data": sub.get("has_data"),
        "median_sub_rate": sub.get("channel_median_sub_rate"),
        "winning": (sub.get("winning_patterns") or [])[:5],
        "guidance": sub.get("guidance"),
    }

    title_analysis = analyze_title_patterns(profiles)
    traps = refresh_clickbait_traps(profiles)
    data["clickbait_traps"] = title_analysis.get("clickbait_traps") or []

    script_opt = analyze_script_optimization(profiles)
    lessons = list(data.get("retention_lessons") or [])
    for key in ("suggested", "retention_signals"):
        val = script_opt.get(key)
        if val:
            lessons.append(str(val)[:300])
    learning_summary = insights.get("learning_summary") or {}
    for card in (learning_summary.get("video_cards") or [])[:8]:
        diag = card.get("diagnosis") or ""
        if card.get("confidence") == "insufficient_data" or not diag:
            continue
        if "packaging" in diag.lower() or "overpromise" in diag or "retention" in diag.lower():
            lessons.append(f"{card.get('title', '')[:40]}: {diag}"[:200])
    cq = list(data.get("content_quality_lessons") or [])
    for card in (learning_summary.get("video_cards") or []):
        diag = card.get("diagnosis") or ""
        if "overpromise" in diag or "packaging" in diag.lower():
            entry = f"{card.get('title', '')[:40]}: {diag}"
            if entry not in cq:
                cq.append(entry)
    data["content_quality_lessons"] = cq[-20:]
    if lessons:
        data["retention_lessons"] = lessons[-12:]

    audience_lines = learning_summary.get("audience_summary") or []
    if audience_lines:
        data["audience_insights"] = audience_lines[:10]

    _save(data)
    return data


def record_scheduling_decision(
    *,
    video_id: str,
    scheduled_hour_utc: int,
    scheduled_day: str,
    predicted_window: dict | None,
    topic_source: str = "",
) -> None:
    """Record what time we chose and predicted performance window."""
    data = load_channel_learning()
    history = data.get("scheduling_history") or []
    history.append({
        "date": _now(),
        "video_id": video_id,
        "scheduled_hour_utc": scheduled_hour_utc,
        "scheduled_day": scheduled_day,
        "predicted_window": predicted_window or {},
        "topic_source": topic_source,
        "outcome_recorded": False,
    })
    data["scheduling_history"] = history[-MAX_SCHEDULE_HISTORY:]
    if topic_source:
        stats = data.get("topic_source_stats") or {}
        entry = stats.get(topic_source) or {"count": 0, "video_ids": []}
        entry["count"] = int(entry.get("count", 0)) + 1
        vids = list(entry.get("video_ids") or [])
        if video_id and video_id not in vids:
            vids.append(video_id)
        entry["video_ids"] = vids[-20:]
        stats[topic_source] = entry
        if len(stats) > MAX_SOURCE_STATS:
            oldest = sorted(stats.items(), key=lambda x: x[1].get("count", 0))[:1]
            for k, _ in oldest:
                stats.pop(k, None)
        data["topic_source_stats"] = stats
    _save(data)


def record_topic_source_outcome(topic_source: str, video_id: str, tier: str) -> None:
    """Update topic source stats when performance tier is known."""
    data = load_channel_learning()
    stats = data.get("topic_source_stats") or {}
    entry = stats.get(topic_source) or {"count": 0, "outcomes": []}
    outcomes = list(entry.get("outcomes") or [])
    outcomes.append({"video_id": video_id, "tier": tier})
    entry["outcomes"] = outcomes[-15:]
    stats[topic_source] = entry
    data["topic_source_stats"] = stats
    _save(data)
