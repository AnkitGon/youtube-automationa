"""
Subscriber conversion learning from performance profiles.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from moduli.channel_confidence import confidence_from_profiles


def _sub_rate(profile: dict) -> float | None:
    m = profile.get("metrics") or {}
    sg = m.get("subscribers_gained")
    views = int(m.get("views") or 0)
    if sg is None or views < 10:
        return None
    return float(sg) / views * 100


def analyze_subscriber_patterns(profiles: list[dict]) -> dict:
    """Identify formats/topics/title patterns that convert viewers to subscribers."""
    conf = confidence_from_profiles(profiles)
    usable = [p for p in profiles if _sub_rate(p) is not None]
    empty = {
        "has_data": False,
        "confidence": conf.level,
        "video_count": len(usable),
        "channel_median_sub_rate": None,
        "winning_patterns": [],
        "losing_patterns": [],
        "guidance": "Insufficient subscriber data — focus on viewer value, not CTAs.",
    }
    if len(usable) < 2:
        return empty

    rates = [_sub_rate(p) for p in usable]
    median = statistics.median(rates)

    def _bucket(key_fn):
        buckets: dict[str, list[float]] = defaultdict(list)
        for p in usable:
            meta = p.get("content_metadata") or {}
            key = key_fn(p, meta)
            if key:
                r = _sub_rate(p)
                if r is not None:
                    buckets[str(key)].append(r)
        rows = []
        for key, vals in buckets.items():
            if len(vals) < max(1, conf.min_bucket_samples - 1):
                continue
            avg = statistics.mean(vals)
            rows.append({
                "pattern": key,
                "sample_size": len(vals),
                "avg_sub_rate_pct": round(avg, 3),
                "vs_median": round(avg - median, 3),
            })
        rows.sort(key=lambda x: x["vs_median"], reverse=True)
        return rows

    winners = _bucket(lambda p, m: m.get("content_format") or m.get("topic_category"))[:5]
    losers = sorted(
        _bucket(lambda p, m: m.get("title_pattern")),
        key=lambda x: x["vs_median"],
    )[:3]

    guidance_lines = []
    if winners:
        guidance_lines.append(
            "Formats/categories that convert subscribers: "
            + ", ".join(w["pattern"] for w in winners[:3])
        )
    guidance_lines.append(
        "Do NOT use desperate subscribe begging — value and channel identity drive subs."
    )

    return {
        "has_data": True,
        "confidence": conf.level,
        "video_count": len(usable),
        "channel_median_sub_rate": round(median, 3),
        "winning_patterns": [w for w in winners if w["vs_median"] > 0],
        "losing_patterns": [l for l in losers if l["vs_median"] < 0],
        "guidance": " ".join(guidance_lines),
    }


def subscriber_guidance_block(strategy: dict | None = None) -> str:
    try:
        from moduli.performance import carica_profili
        analysis = analyze_subscriber_patterns(carica_profili())
    except Exception:
        return ""
    if not analysis.get("has_data"):
        return ""
    lines = ["SUBSCRIBER CONVERSION (from channel data):"]
    lines.append(analysis.get("guidance", ""))
    for w in (analysis.get("winning_patterns") or [])[:2]:
        lines.append(
            f"- Strong sub conversion: {w['pattern']} "
            f"(+{w['vs_median']:.2f}% vs median, n={w['sample_size']})"
        )
    return "\n".join(lines)
