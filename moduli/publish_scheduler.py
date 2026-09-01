"""
Deterministic YouTube publish-time scheduler.

The local PC clock is only used to pick the *next* valid slot (must be in the
future).  Publication authority is YouTube via an explicit RFC3339 UTC publishAt.

Agent pipeline trigger hours are separate — see resolve_pipeline_trigger_hours().
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# ISO weekday: Monday=0 … Sunday=6 (Python)
_WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
)
# YouTube Analytics dayOfWeek: Sunday=1 … Saturday=7
_YT_DOW_TO_PY = {1: 6, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5}

# Dominant country → IANA timezone (refined for US via province when available)
_COUNTRY_TZ: dict[str, str] = {
    "GB": "Europe/London",
    "IE": "Europe/Dublin",
    "US": "America/New_York",
    "CA": "America/Toronto",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    "IN": "Asia/Kolkata",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "IT": "Europe/Rome",
    "ES": "Europe/Madrid",
    "NL": "Europe/Amsterdam",
    "BR": "America/Sao_Paulo",
    "MX": "America/Mexico_City",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "SG": "Asia/Singapore",
    "PH": "Asia/Manila",
    "ZA": "Africa/Johannesburg",
    "AE": "Asia/Dubai",
    "PL": "Europe/Warsaw",
    "SE": "Europe/Stockholm",
    "NO": "Europe/Oslo",
    "DK": "Europe/Copenhagen",
    "FI": "Europe/Helsinki",
    "PT": "Europe/Lisbon",
    "CH": "Europe/Zurich",
    "AT": "Europe/Vienna",
    "BE": "Europe/Brussels",
}

_US_PROVINCE_TZ: dict[str, str] = {
    "CA": "America/Los_Angeles",
    "WA": "America/Los_Angeles",
    "OR": "America/Los_Angeles",
    "NV": "America/Los_Angeles",
    "AZ": "America/Phoenix",
    "CO": "America/Denver",
    "TX": "America/Chicago",
    "IL": "America/Chicago",
    "NY": "America/New_York",
    "NJ": "America/New_York",
    "FL": "America/New_York",
    "GA": "America/New_York",
    "MA": "America/New_York",
    "PA": "America/New_York",
    "MI": "America/Detroit",
    "HI": "Pacific/Honolulu",
    "AK": "America/Anchorage",
}


@dataclass
class SchedulerConfig:
    default_publish_time: str = "18:00"
    default_publish_timezone: str = "Asia/Kolkata"
    default_publish_days: list[int] = field(default_factory=list)  # empty = any day
    analytics_min_videos: int = 3
    analytics_rolling_videos: int = 10
    lead_minutes: int = 0
    pipeline_trigger_hours: list[int] = field(default_factory=lambda: [14])
    activity_min_views: int = 50
    activity_min_buckets: int = 4
    stability_max_hour_shift: int = 2  # max hour change unless HIGH confidence


@dataclass
class ScheduleDecision:
    publish_at_utc: datetime
    audience_timezone: str
    local_publish_label: str
    peak_day: str | None
    peak_hour_local: int | None
    confidence: str  # LOW | MEDIUM | HIGH
    fallback_used: bool
    analytics_available: bool
    source: str  # fallback | analytics | manual
    reason: str
    audience_basis: str
    utc_label: str
    youtube_publish_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_at_utc": self.publish_at_utc.isoformat(),
            "youtube_publish_at": self.youtube_publish_at,
            "audience_timezone": self.audience_timezone,
            "local_publish_label": self.local_publish_label,
            "peak_day": self.peak_day,
            "peak_hour_local": self.peak_hour_local,
            "confidence": self.confidence,
            "fallback_used": self.fallback_used,
            "analytics_available": self.analytics_available,
            "source": self.source,
            "reason": self.reason,
            "audience_basis": self.audience_basis,
            "utc_label": self.utc_label,
        }


def load_scheduler_config() -> SchedulerConfig:
    days_raw = os.environ.get("DEFAULT_PUBLISH_DAYS", "").strip()
    days: list[int] = []
    if days_raw:
        for part in days_raw.split(","):
            part = part.strip()
            if part.isdigit():
                days.append(int(part))
            else:
                for i, name in enumerate(_WEEKDAY_NAMES):
                    if name.lower().startswith(part.lower()):
                        days.append(i)
                        break

    trigger_raw = os.environ.get("PIPELINE_TRIGGER_HOURS", "14").strip()
    triggers = [int(h) for h in trigger_raw.split(",") if h.strip().isdigit()]
    if not triggers:
        triggers = [14]

    return SchedulerConfig(
        default_publish_time=os.environ.get("DEFAULT_PUBLISH_TIME", "18:00").strip() or "18:00",
        default_publish_timezone=os.environ.get(
            "DEFAULT_PUBLISH_TIMEZONE", "Asia/Kolkata"
        ).strip()
        or "Asia/Kolkata",
        default_publish_days=days,
        analytics_min_videos=int(os.environ.get("ANALYTICS_MIN_VIDEOS_FOR_SCHEDULING", "3")),
        analytics_rolling_videos=int(os.environ.get("ANALYTICS_ROLLING_VIDEOS", "10")),
        lead_minutes=int(os.environ.get("SCHEDULER_LEAD_MINUTES", "0")),
        pipeline_trigger_hours=triggers,
        activity_min_views=int(os.environ.get("SCHEDULER_ACTIVITY_MIN_VIEWS", "50")),
        activity_min_buckets=int(os.environ.get("SCHEDULER_ACTIVITY_MIN_BUCKETS", "4")),
        stability_max_hour_shift=int(os.environ.get("SCHEDULER_MAX_HOUR_SHIFT", "2")),
    )


def _parse_hhmm(value: str) -> tuple[int, int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", (value or "18:00").strip())
    if not m:
        return 18, 0
    h, mi = int(m.group(1)), int(m.group(2))
    return max(0, min(23, h)), max(0, min(59, mi))


def infer_audience_timezone(
    countries: list[dict] | None,
    *,
    provinces: list[dict] | None = None,
    fallback: str = "Asia/Kolkata",
) -> tuple[str, str]:
    """
    Pick audience IANA timezone from geography views.
    Returns (timezone, basis_description).
    """
    if not countries:
        return fallback, "configured default timezone"

    total = sum(int(c.get("views") or 0) for c in countries)
    if total <= 0:
        return fallback, "configured default timezone (no geography views)"

    # US: refine with province distribution when available
    us_views = sum(int(c.get("views") or 0) for c in countries if c.get("country") == "US")
    if us_views > 0 and provinces:
        prov_total = sum(int(p.get("views") or 0) for p in provinces)
        if prov_total > 0:
            tz_weights: dict[str, float] = {}
            for p in provinces:
                prov = (p.get("province") or "").upper()
                tz = _US_PROVINCE_TZ.get(prov, "America/New_York")
                tz_weights[tz] = tz_weights.get(tz, 0) + int(p.get("views") or 0)
            if tz_weights:
                best_tz = max(tz_weights, key=tz_weights.get)
                pct = round(tz_weights[best_tz] / prov_total * 100)
                return best_tz, f"US audience provinces ({pct}% in {best_tz})"

    # Weighted country → timezone
    tz_weights: dict[str, float] = {}
    for c in countries:
        code = (c.get("country") or "").upper()
        tz = _COUNTRY_TZ.get(code, fallback)
        tz_weights[tz] = tz_weights.get(tz, 0) + int(c.get("views") or 0)

    best_tz = max(tz_weights, key=tz_weights.get)
    pct = round(tz_weights[best_tz] / total * 100)
    top_country = max(countries, key=lambda x: int(x.get("views") or 0))
    return best_tz, f"{top_country.get('country', '?')} audience ({pct}% in {best_tz})"


def _activity_has_signal(activity: dict | None, cfg: SchedulerConfig) -> bool:
    if not activity or not activity.get("has_data"):
        return False
    if int(activity.get("total_views") or 0) < cfg.activity_min_views:
        return False
    buckets = activity.get("buckets") or []
    nonzero = [b for b in buckets if int(b.get("views") or 0) > 0]
    return len(nonzero) >= cfg.activity_min_buckets


def _scheduling_confidence(
    video_count: int,
    activity: dict | None,
    cfg: SchedulerConfig,
) -> tuple[str, bool]:
    """
    Returns (confidence_level, use_fallback).
    use_fallback=True → default schedule.
    """
    has_signal = _activity_has_signal(activity, cfg)
    n = max(0, int(video_count))

    if not has_signal:
        return "LOW", True

    if n <= 2:
        return "LOW", True

    if n <= 5:
        # Cautious: use analytics only if signal is strong
        if int(activity.get("total_views") or 0) >= cfg.activity_min_views * 2:
            return "MEDIUM", False
        return "LOW", True

    if n <= 9:
        return "MEDIUM", False

    return "HIGH", False


def _rank_activity_windows(activity: dict) -> list[dict]:
    """Sort day+hour buckets by views (descending)."""
    buckets = list(activity.get("buckets") or [])
    buckets.sort(key=lambda b: int(b.get("views") or 0), reverse=True)
    return buckets


def _py_weekday_from_yt(yt_dow: int) -> int:
    return _YT_DOW_TO_PY.get(int(yt_dow), 0)


def _next_local_slot(
    *,
    tz: ZoneInfo,
    hour: int,
    minute: int,
    weekday: int | None,
    now_utc: datetime,
    run_index: int = 0,
    ranked_windows: list[dict] | None = None,
) -> datetime:
    """Return timezone-aware UTC datetime for the next matching local slot."""
    now_local = now_utc.astimezone(tz)

    candidates: list[datetime] = []

    if ranked_windows and run_index < len(ranked_windows):
        # Use ranked analytics windows; for multi-video spread across top slots
        slots_to_try = ranked_windows[run_index : run_index + 1]
        if not slots_to_try and ranked_windows:
            slots_to_try = [ranked_windows[run_index % len(ranked_windows)]]
        for w in slots_to_try:
            h = int(w.get("hour") or hour)
            wd = _py_weekday_from_yt(w.get("day_of_week") or 1)
            candidates.append(_local_dt_for_weekday(tz, wd, h, minute, now_local))
    elif weekday is not None:
        candidates.append(_local_dt_for_weekday(tz, weekday, hour, minute, now_local))
    else:
        candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += timedelta(days=1)
        candidates.append(candidate)

    # Pick earliest future slot
    best: datetime | None = None
    for loc in candidates:
        if loc <= now_local:
            loc = _advance_weekly(loc, tz, hour, minute, weekday if weekday is not None else loc.weekday())
        utc = loc.astimezone(timezone.utc)
        if best is None or utc < best:
            best = utc
    return best or (now_utc + timedelta(hours=1))


def _local_dt_for_weekday(
    tz: ZoneInfo,
    weekday: int,
    hour: int,
    minute: int,
    now_local: datetime,
) -> datetime:
    """Next occurrence of weekday+hour:minute in tz (may be today if still future)."""
    days_ahead = (weekday - now_local.weekday()) % 7
    candidate = (now_local + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate <= now_local:
        candidate += timedelta(days=7)
    return candidate


def _advance_weekly(
    loc: datetime,
    tz: ZoneInfo,
    hour: int,
    minute: int,
    weekday: int,
) -> datetime:
    loc = loc + timedelta(days=7)
    return loc.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _apply_lead(hour: int, minute: int, lead_minutes: int) -> tuple[int, int]:
    if lead_minutes <= 0:
        return hour, minute
    total = hour * 60 + minute - lead_minutes
    if total < 0:
        total += 24 * 60
    return total // 60, total % 60


def _stabilize_hour(
    proposed_hour: int,
    last_hour: int | None,
    confidence: str,
    max_shift: int,
) -> int:
    """Avoid large hour swings on LOW/MEDIUM confidence."""
    if last_hour is None or confidence == "HIGH":
        return proposed_hour
    diff = abs(proposed_hour - last_hour)
    if diff <= max_shift or diff >= 24 - max_shift:
        return proposed_hour
    # Nudge toward last hour
    if proposed_hour > last_hour:
        return min(23, last_hour + max_shift)
    return max(0, last_hour - max_shift)


def validate_publish_timestamp(
    publish_at: datetime,
    now_utc: datetime | None = None,
) -> datetime:
    """Ensure timezone-aware UTC and in the future; advance by 1h if needed."""
    now = now_utc or datetime.now(timezone.utc)
    if publish_at.tzinfo is None:
        raise ValueError("publish_at must be timezone-aware")
    publish_at = publish_at.astimezone(timezone.utc)
    if publish_at <= now:
        publish_at = now + timedelta(hours=1)
        publish_at = publish_at.replace(minute=0, second=0, microsecond=0)
    return publish_at


def format_youtube_publish_at(publish_at: datetime) -> str:
    utc = publish_at.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_publish_schedule(
    state: dict,
    *,
    run_index: int = 0,
    now: datetime | None = None,
    activity: dict | None = None,
    geography: dict | None = None,
    video_count: int | None = None,
    config: SchedulerConfig | None = None,
) -> ScheduleDecision:
    """
    Deterministic publish-time calculation.
    LLM/strategy hints in state are ignored for the final timestamp.
    """
    cfg = config or load_scheduler_config()
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    countries = (geography or {}).get("countries") or []
    provinces = (geography or {}).get("provinces") or []
    audience_tz_name, audience_basis = infer_audience_timezone(
        countries,
        provinces=provinces,
        fallback=state.get("publish_timezone")
        or state.get("default_publish_timezone")
        or cfg.default_publish_timezone,
    )

    try:
        tz = ZoneInfo(audience_tz_name)
    except Exception:
        audience_tz_name = cfg.default_publish_timezone
        tz = ZoneInfo(audience_tz_name)
        audience_basis = "configured default timezone"

    vc = video_count
    if vc is None:
        vc = int((state.get("publish_timing") or {}).get("sample_size") or 0)
        if not vc:
            vc = len(state.get("video_ids") or [])

    confidence, use_fallback = _scheduling_confidence(vc, activity, cfg)
    analytics_available = bool(activity and activity.get("has_data"))

    # Manual mode: fixed local hours (publish_hours_utc key kept for backward compat)
    manual_hours = None
    if not state.get("auto_scheduling", True):
        manual_hours = state.get("publish_hours_local") or state.get("publish_hours_utc")

    default_hour, default_minute = _parse_hhmm(cfg.default_publish_time)
    default_weekday = None
    if cfg.default_publish_days:
        default_weekday = cfg.default_publish_days[0]

    peak_day: str | None = None
    peak_hour_local: int | None = None
    source = "fallback"
    reason = ""
    ranked: list[dict] = []
    publish_hour, publish_minute = default_hour, default_minute
    target_weekday = default_weekday

    if manual_hours and not state.get("auto_scheduling", True):
        source = "manual"
        h = int(manual_hours[run_index % len(manual_hours)])
        publish_hour, publish_minute = h, 0
        reason = f"Manual schedule: {h:02d}:00 {audience_tz_name}"
        confidence = "LOW"
        use_fallback = False  # manual is intentional, not analytics fallback
    elif not use_fallback and analytics_available:
        ranked = _rank_activity_windows(activity)
        if ranked:
            top = ranked[run_index % len(ranked)] if ranked else ranked[0]
            peak_hour_local = int(top.get("hour") or default_hour)
            yt_dow = int(top.get("day_of_week") or 1)
            target_weekday = _py_weekday_from_yt(yt_dow)
            peak_day = _WEEKDAY_NAMES[target_weekday]
            publish_hour, publish_minute = _apply_lead(
                peak_hour_local, 0, cfg.lead_minutes
            )
            # Stability: don't jump wildly vs last publish
            last_decision = (state.get("last_schedule_decision") or {})
            last_hour = last_decision.get("peak_hour_local")
            publish_hour = _stabilize_hour(
                publish_hour, last_hour, confidence, cfg.stability_max_hour_shift
            )
            source = "analytics"
            reason = (
                f"Peak audience activity {peak_day} {peak_hour_local:02d}:00 "
                f"{audience_tz_name} (views={top.get('views', 0)})"
            )
        else:
            use_fallback = True
            reason = "Analytics returned no usable activity buckets"
    else:
        if not analytics_available:
            reason = "insufficient audience activity data"
        elif vc <= 2:
            reason = f"only {vc} published videos — using default schedule"
        else:
            reason = "analytics confidence too low for scheduling changes"

    if use_fallback and source != "manual":
        source = "fallback"
        publish_hour, publish_minute = default_hour, default_minute
        if cfg.default_publish_days:
            target_weekday = cfg.default_publish_days[run_index % len(cfg.default_publish_days)]
            peak_day = _WEEKDAY_NAMES[target_weekday]
        if not reason:
            reason = "default configured schedule"

    publish_at_utc = _next_local_slot(
        tz=tz,
        hour=publish_hour,
        minute=publish_minute,
        weekday=target_weekday,
        now_utc=now_utc,
        run_index=run_index,
        ranked_windows=None,
    )
    publish_at_utc = validate_publish_timestamp(publish_at_utc, now_utc)

    local_dt = publish_at_utc.astimezone(tz)
    local_label = (
        f"{local_dt.strftime('%A')}, {local_dt.strftime('%H:%M')} {audience_tz_name}"
    )
    utc_label = publish_at_utc.strftime("%H:%M UTC")
    youtube_at = format_youtube_publish_at(publish_at_utc)

    return ScheduleDecision(
        publish_at_utc=publish_at_utc,
        audience_timezone=audience_tz_name,
        local_publish_label=local_label,
        peak_day=peak_day or local_dt.strftime("%A"),
        peak_hour_local=peak_hour_local if peak_hour_local is not None else publish_hour,
        confidence=confidence,
        fallback_used=(source == "fallback"),
        analytics_available=analytics_available,
        source=source,
        reason=reason,
        audience_basis=(
            "YouTube viewer activity"
            if source == "analytics"
            else audience_basis
        ),
        utc_label=utc_label,
        youtube_publish_at=youtube_at,
    )


def resolve_pipeline_trigger_hours(state: dict, config: SchedulerConfig | None = None) -> list[int]:
    """
    When the agent wakes up to run the pipeline (UTC hours).
    Independent of YouTube publish time.
    """
    cfg = config or load_scheduler_config()
    if state.get("trigger_hours_utc"):
        hours = list(state["trigger_hours_utc"])
    elif not state.get("auto_scheduling", True) and state.get("publish_hours_utc"):
        # Legacy: manual publish hours → produce TRIGGER_LEAD_HOURS earlier (UTC-based legacy)
        lead = int(os.environ.get("TRIGGER_LEAD_HOURS", "3"))
        hours = [(int(h) - lead) % 24 for h in state["publish_hours_utc"]]
    else:
        hours = list(cfg.pipeline_trigger_hours)
    n = max(1, min(5, int(state.get("videos_per_day", 1))))
    return sorted(int(h) for h in hours)[:n]


def log_schedule_decision(decision: ScheduleDecision, *, log_fn=print) -> None:
    lines = [
        "[SCHEDULER]",
        f"Analytics available: {'yes' if decision.analytics_available else 'no'}",
        f"Analytics confidence: {decision.confidence.lower()}",
        f"Audience timezone: {decision.audience_timezone}",
        f"Peak day: {decision.peak_day or 'n/a'}",
        f"Peak hour: {decision.peak_hour_local if decision.peak_hour_local is not None else 'n/a'}",
        f"Selected local publish time: {decision.local_publish_label}",
        f"UTC publish time: {decision.utc_label} ({decision.youtube_publish_at})",
        f"Fallback used: {'yes' if decision.fallback_used else 'no'}",
        f"Source: {decision.source}",
        f"Reason: {decision.reason}",
    ]
    for line in lines:
        log_fn(line)


def format_telegram_schedule(decision: ScheduleDecision) -> str:
    if decision.fallback_used:
        return (
            "📅 <b>Publish scheduled</b>\n\n"
            f"🕐 Publish time:\n{decision.local_publish_label}\n\n"
            f"📊 Analytics confidence:\n{decision.confidence}\n\n"
            f"ℹ️ Using default schedule because {decision.reason}."
        )
    if decision.source == "manual":
        return (
            "📅 <b>Publish scheduled</b>\n\n"
            f"🕐 Publish time:\n{decision.local_publish_label}\n\n"
            f"📊 Source: manual schedule"
        )
    return (
        "📅 <b>Publish scheduled</b>\n\n"
        f"🕐 Audience time:\n{decision.local_publish_label}\n\n"
        f"🌍 Audience basis:\n{decision.audience_basis}\n\n"
        f"📊 Analytics confidence:\n{decision.confidence}\n\n"
        f"🕐 UTC:\n{decision.utc_label}"
    )
