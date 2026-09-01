"""
Cache analytics canale — evita decine di chiamate YouTube API per ciclo.

Fonti (in ordine):
  1. cache/analytics_snapshot.json (TTL configurabile)
  2. video_performance_profiles.json (metriche recenti)
  3. API live (solo se stale o force=True)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

CACHE_FILE = "cache/analytics_snapshot.json"
DEFAULT_TTL_MINUTES = 90
DEFAULT_RETENTION_TTL_HOURS = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%d %H:%M UTC")


def cache_ttl_minutes() -> int:
    raw = os.environ.get("ANALYTICS_CACHE_TTL_MINUTES", str(DEFAULT_TTL_MINUTES))
    try:
        return max(5, int(raw))
    except ValueError:
        return DEFAULT_TTL_MINUTES


def retention_query_ttl_hours() -> int:
    raw = os.environ.get("ANALYTICS_RETENTION_TTL_HOURS", str(DEFAULT_RETENTION_TTL_HOURS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_RETENTION_TTL_HOURS


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value.replace("+00:00", "Z"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def is_metrics_fresh(profile: dict | None, ttl_minutes: int | None = None) -> bool:
    """True se metrics_updated_at del profilo è entro TTL."""
    if not profile or not profile.get("metrics"):
        return False
    ttl_minutes = ttl_minutes if ttl_minutes is not None else cache_ttl_minutes()
    updated = _parse_ts(profile.get("metrics_updated_at"))
    if not updated:
        return False
    return (_now() - updated) <= timedelta(minutes=ttl_minutes)


def is_retention_fresh(profile: dict | None) -> bool:
    m = (profile or {}).get("metrics") or {}
    if m.get("retention_at_30s_percent") is None:
        return False
    updated = _parse_ts(profile.get("metrics_updated_at"))
    if not updated:
        return False
    return (_now() - updated) <= timedelta(hours=retention_query_ttl_hours())


def load_snapshot() -> dict | None:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("rows"):
            return data
    except Exception:
        pass
    return None


def save_snapshot(rows: list[dict], n_video: int) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
    payload = {
        "fetched_at": _now_iso(),
        "n_video": n_video,
        "rows": rows,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def snapshot_is_fresh(snapshot: dict | None, n_video: int, ttl_minutes: int | None = None) -> bool:
    if not snapshot or not snapshot.get("rows"):
        return False
    if int(snapshot.get("n_video") or 0) < n_video:
        return False
    fetched = _parse_ts(snapshot.get("fetched_at"))
    if not fetched:
        return False
    ttl = ttl_minutes if ttl_minutes is not None else cache_ttl_minutes()
    return (_now() - fetched) <= timedelta(minutes=ttl)


def rows_from_profiles(n_video: int, ttl_minutes: int | None = None) -> list[dict]:
    """Profili con metriche fresche → righe analytics (senza API)."""
    from moduli.performance import carica_profili, profilo_to_analytics_row
    ttl = ttl_minutes if ttl_minutes is not None else cache_ttl_minutes()
    rows: list[dict] = []
    for profile in carica_profili():
        if not is_metrics_fresh(profile, ttl):
            continue
        rows.append(profilo_to_analytics_row(profile))
        if len(rows) >= n_video:
            break
    return rows


def get_channel_performance(
    n_video: int = 10,
    *,
    force: bool = False,
) -> tuple[list[dict], str]:
    """
    Performance canale con cache.
    Ritorna (righe, fonte) dove fonte è cache | profiles | api.
    """
    n_video = max(1, int(n_video))
    ttl = cache_ttl_minutes()

    if not force:
        snap = load_snapshot()
        if snapshot_is_fresh(snap, n_video, ttl):
            return list(snap["rows"][:n_video]), "cache"

        profile_rows = rows_from_profiles(n_video, ttl)
        if len(profile_rows) >= n_video:
            return profile_rows[:n_video], "profiles"

    from moduli.analytics import leggi_performance
    from moduli.performance import carica_profili

    profiles_hint = None if force else carica_profili()
    rows = leggi_performance(n_video=n_video, profiles_hint=profiles_hint)
    if rows:
        save_snapshot(rows, n_video)
        return rows, "api"
    return rows, "api"
