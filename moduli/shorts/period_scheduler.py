"""Dynamic morning / afternoon / evening Shorts slots from YouTube audience activity."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from moduli.publish_scheduler import (
    _activity_has_signal,
    _scheduling_confidence,
    infer_audience_timezone,
    load_scheduler_config,
)
from moduli.shorts.config import ShortsConfig, load_config

_SLOT_LABELS = ("morning", "afternoon", "evening")

# Local audience hours inclusive for each daily Short slot
_DEFAULT_PERIODS: tuple[tuple[str, int, int], ...] = (
    ("morning", 5, 11),
    ("afternoon", 12, 16),
    ("evening", 17, 22),
)


@dataclass
class ShortsSlotWindow:
    slot_index: int
    label: str
    hour: int
    minute: int = 0
    period_start: int = 0
    period_end: int = 0
    views: int = 0
    source: str = "fallback"  # analytics | fallback | static


@dataclass
class ShortsDailyPlan:
    slots: list[ShortsSlotWindow] = field(default_factory=list)
    audience_timezone: str = "Asia/Kolkata"
    confidence: str = "LOW"
    fallback_used: bool = True
    analytics_available: bool = False
    source: str = "fallback"
    reason: str = ""
    date_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_key": self.date_key,
            "audience_timezone": self.audience_timezone,
            "confidence": self.confidence,
            "fallback_used": self.fallback_used,
            "analytics_available": self.analytics_available,
            "source": self.source,
            "reason": self.reason,
            "slots": [
                {
                    "slot_index": s.slot_index,
                    "label": s.label,
                    "hour": s.hour,
                    "minute": s.minute,
                    "period_start": s.period_start,
                    "period_end": s.period_end,
                    "views": s.views,
                    "source": s.source,
                }
                for s in self.slots
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ShortsDailyPlan | None:
        if not data or not data.get("slots"):
            return None
        slots = [
            ShortsSlotWindow(
                slot_index=int(s.get("slot_index", i)),
                label=str(s.get("label") or _SLOT_LABELS[i] if i < 3 else f"slot{i}"),
                hour=int(s.get("hour", 0)),
                minute=int(s.get("minute", 0)),
                period_start=int(s.get("period_start", 0)),
                period_end=int(s.get("period_end", 0)),
                views=int(s.get("views", 0)),
                source=str(s.get("source", "fallback")),
            )
            for i, s in enumerate(data.get("slots") or [])
        ]
        return cls(
            slots=slots,
            audience_timezone=str(data.get("audience_timezone") or "Asia/Kolkata"),
            confidence=str(data.get("confidence", "LOW")),
            fallback_used=bool(data.get("fallback_used", True)),
            analytics_available=bool(data.get("analytics_available", False)),
            source=str(data.get("source", "fallback")),
            reason=str(data.get("reason", "")),
            date_key=str(data.get("date_key", "")),
        )


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def dynamic_schedule_enabled() -> bool:
    return _bool_env("SHORTS_DYNAMIC_SCHEDULE", True)


def _period_bounds() -> list[tuple[str, int, int]]:
    """Parse SHORTS_PERIOD_MORNING=5,11 style env overrides."""
    periods: list[tuple[str, int, int]] = []
    env_keys = (
        ("morning", "SHORTS_PERIOD_MORNING"),
        ("afternoon", "SHORTS_PERIOD_AFTERNOON"),
        ("evening", "SHORTS_PERIOD_EVENING"),
    )
    defaults = {label: (start, end) for label, start, end in _DEFAULT_PERIODS}
    for label, env_name in env_keys:
        raw = os.environ.get(env_name, "").strip()
        if raw and "," in raw:
            a, _, b = raw.partition(",")
            try:
                start, end = int(a.strip()), int(b.strip())
                periods.append((label, start, end))
                continue
            except ValueError:
                pass
        start, end = defaults[label]
        periods.append((label, start, end))
    return periods


def _min_slot_gap_hours() -> int:
    try:
        return max(2, int(os.environ.get("SHORTS_MIN_SLOT_GAP_HOURS", "4")))
    except (TypeError, ValueError):
        return 4


def _hour_gap(a: int, b: int) -> int:
    diff = abs(a - b)
    return min(diff, 24 - diff)


def _aggregate_hour_views(activity: dict | None) -> dict[int, int]:
    """Sum viewer activity across all day-of-week buckets per local hour."""
    totals: dict[int, int] = {}
    for bucket in (activity or {}).get("buckets") or []:
        try:
            hour = int(bucket.get("hour"))
            views = int(bucket.get("views") or 0)
        except (TypeError, ValueError):
            continue
        if views <= 0:
            continue
        totals[hour] = totals.get(hour, 0) + views
    return totals


def _hours_in_period(start: int, end: int) -> list[int]:
    if start <= end:
        return list(range(start, end + 1))
    # wrap midnight (not expected for Shorts periods)
    return list(range(start, 24)) + list(range(0, end + 1))


def _rank_hours_in_period(
    hour_views: dict[int, int],
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    ranked: list[tuple[int, int]] = []
    for hour in _hours_in_period(start, end):
        views = hour_views.get(hour, 0)
        if views > 0:
            ranked.append((hour, views))
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return ranked


def _respects_gap(candidate: int, chosen: list[int], min_gap: int) -> bool:
    for h in chosen:
        if _hour_gap(candidate, h) < min_gap:
            return False
    return True


def _nearest_valid_hour_in_period(
    hour: int,
    period_start: int,
    period_end: int,
    anchors: list[int],
    min_gap: int,
    hour_views: dict[int, int],
) -> int:
    """Move to the closest in-period hour that satisfies min gap (prefer higher views)."""
    period_hours = sorted(_hours_in_period(period_start, period_end))

    def sort_key(h: int) -> tuple:
        gap_ok = _respects_gap(h, anchors, min_gap)
        return (0 if gap_ok else 1, abs(h - hour), -hour_views.get(h, 0))

    for candidate in sorted(period_hours, key=sort_key):
        if _respects_gap(candidate, anchors, min_gap):
            return candidate
    return hour


def _rebalance_slots_for_gap(
    slots: list[ShortsSlotWindow],
    *,
    min_gap: int,
    hour_views: dict[int, int],
) -> None:
    """
    If analytics picks violate min gap, nudge the weaker slot (lower views)
    to the nearest valid hour inside its morning/afternoon/evening period.
    """
    changed = True
    guard = 0
    while changed and guard < 24:
        guard += 1
        changed = False
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                if _hour_gap(slots[i].hour, slots[j].hour) >= min_gap:
                    continue
                weaker_idx = i if slots[i].views <= slots[j].views else j
                weaker = slots[weaker_idx]
                anchors = [slots[k].hour for k in range(len(slots)) if k != weaker_idx]
                new_hour = _nearest_valid_hour_in_period(
                    weaker.hour,
                    weaker.period_start,
                    weaker.period_end,
                    anchors,
                    min_gap,
                    hour_views,
                )
                if new_hour != weaker.hour:
                    weaker.hour = new_hour
                    weaker.views = hour_views.get(new_hour, weaker.views)
                    changed = True


def _pick_slot_hour(
    *,
    ranked: list[tuple[int, int]],
    hour_views: dict[int, int],
    fallback_hour: int,
    period_start: int,
    period_end: int,
    chosen_hours: list[int],
    min_gap: int,
) -> tuple[int, int, str]:
    """Return (hour, views, source)."""
    for hour, views in ranked:
        if _respects_gap(hour, chosen_hours, min_gap):
            return hour, views, "analytics"

    period_hours = sorted(_hours_in_period(period_start, period_end))
    if fallback_hour not in period_hours:
        fallback_hour = period_hours[len(period_hours) // 2]

    candidates = [fallback_hour] + [h for h in period_hours if h != fallback_hour]
    seen: set[int] = set()
    for hour in candidates:
        if hour in seen:
            continue
        seen.add(hour)
        if _respects_gap(hour, chosen_hours, min_gap):
            return hour, hour_views.get(hour, 0), "fallback"

    return fallback_hour, hour_views.get(fallback_hour, 0), "fallback"


def _static_plan(cfg: ShortsConfig, *, date_key: str, reason: str) -> ShortsDailyPlan:
    periods = _period_bounds()
    slots: list[ShortsSlotWindow] = []
    hours = (cfg.production_hours or cfg.fallback_hours or [10, 15, 20])[: cfg.per_day]
    fallbacks = (cfg.fallback_hours or hours)[: cfg.per_day]
    for i, hour in enumerate(hours):
        label, p_start, p_end = periods[i] if i < len(periods) else (f"slot{i}", 0, 23)
        slots.append(
            ShortsSlotWindow(
                slot_index=i,
                label=label,
                hour=hour,
                period_start=p_start,
                period_end=p_end,
                source="static",
            )
        )
    return ShortsDailyPlan(
        slots=slots,
        audience_timezone=cfg.timezone,
        confidence="LOW",
        fallback_used=True,
        analytics_available=False,
        source="static",
        reason=reason or "static production hours from config",
        date_key=date_key,
    )


def resolve_daily_slot_plan(
    *,
    config: ShortsConfig | None = None,
    activity: dict | None = None,
    geography: dict | None = None,
    profiles_count: int = 0,
    now_utc: datetime | None = None,
    state: dict | None = None,
    force_refresh: bool = False,
) -> ShortsDailyPlan:
    """
    Pick morning / afternoon / evening production hours for today.

    Uses YouTube 'when your viewers are on YouTube' activity when signal is
    strong enough; otherwise predefined fallback hours per period.
  Never raises.
    """
    cfg = config or load_config()
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)

    countries = (geography or {}).get("countries") or []
    provinces = (geography or {}).get("provinces") or []
    audience_tz_name, _basis = infer_audience_timezone(
        countries,
        provinces=provinces,
        fallback=cfg.timezone,
    )
    try:
        ZoneInfo(audience_tz_name)
    except Exception:
        audience_tz_name = cfg.timezone

    date_key = now_utc.astimezone(ZoneInfo(audience_tz_name)).strftime("%Y-%m-%d")

    if state and not force_refresh:
        cached = state.get("daily_slot_plan") or {}
        if cached.get("date_key") == date_key:
            plan = ShortsDailyPlan.from_dict(cached)
            if plan and len(plan.slots) >= cfg.per_day:
                return plan

    if not dynamic_schedule_enabled():
        return _static_plan(cfg, date_key=date_key, reason="SHORTS_DYNAMIC_SCHEDULE=0")

    sched_cfg = load_scheduler_config()
    analytics_available = bool(activity and activity.get("has_data"))
    confidence, use_fallback = _scheduling_confidence(
        profiles_count,
        activity,
        sched_cfg,
    )
    # Shorts-specific floor: need enough Short uploads before trusting analytics
    if profiles_count < cfg.analytics_min_videos:
        use_fallback = True
        if not confidence:
            confidence = "LOW"

    periods = _period_bounds()
    fallback_hours = (cfg.fallback_hours or cfg.production_hours or [10, 15, 20])[: cfg.per_day]
    while len(fallback_hours) < cfg.per_day:
        fallback_hours.append(fallback_hours[-1] if fallback_hours else 20)

    has_signal = _activity_has_signal(activity, sched_cfg) and not use_fallback
    hour_views = _aggregate_hour_views(activity) if has_signal else {}

    chosen: list[int] = []
    slots: list[ShortsSlotWindow] = []
    min_gap = _min_slot_gap_hours()
    any_analytics = False

    for i in range(cfg.per_day):
        label, p_start, p_end = periods[i] if i < len(periods) else (f"slot{i}", 0, 23)
        fb_hour = fallback_hours[i]
        ranked = _rank_hours_in_period(hour_views, p_start, p_end) if has_signal else []

        if ranked:
            hour, views, source = _pick_slot_hour(
                ranked=ranked,
                hour_views=hour_views,
                fallback_hour=fb_hour,
                period_start=p_start,
                period_end=p_end,
                chosen_hours=chosen,
                min_gap=min_gap,
            )
            if source == "analytics":
                any_analytics = True
        else:
            hour, views, source = _pick_slot_hour(
                ranked=[],
                hour_views=hour_views,
                fallback_hour=fb_hour,
                period_start=p_start,
                period_end=p_end,
                chosen_hours=chosen,
                min_gap=min_gap,
            )

        chosen.append(hour)
        slots.append(
            ShortsSlotWindow(
                slot_index=i,
                label=label,
                hour=hour,
                period_start=p_start,
                period_end=p_end,
                views=views,
                source=source,
            )
        )

    if slots:
        _rebalance_slots_for_gap(slots, min_gap=min_gap, hour_views=hour_views)

    if any_analytics:
        source = "analytics"
        reason = (
            f"Peak viewer activity per period ({audience_tz_name}) — "
            f"morning/afternoon/evening >={min_gap}h apart"
        )
        fallback_used = False
    else:
        source = "fallback"
        if not analytics_available:
            reason = "insufficient YouTube audience activity — using fallback hours"
        elif profiles_count < cfg.analytics_min_videos:
            reason = (
                f"only {profiles_count} Shorts — need {cfg.analytics_min_videos} "
                "before analytics-driven schedule"
            )
        else:
            reason = "audience signal too weak — using fallback hours per period"
        fallback_used = True

    plan = ShortsDailyPlan(
        slots=slots[: cfg.per_day],
        audience_timezone=audience_tz_name,
        confidence=confidence,
        fallback_used=fallback_used,
        analytics_available=analytics_available,
        source=source,
        reason=reason,
        date_key=date_key,
    )

    print(
        "[SHORTS_SLOTS] "
        + " | ".join(
            f"{s.label} {s.hour:02d}:00 ({s.source}, views={s.views})"
            for s in plan.slots
        )
        + f" — {plan.reason}",
        flush=True,
    )
    return plan


def production_hours_from_plan(plan: ShortsDailyPlan, *, per_day: int = 3) -> list[int]:
    return [s.hour for s in plan.slots[:per_day]]
