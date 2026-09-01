"""Deterministic per-slot Shorts production and publish scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from moduli.publish_scheduler import (
    format_youtube_publish_at,
    infer_audience_timezone,
    validate_publish_timestamp,
)
from moduli.shorts.config import ShortsConfig, load_config

_SLOT_LABELS = ("morning", "afternoon", "evening")


@dataclass
class ShortsScheduleDecision:
    publish_at_utc: datetime
    audience_timezone: str
    local_publish_label: str
    slot_index: int
    confidence: str
    fallback_used: bool
    analytics_available: bool
    source: str
    reason: str
    youtube_publish_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_at_utc": self.publish_at_utc.isoformat(),
            "youtube_publish_at": self.youtube_publish_at,
            "audience_timezone": self.audience_timezone,
            "local_publish_label": self.local_publish_label,
            "slot_index": self.slot_index,
            "confidence": self.confidence,
            "fallback_used": self.fallback_used,
            "analytics_available": self.analytics_available,
            "source": self.source,
            "reason": self.reason,
        }


def slot_label(slot_index: int) -> str:
    if 0 <= slot_index < len(_SLOT_LABELS):
        return _SLOT_LABELS[slot_index]
    return f"slot {slot_index + 1}"


def production_hours_local(cfg: ShortsConfig | None = None) -> list[int]:
    cfg = cfg or load_config()
    return list(cfg.production_hours or [10, 15, 20])


def _audience_tz(cfg: ShortsConfig) -> tuple[ZoneInfo, str]:
    try:
        return ZoneInfo(cfg.timezone), cfg.timezone
    except Exception:
        return ZoneInfo("Asia/Kolkata"), "Asia/Kolkata"


def missed_slots_today(
    now_utc: datetime | None = None,
    *,
    config: ShortsConfig | None = None,
    state: dict | None = None,
) -> list[int]:
    """Production slots whose hour already passed today without a successful Short."""
    from moduli.shorts.state import completed_slots_today, load_state

    cfg = config or load_config()
    state = state or load_state()
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tz, _ = _audience_tz(cfg)
    now_local = now_utc.astimezone(tz)
    done = completed_slots_today(state, now_utc=now_utc)
    missed = []
    for slot, hour in enumerate(production_hours_local(cfg)[: cfg.per_day]):
        if slot in done:
            continue
        if now_local.hour > hour or (now_local.hour == hour and now_local.minute > 0):
            missed.append(slot)
    return missed


def next_slot_to_produce(
    now_utc: datetime | None = None,
    *,
    config: ShortsConfig | None = None,
    state: dict | None = None,
) -> tuple[int, str] | None:
    """
    Return (slot_index, reason) for the next Short to produce, or None.

    Missed windows are caught up first (earliest missed slot), then the
    current scheduled hour if it matches.
    """
    from moduli.shorts.state import load_state, runs_today

    cfg = config or load_config()
    state = state or load_state()
    if not cfg.enabled or not state.get("enabled", True):
        return None
    if runs_today(state, now_utc=now_utc) >= cfg.per_day:
        return None

    missed = missed_slots_today(now_utc, config=cfg, state=state)
    if missed:
        return missed[0], "catch-up"

    slot = should_produce_short_now(now_utc, config=cfg, state=state)
    if slot is not None:
        return slot, "scheduled"
    return None


def should_produce_short_now(
    now_utc: datetime | None = None,
    *,
    config: ShortsConfig | None = None,
    state: dict | None = None,
) -> int | None:
    """
    Return the slot index (0, 1, 2…) to produce now, or None.

    Each slot fires once per day when the local audience clock hits that
  slot's production hour (morning / afternoon / evening).
    """
    from moduli.shorts.state import completed_slots_today, load_state, runs_today

    cfg = config or load_config()
    state = state or load_state()
    if not cfg.enabled or not state.get("enabled", True):
        return None

    if runs_today(state, now_utc=now_utc) >= cfg.per_day:
        return None

    hours = production_hours_local(cfg)
    if not hours:
        return None

    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tz, _ = _audience_tz(cfg)
    current_hour = now_utc.astimezone(tz).hour
    done_slots = completed_slots_today(state, now_utc=now_utc)

    for slot, hour in enumerate(hours[: cfg.per_day]):
        if hour == current_hour and slot not in done_slots:
            return slot
    return None


def next_production_slots(cfg: ShortsConfig | None = None) -> list[dict]:
    """Human-readable upcoming production windows in audience local time."""
    cfg = cfg or load_config()
    tz, tz_name = _audience_tz(cfg)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    rows = []
    for i, hour in enumerate(production_hours_local(cfg)[: cfg.per_day]):
        candidate = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(days=1)
        rows.append({
            "slot": i,
            "label": slot_label(i),
            "local_hour": hour,
            "local_time": candidate.strftime(f"%Y-%m-%d %H:%M {tz_name}"),
        })
    return rows


def _next_local_slot(
    tz: ZoneInfo,
    hour: int,
    minute: int,
    *,
    now_utc: datetime,
) -> datetime:
    now_local = now_utc.astimezone(tz)
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _confidence(video_count: int, activity: dict | None, min_videos: int) -> tuple[str, bool]:
    has_data = bool(activity and activity.get("has_data"))
    if video_count < 6 or not has_data:
        return "LOW", True
    if video_count < 16:
        return "MEDIUM", False
    return "HIGH", False


def compute_shorts_schedule(
    slot_index: int = 0,
    *,
    now: datetime | None = None,
    activity: dict | None = None,
    geography: dict | None = None,
    profiles_count: int = 0,
    config: ShortsConfig | None = None,
    producing_now: bool = True,
) -> ShortsScheduleDecision:
    """
    Publish time for a Short.

    When producing_now=True (default), publish shortly after render completes
    — the Short was made for this morning/afternoon/evening window.
    """
    cfg = config or load_config()
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    countries = (geography or {}).get("countries") or []
    provinces = (geography or {}).get("provinces") or []
    audience_tz_name, basis = infer_audience_timezone(
        countries,
        provinces=provinces,
        fallback=cfg.timezone,
    )
    try:
        tz = ZoneInfo(audience_tz_name)
    except Exception:
        audience_tz_name = cfg.timezone
        tz = ZoneInfo(audience_tz_name)
        basis = "configured default timezone"

    confidence, use_fallback = _confidence(profiles_count, activity, cfg.analytics_min_videos)
    analytics_available = bool(activity and activity.get("has_data"))

    fallback_hours = cfg.fallback_hours or production_hours_local(cfg)
    hour = fallback_hours[slot_index % len(fallback_hours)]
    minute = 0
    source = "produce_now"
    reason = ""

    if producing_now:
        lead = max(5, int(cfg.publish_lead_minutes))
        publish_at_utc = now_utc + timedelta(minutes=lead)
        publish_at_utc = validate_publish_timestamp(publish_at_utc, now_utc=now_utc)
        reason = (
            f"{slot_label(slot_index)} slot — produced now, "
            f"publish in ~{lead} min ({audience_tz_name})"
        )
    else:
        source = "fallback"
        reason = f"Fallback slot {slot_index}: {hour:02d}:00 {audience_tz_name}"
        if not use_fallback and analytics_available:
            buckets = activity.get("buckets") or []
            hours_ranked: dict[int, int] = {}
            for b in buckets:
                h = int(b.get("hour") or hour)
                hours_ranked[h] = hours_ranked.get(h, 0) + int(b.get("views") or 0)
            if hours_ranked:
                ranked = sorted(hours_ranked.keys(), key=lambda h: hours_ranked[h], reverse=True)
                hour = ranked[slot_index % len(ranked)]
                source = "analytics"
                reason = f"Shorts activity peak hour {hour:02d}:00 {audience_tz_name} ({basis})"
                use_fallback = False
        publish_at_utc = _next_local_slot(tz, hour, minute, now_utc=now_utc)
        publish_at_utc = validate_publish_timestamp(publish_at_utc, now_utc=now_utc)

    local_label = publish_at_utc.astimezone(tz).strftime(f"%Y-%m-%d %H:%M {audience_tz_name}")
    yt_at = format_youtube_publish_at(publish_at_utc)

    print(
        f"[SHORTS_SCHEDULER] {slot_label(slot_index)} slot={slot_index} {local_label} "
        f"({yt_at}) confidence={confidence} source={source} — {reason}",
        flush=True,
    )

    return ShortsScheduleDecision(
        publish_at_utc=publish_at_utc,
        audience_timezone=audience_tz_name,
        local_publish_label=local_label,
        slot_index=slot_index,
        confidence=confidence,
        fallback_used=use_fallback and not producing_now,
        analytics_available=analytics_available,
        source=source,
        reason=reason,
        youtube_publish_at=yt_at,
    )


def resolve_shorts_trigger_hours(config: ShortsConfig | None = None) -> list[int]:
    """Legacy helper — returns local production hours (not UTC)."""
    return production_hours_local(config)
