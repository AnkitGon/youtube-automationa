"""
Ottimizzazione orari di pubblicazione da analytics.

Impara da ora UTC, giorno settimana, CTR, velocity e watch time.
Non cambia gli orari su un solo video — richiede evidenza aggregata.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone

from moduli.channel_confidence import channel_confidence, confidence_from_profiles

DEFAULT_SPREADS = {
    1: [20],
    2: [14, 20],
    3: [10, 15, 20],
    4: [9, 13, 17, 21],
    5: [8, 11, 14, 17, 20],
}


def _composite_score(profile: dict) -> float:
    """Score composito per ranking slot pubblicazione."""
    from moduli.performance import compute_score_breakdown
    if profile.get("performance_score") is not None:
        return float(profile["performance_score"])
    return float(compute_score_breakdown(profile).get("performance_score") or 0)


def _ctr(profile: dict) -> float:
    return float((profile.get("metrics") or {}).get("ctr_percent") or 0)


def _velocity(profile: dict) -> float:
    from moduli.performance import compute_score_breakdown
    return float(compute_score_breakdown(profile).get("views_per_day") or 0)


def _watch_time_ratio(profile: dict) -> float:
    m = profile.get("metrics") or {}
    dur = max(float(m.get("duration_seconds") or 1), 1.0)
    return float(m.get("avg_view_duration_seconds") or 0) / dur


def _hour(profile: dict) -> int | None:
    h = profile.get("published_hour_utc")
    if h is not None:
        return int(h)
    return None


def _day(profile: dict) -> str | None:
    d = profile.get("published_day_utc")
    if d:
        return str(d)
    pub = profile.get("published_at") or ""
    try:
        dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%A")
    except Exception:
        return None


def analyze_publish_timing(profiles: list[dict]) -> dict:
    """Analizza finestre di pubblicazione con metriche composite."""
    conf = confidence_from_profiles(profiles)
    empty = {
        "has_data": False,
        "confidence": conf.level,
        "video_count": conf.video_count,
        "sufficient_evidence": False,
        "hour_rankings": [],
        "day_rankings": [],
        "recommended_hours_utc": [],
        "recommended_days": [],
        "windows": [],
        "channel_baseline": {},
    }
    usable = [p for p in profiles if _hour(p) is not None]
    if not usable:
        return empty

    scores = [_composite_score(p) for p in usable]
    ctrs = [_ctr(p) for p in usable]
    vels = [_velocity(p) for p in usable]
    watches = [_watch_time_ratio(p) for p in usable]
    baseline_score = statistics.mean(scores) if scores else 0.0

    hour_buckets: dict[int, list[dict]] = defaultdict(list)
    day_buckets: dict[str, list[dict]] = defaultdict(list)
    window_buckets: dict[tuple[int, str], list[dict]] = defaultdict(list)

    for p in usable:
        h = _hour(p)
        d = _day(p)
        row = {
            "score": _composite_score(p),
            "ctr": _ctr(p),
            "velocity": _velocity(p),
            "watch_ratio": _watch_time_ratio(p),
            "video_id": p.get("video_id"),
            "title": (p.get("title") or "")[:50],
        }
        if h is not None:
            hour_buckets[h].append(row)
        if d:
            day_buckets[d].append(row)
            if h is not None:
                window_buckets[(h, d)].append(row)

    def _rank_buckets(buckets: dict, label_key: str) -> list[dict]:
        rows: list[dict] = []
        for key, items in buckets.items():
            n = len(items)
            avg_score = statistics.mean(i["score"] for i in items)
            avg_ctr = statistics.mean(i["ctr"] for i in items)
            avg_vel = statistics.mean(i["velocity"] for i in items)
            avg_watch = statistics.mean(i["watch_ratio"] for i in items)
            rows.append({
                label_key: key,
                "sample_size": n,
                "avg_score": round(avg_score * 100, 1),
                "score_vs_channel": round((avg_score - baseline_score) * 100, 1),
                "avg_ctr": round(avg_ctr, 2),
                "avg_velocity": round(avg_vel, 1),
                "avg_watch_ratio": round(avg_watch, 3),
                "evidence_ok": n >= conf.min_bucket_samples,
            })
        rows.sort(key=lambda x: x["score_vs_channel"], reverse=True)
        return rows

    hour_rankings = _rank_buckets(hour_buckets, "hour_utc")
    day_rankings = _rank_buckets(day_buckets, "day")
    windows = []
    for (h, d), items in window_buckets.items():
        if len(items) < conf.min_bucket_samples:
            continue
        avg_score = statistics.mean(i["score"] for i in items)
        windows.append({
            "hour_utc": h,
            "day": d,
            "sample_size": len(items),
            "avg_score": round(avg_score * 100, 1),
            "score_vs_channel": round((avg_score - baseline_score) * 100, 1),
            "avg_ctr": round(statistics.mean(i["ctr"] for i in items), 2),
            "avg_velocity": round(statistics.mean(i["velocity"] for i in items), 1),
        })
    windows.sort(key=lambda x: x["score_vs_channel"], reverse=True)

    sufficient = (
        conf.apply_publish_changes
        and any(r["evidence_ok"] and r["sample_size"] >= 2 for r in hour_rankings)
    )

    recommended_hours = [
        r["hour_utc"] for r in hour_rankings
        if r["evidence_ok"] and r["score_vs_channel"] > 0
    ]
    recommended_days = [
        r["day"] for r in day_rankings
        if r["evidence_ok"] and r["score_vs_channel"] > 0
    ]

    return {
        "has_data": True,
        "confidence": conf.level,
        "video_count": conf.video_count,
        "optimization_mode": conf.optimization_mode,
        "sufficient_evidence": sufficient,
        "hour_rankings": hour_rankings,
        "day_rankings": day_rankings,
        "recommended_hours_utc": recommended_hours,
        "recommended_days": recommended_days,
        "windows": windows[:8],
        "channel_baseline": {
            "avg_score": round(baseline_score * 100, 1),
            "avg_ctr": round(statistics.mean(ctrs), 2) if ctrs else 0,
            "avg_velocity": round(statistics.mean(vels), 1) if vels else 0,
            "avg_watch_ratio": round(statistics.mean(watches), 3) if watches else 0,
        },
    }


def recommend_publish_hours(
    profiles: list[dict],
    videos_per_day: int = 1,
    current_hours: list[int] | None = None,
    *,
    performance_rows: list[dict] | None = None,
) -> dict:
    """
    Calcola ore UTC consigliate per pubblicazione.
    Mantiene spread default se evidenza insufficiente.
    """
    vpd = max(1, min(5, int(videos_per_day)))
    fallback = list(DEFAULT_SPREADS.get(vpd, [20]))
    current = sorted(current_hours or fallback)

    # Arricchisci con righe analytics se i profili sono scarsi
    if performance_rows and len(profiles or []) < len(performance_rows):
        merged = list(profiles or [])
        seen = {p.get("video_id") for p in merged}
        for row in performance_rows:
            vid = row.get("video_id")
            if vid and vid not in seen:
                merged.append({
                    "video_id": vid,
                    "title": row.get("title"),
                    "published_hour_utc": row.get("published_hour_utc"),
                    "published_day_utc": row.get("published_day_utc"),
                    "published_at": row.get("published_at"),
                    "metrics": row,
                    "performance_score": None,
                })
        profiles = merged

    analysis = analyze_publish_timing(profiles or [])
    conf = confidence_from_profiles(profiles or [])

    result = {
        "hours": current if current else fallback,
        "changed": False,
        "confidence": conf.level,
        "video_count": conf.video_count,
        "analysis": analysis,
        "reason": conf.summary,
    }

    if not conf.apply_publish_changes:
        result["reason"] = (
            f"{conf.level} confidence ({conf.video_count} videos) — "
            "keeping default/manual publish hours"
        )
        result["hours"] = fallback if not current_hours else current
        return result

    hour_rankings = analysis.get("hour_rankings") or []
    evidenced = [
        r for r in hour_rankings
        if r.get("evidence_ok") and r.get("sample_size", 0) >= conf.min_bucket_samples
    ]
    if len(evidenced) < 1:
        result["reason"] = "No publish hour has enough supporting videos"
        return result

    # Solo ore con evidenza — mai basarsi su un singolo video
    top_hours = [r["hour_utc"] for r in evidenced[: vpd + 2]]
    if not top_hours:
        return result

    new_hours = sorted(top_hours[:vpd])
    while len(new_hours) < vpd:
        for h in fallback:
            if h not in new_hours:
                new_hours.append(h)
            if len(new_hours) >= vpd:
                break
    new_hours = sorted(new_hours[:vpd])

    # Cambio conservativo: non spostare tutto se differenza marginale
    if conf.level != "HIGH" and set(new_hours) != set(current):
        overlap = len(set(new_hours) & set(current))
        if overlap >= max(1, vpd - 1):
            new_hours = current
            result["reason"] = "Partial evidence — keeping most current publish hours"
            result["hours"] = new_hours
            return result

    if new_hours != current:
        result["changed"] = True
        result["hours"] = new_hours
        result["reason"] = (
            f"Publish windows updated from analytics "
            f"(confidence {conf.level}, n={conf.video_count})"
        )
    else:
        result["reason"] = "Current publish hours align with analytics"
    return result


def publish_guidance_text(profiles: list[dict] | None = None) -> str:
    """Testo compatto per strategia / Telegram."""
    analysis = analyze_publish_timing(profiles or [])
    if not analysis.get("has_data"):
        return "Publish timing: insufficient data — use default schedule."
    lines = [
        f"Publish optimization (confidence {analysis.get('confidence')}, "
        f"n={analysis.get('video_count')}):",
    ]
    if analysis.get("recommended_hours_utc"):
        lines.append(f"Recommended hours UTC: {analysis['recommended_hours_utc'][:5]}")
    for w in (analysis.get("windows") or [])[:3]:
        lines.append(
            f"- {w['day']} {w['hour_utc']:02d}:00 UTC — "
            f"score {w['avg_score']} (+{w['score_vs_channel']}), "
            f"CTR {w['avg_ctr']}%, vel {w['avg_velocity']}/day (n={w['sample_size']})"
        )
    if not analysis.get("sufficient_evidence"):
        lines.append("Not enough evidence for major schedule changes yet.")
    return "\n".join(lines)


def build_publish_strategy(
    profiles: list[dict],
    *,
    state: dict | None = None,
    videos_per_day: int = 1,
) -> dict:
    """
    Analytics-driven publishing strategy with time window (not a single magic minute).
    """
    state = state or {}
    vpd = max(1, int(state.get("videos_per_day", videos_per_day)))
    current = state.get("best_hours_utc") or state.get("publish_hours_utc")
    rec = recommend_publish_hours(
        profiles,
        videos_per_day=vpd,
        current_hours=current,
    )
    analysis = rec.get("analysis") or analyze_publish_timing(profiles)
    hours = rec.get("hours") or [20]
    windows = analysis.get("windows") or []
    best_window = None
    if windows:
        w = windows[0]
        best_window = {
            "hour_utc": w.get("hour_utc"),
            "day": w.get("day"),
            "sample_size": w.get("sample_size"),
            "score_vs_channel": w.get("score_vs_channel"),
        }
    elif hours:
        best_window = {"hour_utc": hours[0], "day": None, "sample_size": analysis.get("video_count", 0)}

    return {
        "best_hours_utc": hours,
        "best_time_window_utc": best_window,
        "confidence": rec.get("confidence") or analysis.get("confidence"),
        "sample_size": analysis.get("video_count", 0),
        "reason": rec.get("reason", ""),
        "sufficient_evidence": analysis.get("sufficient_evidence", False),
        "recommended_days": analysis.get("recommended_days") or [],
    }


def record_schedule_outcome(
    video_id: str,
    scheduled_at: str,
    *,
    actual_metrics: dict | None = None,
) -> None:
    """Link scheduled time to later performance for schedule learning."""
    try:
        from moduli.channel_learning import load_channel_learning, _save
        data = load_channel_learning()
        for entry in reversed(data.get("scheduling_history") or []):
            if entry.get("video_id") == video_id and not entry.get("outcome_recorded"):
                entry["outcome_recorded"] = True
                entry["actual_metrics"] = actual_metrics or {}
                entry["scheduled_at"] = scheduled_at
                break
        _save(data)
    except Exception:
        pass
