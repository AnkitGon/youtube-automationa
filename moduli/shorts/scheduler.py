"""Deterministic per-slot Shorts production and publish scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from moduli.publish_scheduler import (
    format_youtube_publish_at,
    validate_publish_timestamp,
)
from moduli.shorts.config import ShortsConfig, load_config
from moduli.shorts.period_scheduler import (
    production_hours_from_plan,
    resolve_daily_slot_plan,
)

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


def production_hours_local(
    cfg: ShortsConfig | None = None,
    *,
    activity: dict | None = None,
    geography: dict | None = None,
    profiles_count: int = 0,
    state: dict | None = None,
) -> list[int]:
    cfg = cfg or load_config()
    plan = resolve_daily_slot_plan(
        config=cfg,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        state=state,
    )
    return production_hours_from_plan(plan, per_day=cfg.per_day)


def _audience_tz(cfg: ShortsConfig) -> tuple[ZoneInfo, str]:
    try:
        return ZoneInfo(cfg.timezone), cfg.timezone
    except Exception:
        return ZoneInfo("Asia/Kolkata"), "Asia/Kolkata"


def _scheduler_context(state: dict | None) -> tuple[dict | None, dict | None, int]:
    cache = (state or {}).get("_scheduler_cache") or {}
    return (
        cache.get("activity"),
        cache.get("geography"),
        int(cache.get("profiles_count") or 0),
    )


def skipped_slots_today(
    now_utc: datetime | None = None,
    *,
    config: ShortsConfig | None = None,
    state: dict | None = None,
) -> list[int]:
    """
    Slots whose production hour already passed today without a Short.
    Informational only — missed windows are NOT caught up.
    """
    from moduli.shorts.state import completed_slots_today, load_state

    cfg = config or load_config()
    state = state or load_state()
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tz, _ = _audience_tz(cfg)
    now_local = now_utc.astimezone(tz)
    done = completed_slots_today(state, now_utc=now_utc)
    skipped = []
    activity, geography, profiles_count = _scheduler_context(state)
    hours = production_hours_local(
        cfg,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        state=state,
    )
    for slot, hour in enumerate(hours[: cfg.per_day]):
        if slot in done:
            continue
        if now_local.hour > hour or (now_local.hour == hour and now_local.minute > 0):
            skipped.append(slot)
    return skipped


# Backward-compatible alias (no catch-up behavior)
missed_slots_today = skipped_slots_today


def next_slot_to_produce(
    now_utc: datetime | None = None,
    *,
    config: ShortsConfig | None = None,
    state: dict | None = None,
) -> tuple[int, str] | None:
    """
    Return (slot_index, reason) for the next Short to produce, or None.

    Only the current scheduled hour triggers production. Missed earlier windows
    are skipped for the day (no catch-up, no carry-forward to tomorrow).
    """
    from moduli.shorts.state import load_state, runs_today

    cfg = config or load_config()
    state = state or load_state()
    if not cfg.enabled or not state.get("enabled", True):
        return None
    if runs_today(state, now_utc=now_utc) >= cfg.per_day:
        return None

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

    activity, geography, profiles_count = _scheduler_context(state)
    hours = production_hours_local(
        cfg,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        state=state,
    )
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


def next_production_slots(
    cfg: ShortsConfig | None = None,
    *,
    state: dict | None = None,
) -> list[dict]:
    """Human-readable upcoming production windows in audience local time."""
    from moduli.shorts.state import load_state

    cfg = cfg or load_config()
    state = state or load_state()
    tz, tz_name = _audience_tz(cfg)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    activity, geography, profiles_count = _scheduler_context(state)
    plan = resolve_daily_slot_plan(
        config=cfg,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        state=state,
    )
    rows = []
    for win in plan.slots[: cfg.per_day]:
        candidate = now_local.replace(hour=win.hour, minute=win.minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(days=1)
        rows.append({
            "slot": win.slot_index,
            "label": win.label,
            "local_hour": win.hour,
            "local_time": candidate.strftime(f"%Y-%m-%d %H:%M {tz_name}"),
            "source": win.source,
            "views": win.views,
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
    """Deprecated — kept for backward-compatible imports."""
    has_data = bool(activity and activity.get("has_data"))
    if video_count < min_videos or not has_data:
        return "LOW", True
    if video_count < 16:
        return "MEDIUM", False
    return "HIGH", False


def refresh_shorts_scheduler_cache(state: dict | None = None, *, force: bool = False) -> dict:
    """
    Load YouTube viewer activity + geography for dynamic Shorts slots.
    Caches results in shorts_state.json (never raises).
    """
    from moduli.analytics import leggi_audience_activity
    from moduli.shorts.analytics import leggi_audience_geography, sync_shorts_profiles
    from moduli.shorts.state import load_state, save_state

    state = state or load_state()
    try:
        from moduli.shorts.config import load_config
        from zoneinfo import ZoneInfo

        cfg = load_config()
        tz = ZoneInfo(cfg.timezone)
        today = datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d")
        cached_plan = state.get("daily_slot_plan") or {}
        if cached_plan.get("date_key") and cached_plan.get("date_key") != today:
            state.pop("daily_slot_plan", None)

        profiles = sync_shorts_profiles()
        activity = leggi_audience_activity()
        geography = leggi_audience_geography()
        profiles_count = len(profiles)
        state["_scheduler_cache"] = {
            "activity": activity,
            "geography": geography,
            "profiles_count": profiles_count,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        plan = resolve_daily_slot_plan(
            activity=activity,
            geography=geography,
            profiles_count=profiles_count,
            state=state,
            force_refresh=force,
        )
        state["daily_slot_plan"] = plan.to_dict()
        save_state(state)
    except Exception as e:
        print(f"[shorts/scheduler] cache refresh failed (fallback schedule): {e}", flush=True)
    return state


def compute_shorts_schedule(
    slot_index: int = 0,
    *,
    now: datetime | None = None,
    activity: dict | None = None,
    geography: dict | None = None,
    profiles_count: int = 0,
    config: ShortsConfig | None = None,
    producing_now: bool = True,
    state: dict | None = None,
) -> ShortsScheduleDecision:
    """
    Publish time for a Short.

    When producing_now=True (default), publish shortly after render completes
    — the Short was made for this morning/afternoon/evening window.
    """
    cfg = config or load_config()
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    plan = resolve_daily_slot_plan(
        config=cfg,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        now_utc=now_utc,
        state=state,
    )
    audience_tz_name = plan.audience_timezone
    try:
        tz = ZoneInfo(audience_tz_name)
    except Exception:
        audience_tz_name = cfg.timezone
        tz = ZoneInfo(audience_tz_name)

    slot_win = plan.slots[slot_index] if slot_index < len(plan.slots) else None
    hour = slot_win.hour if slot_win else (cfg.fallback_hours or [10, 15, 20])[slot_index % 3]
    minute = slot_win.minute if slot_win else 0
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
        publish_at_utc = _next_local_slot(tz, hour, minute, now_utc=now_utc)
        publish_at_utc = validate_publish_timestamp(publish_at_utc, now_utc=now_utc)
        if slot_win and slot_win.source == "analytics":
            source = "analytics"
            reason = (
                f"{slot_win.label} peak viewer hour {hour:02d}:{minute:02d} "
                f"{audience_tz_name} (views={slot_win.views})"
            )
        else:
            source = "fallback"
            reason = plan.reason or f"Fallback {slot_label(slot_index)} {hour:02d}:00 {audience_tz_name}"

    local_label = publish_at_utc.astimezone(tz).strftime(f"%Y-%m-%d %H:%M {audience_tz_name}")
    yt_at = format_youtube_publish_at(publish_at_utc)

    print(
        f"[SHORTS_SCHEDULER] {slot_label(slot_index)} slot={slot_index} {local_label} "
        f"({yt_at}) confidence={plan.confidence} source={source} — {reason}",
        flush=True,
    )

    return ShortsScheduleDecision(
        publish_at_utc=publish_at_utc,
        audience_timezone=audience_tz_name,
        local_publish_label=local_label,
        slot_index=slot_index,
        confidence=plan.confidence,
        fallback_used=plan.fallback_used and not producing_now,
        analytics_available=plan.analytics_available,
        source=source,
        reason=reason,
        youtube_publish_at=yt_at,
    )


def next_manual_slot_index(
    state: dict | None = None,
    *,
    config: ShortsConfig | None = None,
) -> int:
    """Next slot index for a manual run (first not completed today)."""
    from moduli.shorts.state import completed_slots_today, load_state, runs_today

    cfg = config or load_config()
    state = state or load_state()
    done = completed_slots_today(state)
    for i in range(cfg.per_day):
        if i not in done:
            return i
    return runs_today(state)


def next_upcoming_planned_slot(
    *,
    config: ShortsConfig | None = None,
    state: dict | None = None,
    now_utc: datetime | None = None,
    activity: dict | None = None,
    geography: dict | None = None,
    profiles_count: int = 0,
) -> tuple[int, datetime] | None:
    """
    Next planned window (local time) for an incomplete slot today or tomorrow.
    Returns (slot_index, local_datetime) or None if all slots done.
    """
    from moduli.shorts.state import completed_slots_today, load_state

    cfg = config or load_config()
    state = state or load_state()
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    done = completed_slots_today(state, now_utc=now_utc)
    plan = resolve_daily_slot_plan(
        config=cfg,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        now_utc=now_utc,
        state=state,
    )
    try:
        tz = ZoneInfo(plan.audience_timezone)
    except Exception:
        tz = ZoneInfo(cfg.timezone)

    now_local = now_utc.astimezone(tz)
    best: tuple[int, datetime] | None = None
    for win in plan.slots[: cfg.per_day]:
        if win.slot_index in done:
            continue
        candidate = now_local.replace(
            hour=win.hour, minute=win.minute, second=0, microsecond=0,
        )
        if candidate <= now_local:
            candidate += timedelta(days=1)
        if best is None or candidate < best[1]:
            best = (win.slot_index, candidate)
    return best


def describe_manual_publish(
    publish_mode: str,
    *,
    slot_index: int,
    config: ShortsConfig | None = None,
    state: dict | None = None,
    activity: dict | None = None,
    geography: dict | None = None,
    profiles_count: int = 0,
    now_utc: datetime | None = None,
) -> str:
    """Human-readable publish plan for Telegram (/shorts now)."""
    cfg = config or load_config()
    if publish_mode == "next":
        upcoming = next_upcoming_planned_slot(
            config=cfg,
            state=state,
            now_utc=now_utc,
            activity=activity,
            geography=geography,
            profiles_count=profiles_count,
        )
        if not upcoming:
            return "no upcoming window — all slots done today"
        idx, local_dt = upcoming
        return (
            f"{slot_label(idx)} at {local_dt.strftime('%H:%M')} "
            f"{cfg.timezone} (next planned window)"
        )
    lead = max(5, int(cfg.publish_lead_minutes))
    return f"~{lead} min after render finishes ({slot_label(slot_index)} slot)"


def resolve_shorts_trigger_hours(
    config: ShortsConfig | None = None,
    *,
    state: dict | None = None,
) -> list[int]:
    """Legacy helper — returns local production hours (not UTC)."""
    from moduli.shorts.state import load_state

    state = state or load_state()
    activity, geography, profiles_count = _scheduler_context(state)
    return production_hours_local(
        config,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        state=state,
    )
