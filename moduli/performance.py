"""
Profili performance video e scoring normalizzato.

Ogni ciclo pipeline:
  1. aggiorna metriche YouTube sui profili esistenti
  2. calcola performance_score (pesi configurabili via env PERF_WEIGHT_*)
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone

PROFILES_FILE = "video_performance_profiles.json"

PERFORMANCE_TIERS = ("breakout", "strong", "average", "weak", "poor")

# Soglie percentile canale → tier (rank 0 = peggiore)
_TIER_PERCENTILE = (
    (0.85, "breakout"),
    (0.65, "strong"),
    (0.35, "average"),
    (0.15, "weak"),
    (0.00, "poor"),
)

_DIMENSION_LABELS = {
    "topic_category": "topic category",
    "topic_angle": "topic angle",
    "content_format": "content format",
    "title_pattern": "title structure",
    "hook_type": "opening hook style",
    "thumbnail_concept": "thumbnail concept",
    "hook_strength": "hook strength",
    "mood": "mood",
    "pacing": "pacing",
    "video_style": "video style",
    "duration_bucket": "video length",
    "publish_hour_utc": "publish hour (UTC)",
    "publish_day_utc": "publish day",
    "topic_theme": "topic theme",
}

# Temi inferiti da titolo/topic — etichette leggibili per pattern winning/losing
_TOPIC_THEME_RULES = (
    ("failure_story", r"\b(fail(?:ed|ure)?|collapse[ds]?|disaster|bankrupt|shutdown|flop(?:ped)?)\b",
     "technology failure stories"),
    ("why_failed", r"\bwhy\b.{0,40}\b(fail(?:ed|ure)?|flop(?:ped)?|collapse[ds]?)\b",
     '"Why X Failed" style titles'),
    ("generic_ai_future", r"\b(future of ai|ai will|ai revolution|ai takeover|rise of ai|ai age)\b",
     "generic AI future topics"),
    ("ai_business", r"\b(business|startup|compan(?:y|ies)|industry|market|revenue|money)\b",
     "AI business stories"),
    ("generic_ai_news", r"\b(new ai|ai news|latest ai|just announced|openai releases)\b",
     "generic AI news"),
    ("curiosity", r"\b(secret|hidden|truth|nobody|shocking|surpris(?:e|ing)|don't know)\b",
     "curiosity-driven framing"),
    ("broad_subject", r"\b(everything about|complete guide|ultimate guide|all about|101)\b",
     "overly broad subjects"),
)

# Pesi default — somma tipica ~1.0; configurabili con PERF_WEIGHT_CTR ecc.
DEFAULT_WEIGHTS = {
    "ctr": 0.20,
    "retention": 0.25,
    "watch_time": 0.15,
    "views_velocity": 0.20,
    "engagement": 0.10,
    "subscribers": 0.10,
}

# Soglie normalizzazione (valore reale → 1.0)
NORM = {
    "ctr_percent": 12.0,          # 12% CTR = score pieno
    "retention_percent": 70.0,    # 70% watched = score pieno
    "watch_ratio": 1.0,           # avg_view / duration
    "views_per_day": 800.0,       # 800 views/giorno = score pieno (canale piccolo/medio)
    "engagement_rate": 4.0,       # (likes+2*comments)/views * 100
    "sub_rate": 2.0,              # subscribers_gained/views * 100
}


def _load_weights() -> dict[str, float]:
    weights = {}
    for key, default in DEFAULT_WEIGHTS.items():
        env_key = f"PERF_WEIGHT_{key.upper()}"
        raw = os.environ.get(env_key, "")
        try:
            weights[key] = float(raw) if raw.strip() else default
        except ValueError:
            weights[key] = default
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def _load_profiles() -> dict[str, dict]:
    if not os.path.exists(PROFILES_FILE):
        return {}
    try:
        with open(PROFILES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {p["video_id"]: p for p in data if p.get("video_id")}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_profiles(profiles: dict[str, dict]) -> None:
    ordered = sorted(
        profiles.values(),
        key=lambda p: p.get("published_at") or p.get("pipeline_recorded_at") or "",
        reverse=True,
    )
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(ordered[:100], f, indent=2, ensure_ascii=False)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _norm_ratio(value: float, ceiling: float) -> float:
    if ceiling <= 0:
        return 0.0
    return _clamp01(value / ceiling)


def video_age_hours(published_at: str | None, now: datetime | None = None) -> float:
    if not published_at:
        return 24.0
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hours = (now - dt.astimezone(timezone.utc)).total_seconds() / 3600
        return max(hours, 0.25)
    except Exception:
        return 24.0


def _published_meta(published_at: str | None) -> tuple[int | None, str | None]:
    if not published_at:
        return None, None
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        utc = dt.astimezone(timezone.utc)
        return utc.hour, utc.strftime("%A")
    except Exception:
        return None, None


def _infer_title_pattern(title: str) -> str:
    from moduli.title_learning import classify_title_pattern
    return classify_title_pattern(title)


def infer_title_pattern(title: str) -> str:
    """API pubblica per inferenza pattern titolo."""
    return _infer_title_pattern(title)


def _duration_bucket(seconds: int | float | None) -> str | None:
    if not seconds:
        return None
    mins = float(seconds) / 60.0
    if mins < 4:
        return "~3-4 min"
    if mins < 6:
        return "~5 min"
    if mins < 9:
        return "~8 min"
    if mins < 12:
        return "~10 min"
    return "12+ min"


def infer_topic_themes(title: str, topic: str) -> list[str]:
    text = f"{title} {topic}".lower()
    themes: list[str] = []
    for _tid, pattern, label in _TOPIC_THEME_RULES:
        if re.search(pattern, text, re.I):
            themes.append(label)
    return themes


def _infer_topic_themes(title: str, topic: str) -> list[str]:
    return infer_topic_themes(title, topic)


def _profile_score(profile: dict) -> float:
    if profile.get("performance_score") is not None:
        return float(profile["performance_score"])
    return compute_score_breakdown(profile)["performance_score"]


def classify_tier(rank_pct: float) -> str:
    """Classifica un percentile relativo canale (0=peggiore, 1=migliore)."""
    for threshold, tier in _TIER_PERCENTILE:
        if rank_pct >= threshold:
            return tier
    return "poor"


def classify_profiles(profiles: list[dict]) -> dict[str, str]:
    """Mappa video_id → tier usando performance relativa al canale."""
    scored = [
        (p.get("video_id"), _profile_score(p))
        for p in profiles
        if p.get("video_id") is not None
    ]
    if not scored:
        return {}
    if len(scored) == 1:
        return {scored[0][0]: "average"}

    ordered = sorted(scored, key=lambda x: x[1])
    n = len(ordered)
    tiers: dict[str, str] = {}
    for i, (vid, _score) in enumerate(ordered):
        pct = i / (n - 1)
        tiers[vid] = classify_tier(pct)
    return tiers


def apply_tier_classification(profiles: list[dict]) -> list[dict]:
    """Aggiunge performance_tier a ogni profilo (relativo al batch/canale)."""
    tiers = classify_profiles(profiles)
    for p in profiles:
        vid = p.get("video_id")
        p["performance_tier"] = tiers.get(vid, "average")
    return profiles


def _extract_pattern_attrs(profile: dict) -> dict[str, str]:
    """Attributi confrontabili per pattern detection."""
    meta = profile.get("content_metadata") or {}
    m = profile.get("metrics") or {}
    title = profile.get("title") or ""
    topic = profile.get("topic") or meta.get("topic") or ""

    attrs: dict[str, str] = {}
    for key in (
        "topic_category", "topic_angle", "content_format", "title_pattern",
        "hook_type", "thumbnail_concept", "hook_strength", "mood", "pacing", "video_style",
    ):
        val = meta.get(key) or profile.get(key)
        if val:
            attrs[key] = str(val).strip()

    if not attrs.get("title_pattern") and title:
        attrs["title_pattern"] = _infer_title_pattern(title)

    bucket = _duration_bucket(m.get("duration_seconds"))
    if bucket:
        attrs["duration_bucket"] = bucket

    hour = profile.get("published_hour_utc")
    if hour is not None:
        attrs["publish_hour_utc"] = f"{int(hour):02d}:00 UTC"

    day = profile.get("published_day_utc")
    if day:
        attrs["publish_day_utc"] = str(day)

    for theme in _infer_topic_themes(title, topic):
        attrs[f"topic_theme|{theme}"] = theme

    # hook debole + retention bassa → pattern perdente esplicito
    retention = float(m.get("retention_percent") or 0)
    hook = (meta.get("hook_strength") or "").lower()
    if hook in ("soft", "medium", "") and retention and retention < 35:
        attrs["weak_intro"] = "low-retention introduction"

    return attrs


def _pattern_threshold(channel_scores: list[float]) -> float:
    if len(channel_scores) < 2:
        return 0.08
    spread = max(channel_scores) - min(channel_scores)
    return max(0.06, spread * 0.18)


def detect_patterns(profiles: list[dict]) -> dict:
    """
    Identifica pattern vincenti/perdenti relativi al canale.
    Confronta medie per attributo vs mediana canale — non soglie globali.
    """
    empty = {
        "by_tier": {t: [] for t in PERFORMANCE_TIERS},
        "winning_patterns": [],
        "losing_patterns": [],
        "winners_count": 0,
        "losers_count": 0,
        "channel_median_score": 0.0,
    }
    if not profiles:
        return empty

    profiles = apply_tier_classification(list(profiles))
    channel_scores = [_profile_score(p) for p in profiles]
    channel_median = statistics.median(channel_scores)
    channel_mean = statistics.mean(channel_scores)
    threshold = _pattern_threshold(channel_scores)
    tiers_map = {p.get("video_id"): p.get("performance_tier") for p in profiles}

    by_tier: dict[str, list[dict]] = {t: [] for t in PERFORMANCE_TIERS}
    for p in profiles:
        tier = p.get("performance_tier", "average")
        m = p.get("metrics") or {}
        meta = p.get("content_metadata") or {}
        by_tier[tier].append({
            "video_id": p.get("video_id"),
            "title": (p.get("title") or "")[:50],
            "score": round(_profile_score(p) * 100, 1),
            "views": m.get("views", 0),
            "ctr_pct": m.get("ctr_percent", 0),
            "retention_pct": m.get("retention_percent", 0),
            "topic_angle": meta.get("topic_angle", ""),
            "title_pattern": meta.get("title_pattern", ""),
        })

    winners = [p for p in profiles if p.get("performance_tier") in ("breakout", "strong")]
    losers = [p for p in profiles if p.get("performance_tier") in ("weak", "poor")]
    min_count = 1 if len(profiles) <= 4 else 2

    buckets: dict[tuple[str, str], list[tuple[float, dict]]] = defaultdict(list)
    for p in profiles:
        score = _profile_score(p)
        for dim_key, value in _extract_pattern_attrs(p).items():
            if dim_key.startswith("topic_theme|"):
                dim_key = "topic_theme"
            if not value:
                continue
            if dim_key not in _DIMENSION_LABELS:
                continue
            buckets[(dim_key, value)].append((score, p))

    winning_patterns: list[dict] = []
    losing_patterns: list[dict] = []

    for (dim_key, value), items in buckets.items():
        if len(items) < min_count:
            continue
        scores = [s for s, _ in items]
        avg = statistics.mean(scores)
        delta = avg - channel_median
        label = _DIMENSION_LABELS.get(dim_key, dim_key)
        top_share = sum(
            1 for _, p in items
            if tiers_map.get(p.get("video_id")) in ("breakout", "strong")
        ) / len(items)
        bottom_share = sum(
            1 for _, p in items
            if tiers_map.get(p.get("video_id")) in ("weak", "poor")
        ) / len(items)

        entry = {
            "pattern": f"{label}: {value}",
            "dimension": dim_key,
            "value": value,
            "avg_score": round(avg * 100, 1),
            "sample_size": len(items),
            "vs_channel_median": round(delta * 100, 1),
        }

        if delta >= threshold and (top_share >= 0.5 or avg >= channel_mean + threshold):
            winning_patterns.append(entry)
        elif delta <= -threshold and (bottom_share >= 0.5 or avg <= channel_mean - threshold):
            losing_patterns.append(entry)

    # Confronto durata esplicito (es. 8 min vs 5 min) se abbastanza dati
    duration_groups: dict[str, list[float]] = defaultdict(list)
    for p in profiles:
        bucket = _duration_bucket((p.get("metrics") or {}).get("duration_seconds"))
        if bucket:
            duration_groups[bucket].append(_profile_score(p))
    if len(duration_groups) >= 2:
        ranked_durations = sorted(
            duration_groups.items(),
            key=lambda x: statistics.mean(x[1]),
            reverse=True,
        )
        best_bucket, best_scores = ranked_durations[0]
        worst_bucket, worst_scores = ranked_durations[-1]
        if statistics.mean(best_scores) - statistics.mean(worst_scores) >= threshold:
            winning_patterns.append({
                "pattern": f"video length: {best_bucket} outperforms {worst_bucket}",
                "dimension": "duration_bucket",
                "value": best_bucket,
                "avg_score": round(statistics.mean(best_scores) * 100, 1),
                "sample_size": len(best_scores),
                "vs_channel_median": round((statistics.mean(best_scores) - channel_median) * 100, 1),
            })
            losing_patterns.append({
                "pattern": f"video length: {worst_bucket} underperforms {best_bucket}",
                "dimension": "duration_bucket",
                "value": worst_bucket,
                "avg_score": round(statistics.mean(worst_scores) * 100, 1),
                "sample_size": len(worst_scores),
                "vs_channel_median": round((statistics.mean(worst_scores) - channel_median) * 100, 1),
            })

    winning_patterns.sort(key=lambda x: -x["vs_channel_median"])
    losing_patterns.sort(key=lambda x: x["vs_channel_median"])

    return {
        "by_tier": by_tier,
        "winning_patterns": winning_patterns[:10],
        "losing_patterns": losing_patterns[:10],
        "winners_count": len(winners),
        "losers_count": len(losers),
        "channel_median_score": round(channel_median * 100, 1),
    }


def pattern_signals(patterns: dict, max_each: int = 4) -> list[str]:
    """Frasi compatte per strategia / Telegram."""
    lines = []
    for wp in patterns.get("winning_patterns", [])[:max_each]:
        lines.append(
            f"WINNING — {wp['pattern']} "
            f"(score {wp['avg_score']}/100, +{wp['vs_channel_median']} vs channel median)"
        )
    for lp in patterns.get("losing_patterns", [])[:max_each]:
        lines.append(
            f"LOSING — {lp['pattern']} "
            f"(score {lp['avg_score']}/100, {lp['vs_channel_median']} vs channel median)"
        )
    return lines


def _content_metadata(topic: str, title: str, content: dict, strategy: dict) -> dict:
    from moduli.hook_optimization import classify_hook_type, opening_excerpt
    from moduli.script_optimization import extract_script_traits
    from moduli.thumbnail_learning import classify_thumbnail_traits
    script = content.get("script") or ""
    hook = opening_excerpt(script, max_words=80) or script[:280].strip()
    hook_type = (content.get("_strategy_meta") or {}).get("hook_type") or classify_hook_type(hook)
    script_traits = extract_script_traits(script)
    if strategy.get("pacing"):
        script_traits["pacing"] = strategy.get("pacing")
    if strategy.get("hook_strength"):
        script_traits["hook_strength"] = strategy.get("hook_strength")
    thumb_traits = classify_thumbnail_traits(
        content.get("thumbnail_description") or "",
        content.get("thumbnail_phrase") or "",
        content.get("mood") or "",
    )
    return {
        "topic": topic,
        "topic_category": strategy.get("topic_focus", "")[:200],
        "topic_angle": strategy.get("preferred_angle", ""),
        "content_format": strategy.get("content_format", ""),
        "title_pattern": _infer_title_pattern(title),
        "thumbnail_concept": (content.get("thumbnail_phrase") or "")[:80],
        "thumbnail_description_snippet": (content.get("thumbnail_description") or "")[:200],
        "hook_strength": strategy.get("hook_strength", ""),
        "hook_type": hook_type,
        "script_hook_excerpt": hook[:280],
        "script_traits": script_traits,
        "thumbnail_traits": thumb_traits,
        "mood": content.get("mood", ""),
        "pacing": strategy.get("pacing", ""),
        "video_style": strategy.get("video_style", ""),
        "experimentation": (content.get("_strategy_meta") or {}).get("experimentation") or {},
    }


def registra_pubblicazione(
    video_id: str,
    topic: str,
    title: str,
    content: dict,
    strategy: dict,
    publish_time: str | None = None,
) -> dict:
    """Salva metadati pipeline al momento della pubblicazione (analytics possono arrivare dopo)."""
    profiles = _load_profiles()
    now = datetime.now(timezone.utc)
    published_at = publish_time or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    hour, day = _published_meta(published_at)

    profile = profiles.get(video_id, {})
    profile.update({
        "video_id": video_id,
        "title": title,
        "topic": topic,
        "published_at": published_at,
        "published_hour_utc": hour,
        "published_day_utc": day,
        "pipeline_recorded_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "content_metadata": _content_metadata(topic, title, content, strategy),
        "strategy_snapshot": {
            "topic_focus": strategy.get("topic_focus", ""),
            "title_style": strategy.get("title_style", ""),
            "hook_strength": strategy.get("hook_strength", ""),
            "avoid_patterns": strategy.get("avoid_patterns", ""),
            "notes": strategy.get("notes", ""),
        },
    })
    profiles[video_id] = profile
    _save_profiles(profiles)
    return profile


def profilo_to_analytics_row(profile: dict) -> dict:
    """Converte profilo persistente in riga compatibile con leggi_performance."""
    m = profile.get("metrics") or {}
    dur = int(m.get("duration_seconds") or 0)
    avg_dur = float(m.get("avg_view_duration_seconds") or 0)
    ctr = float(m.get("ctr_percent") or 0)
    impressions = int(m.get("impressions") or 0)
    return {
        "video_id": profile.get("video_id"),
        "title": profile.get("title") or "",
        "published_at": profile.get("published_at") or "",
        "published_hour_utc": profile.get("published_hour_utc"),
        "published_day_utc": profile.get("published_day_utc"),
        "views": int(m.get("views") or 0),
        "likes": int(m.get("likes") or 0),
        "comments": int(m.get("comments") or 0),
        "shares": m.get("shares"),
        "subscribers_gained": m.get("subscribers_gained"),
        "duration_seconds": dur,
        "avg_view_duration_seconds": avg_dur,
        "avg_view_percentage": float(m.get("avg_view_percentage") or 0),
        "retention_percent": float(m.get("retention_percent") or 0),
        "retention_at_30s_percent": m.get("retention_at_30s_percent"),
        "estimated_minutes_watched": float(m.get("estimated_minutes_watched") or 0),
        "impressions": impressions,
        "ctr_percent": ctr,
        "ctr": ctr / 100.0 if ctr else 0,
        "performance_score": profile.get("performance_score"),
        "performance_tier": profile.get("performance_tier"),
    }


def _metric_block(row: dict) -> dict:
    """Estrae blocco metriche da riga analytics (tollerante a campi mancanti)."""
    dur = max(float(row.get("duration_seconds") or 1), 1.0)
    avg_dur = float(row.get("avg_view_duration_seconds") or 0)
    views = int(row.get("views") or 0)
    return {
        "views": views,
        "impressions": row.get("impressions"),
        "ctr_percent": round(float(row.get("ctr_percent") or 0), 3),
        "avg_view_duration_seconds": round(avg_dur, 2),
        "avg_view_percentage": round(float(row.get("avg_view_percentage") or 0), 2),
        "retention_percent": round(avg_dur / dur * 100, 2) if dur else 0.0,
        "retention_at_30s_percent": row.get("retention_at_30s_percent"),
        "estimated_minutes_watched": round(float(row.get("estimated_minutes_watched") or 0), 2),
        "likes": int(row.get("likes") or 0),
        "comments": int(row.get("comments") or 0),
        "shares": row.get("shares"),
        "subscribers_gained": row.get("subscribers_gained"),
        "duration_seconds": int(row.get("duration_seconds") or 0),
    }


def compute_score_breakdown(profile: dict, weights: dict | None = None) -> dict:
    """Score normalizzato 0–1 per componente + totale pesato."""
    weights = weights or _load_weights()
    m = profile.get("metrics") or {}
    published = profile.get("published_at")
    age_h = video_age_hours(published)
    age_days = max(age_h / 24.0, 0.25)

    views = float(m.get("views") or 0)
    ctr = float(m.get("ctr_percent") or 0)
    retention = float(m.get("retention_percent") or 0)
    if not retention and m.get("avg_view_duration_seconds"):
        dur = max(float(m.get("duration_seconds") or 1), 1.0)
        retention = float(m["avg_view_duration_seconds"]) / dur * 100

    dur_sec = max(float(m.get("duration_seconds") or 1), 1.0)
    watch_ratio = float(m.get("avg_view_duration_seconds") or 0) / dur_sec
    views_per_day = views / age_days

    likes = float(m.get("likes") or 0)
    comments = float(m.get("comments") or 0)
    engagement_rate = ((likes + comments * 2) / max(views, 1)) * 100

    subs = m.get("subscribers_gained")
    sub_rate = (float(subs) / max(views, 1) * 100) if subs is not None else None

    components = {
        "ctr": _norm_ratio(ctr, NORM["ctr_percent"]),
        "retention": _norm_ratio(retention, NORM["retention_percent"]),
        "watch_time": _norm_ratio(watch_ratio, NORM["watch_ratio"]),
        "views_velocity": _norm_ratio(views_per_day, NORM["views_per_day"]),
        "engagement": _norm_ratio(engagement_rate, NORM["engagement_rate"]),
    }
    if sub_rate is not None:
        components["subscribers"] = _norm_ratio(sub_rate, NORM["sub_rate"])
    else:
        components["subscribers"] = None

    total = 0.0
    used_weight = 0.0
    for key, w in weights.items():
        comp = components.get(key)
        if comp is None:
            continue
        total += w * comp
        used_weight += w
    if used_weight > 0:
        total /= used_weight

    return {
        "components": {k: round(v, 4) if v is not None else None for k, v in components.items()},
        "performance_score": round(total, 4),
        "age_hours": round(age_h, 2),
        "views_per_day": round(views_per_day, 2),
        "engagement_rate": round(engagement_rate, 3),
    }


def score_video(row: dict) -> float:
    """API compatibile — score 0–100 da profilo o riga analytics grezza."""
    if row.get("performance_score") is not None:
        return float(row["performance_score"]) * 100
    profile = {
        "published_at": row.get("published_at"),
        "metrics": _metric_block(row),
    }
    breakdown = compute_score_breakdown(profile)
    return breakdown["performance_score"] * 100


def aggiorna_profilo_da_analytics(row: dict, *, save: bool = True) -> dict:
    """Merge metriche API su profilo esistente o crea profilo minimo."""
    vid = row.get("video_id")
    if not vid:
        return {}
    profiles = _load_profiles()
    profile = profiles.get(vid, {"video_id": vid})
    profile["title"] = row.get("title") or profile.get("title", "")
    profile["published_at"] = row.get("published_at") or profile.get("published_at", "")
    hour, day = _published_meta(profile.get("published_at"))
    profile["published_hour_utc"] = row.get("published_hour_utc", hour)
    profile["published_day_utc"] = day
    profile["metrics"] = _metric_block(row)
    profile["metrics_updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    breakdown = compute_score_breakdown(profile)
    profile["score_breakdown"] = breakdown
    profile["performance_score"] = breakdown["performance_score"]
    profiles[vid] = profile
    if save:
        _save_profiles(profiles)
    return profile


def _refresh_tiers_on_disk(profiles: dict[str, dict]) -> None:
    """Ricalcola tier relativi su tutti i profili salvati."""
    all_profiles = list(profiles.values())
    apply_tier_classification(all_profiles)
    for p in all_profiles:
        profiles[p["video_id"]] = p


def sync_profiles(analytics_rows: list[dict]) -> list[dict]:
    """Aggiorna tutti i profili da righe analytics; ritorna lista ordinata per score."""
    updated = []
    profiles = _load_profiles()
    for row in analytics_rows:
        try:
            p = aggiorna_profilo_da_analytics(row, save=False)
            if p and p.get("video_id"):
                updated.append(p)
                profiles[p["video_id"]] = p
        except Exception as e:
            print(f"[performance] skip {row.get('video_id')}: {e}", flush=True)
    _refresh_tiers_on_disk(profiles)
    _save_profiles(profiles)
    try:
        from moduli.experimentation import evaluate_pending_experiments
        evaluate_pending_experiments(list(profiles.values()))
    except Exception as e:
        print(f"[experimentation] evaluate skip: {e}", flush=True)
    updated_ids = {p.get("video_id") for p in updated if p.get("video_id")}
    return sorted(
        [profiles[vid] for vid in updated_ids if vid in profiles],
        key=lambda p: p.get("performance_score") or 0,
        reverse=True,
    )


def carica_profili() -> list[dict]:
    profiles = sorted(
        _load_profiles().values(),
        key=lambda p: p.get("performance_score") or 0,
        reverse=True,
    )
    return apply_tier_classification(profiles)


def profilo_per_video(video_id: str) -> dict | None:
    return _load_profiles().get(video_id)


def performance_snapshot_for_strategy(profiles: list[dict] | None = None) -> list[dict]:
    """Vista compatta per strategia LLM — include score e metadati utili."""
    if profiles is None:
        profiles = carica_profili()
    out = []
    for p in sorted(profiles, key=lambda x: x.get("performance_score") or 0, reverse=True):
        m = p.get("metrics") or {}
        meta = p.get("content_metadata") or {}
        sb = p.get("score_breakdown") or {}
        out.append({
            "video_id": p.get("video_id"),
            "title": (p.get("title") or "")[:60],
            "topic": (p.get("topic") or meta.get("topic") or "")[:60],
            "tier": p.get("performance_tier", "average"),
            "views": m.get("views", 0),
            "ctr_pct": m.get("ctr_percent", 0),
            "retention_pct": m.get("retention_percent", 0),
            "views_per_day": sb.get("views_per_day", 0),
            "performance_score": round((p.get("performance_score") or 0) * 100, 1),
            "age_hours": sb.get("age_hours"),
            "topic_angle": meta.get("topic_angle", ""),
            "content_format": meta.get("content_format", ""),
            "title_pattern": meta.get("title_pattern", ""),
            "thumbnail_concept": meta.get("thumbnail_concept", ""),
        })
    return out
