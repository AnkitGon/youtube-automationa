"""
Compact analytics → learning summaries for strategy and content generation.

Consumes video profiles + channel audience reports from moduli/analytics.py.
Does NOT duplicate API calls or parallel storage — enriches strategia insights.
"""

from __future__ import annotations

import statistics
from typing import Any


def _median(values: list[float]) -> float:
    vals = [v for v in values if v is not None and v == v]
    if not vals:
        return 0.0
    return float(statistics.median(vals))


def compute_channel_baselines(profiles: list[dict]) -> dict:
    """Channel-relative baselines from published video profiles."""
    ctrs, rets, views_day, watch_min, sub_rates, impressions = [], [], [], [], [], []
    for p in profiles:
        m = p.get("metrics") or {}
        if not m.get("views") and not m.get("impressions"):
            continue
        ctrs.append(float(m.get("ctr_percent") or 0))
        ret = float(m.get("retention_percent") or 0)
        if not ret and m.get("avg_view_duration_seconds"):
            dur = max(float(m.get("duration_seconds") or 1), 1.0)
            ret = float(m["avg_view_duration_seconds"]) / dur * 100
        rets.append(ret)
        views = float(m.get("views") or 0)
        from moduli.performance import video_age_hours
        age_days = max(video_age_hours(p.get("published_at")) / 24.0, 0.25)
        views_day.append(views / age_days)
        watch_min.append(float(m.get("estimated_minutes_watched") or 0))
        impressions.append(float(m.get("impressions") or 0))
        sg = m.get("subscribers_gained")
        if sg is not None and views > 0:
            sub_rates.append(float(sg) / views * 100)

    n = len(ctrs)
    return {
        "sample_size": n,
        "median_ctr": round(_median(ctrs), 2),
        "median_retention": round(_median(rets), 1),
        "median_views_per_day": round(_median(views_day), 1),
        "median_watch_minutes": round(_median(watch_min), 1),
        "median_impressions": round(_median(impressions), 0),
        "median_sub_rate": round(_median(sub_rates), 3) if sub_rates else None,
    }


def _strength(value: float, baseline: float, *, higher_is_better: bool = True) -> str:
    if baseline <= 0:
        return "insufficient_data"
    ratio = value / baseline
    if higher_is_better:
        if ratio >= 1.25:
            return "strong"
        if ratio >= 0.85:
            return "average"
        return "weak"
    if ratio <= 0.75:
        return "strong"
    if ratio <= 1.15:
        return "average"
    return "weak"


def diagnose_video_card(profile: dict, baselines: dict) -> dict:
    """Per-video signals vs channel history — compact, no raw dumps."""
    m = profile.get("metrics") or {}
    title = (profile.get("title") or "")[:60]
    views = int(m.get("views") or 0)
    ctr = float(m.get("ctr_percent") or 0)
    ret = float(m.get("retention_percent") or 0)
    if not ret and m.get("avg_view_duration_seconds"):
        dur = max(float(m.get("duration_seconds") or 1), 1.0)
        ret = float(m["avg_view_duration_seconds"]) / dur * 100
    watch_min = float(m.get("estimated_minutes_watched") or 0)
    impressions = int(m.get("impressions") or 0)
    subs = m.get("subscribers_gained")

    b = baselines
    n = b.get("sample_size") or 0
    if n < 2:
        return {
            "title": title,
            "video_id": profile.get("video_id"),
            "views": views,
            "confidence": "insufficient_data",
            "diagnosis": "Too few channel videos for relative comparison.",
        }

    ctr_s = _strength(ctr, b["median_ctr"])
    ret_s = _strength(ret, b["median_retention"])
    watch_s = _strength(watch_min, b["median_watch_minutes"])
    from moduli.performance import video_age_hours
    vpd = views / max(video_age_hours(profile.get("published_at")) / 24.0, 0.25)
    views_s = _strength(vpd, b["median_views_per_day"])

    sub_rate = (float(subs) / views * 100) if subs is not None and views > 0 else None
    sub_s = (
        _strength(sub_rate, b["median_sub_rate"])
        if sub_rate is not None and b.get("median_sub_rate")
        else "insufficient_data"
    )

    diagnosis_parts = []
    if ctr_s == "strong" and ret_s == "weak":
        diagnosis_parts.append("packaging may overpromise (high CTR, weak retention)")
    elif ctr_s == "weak" and ret_s == "strong":
        diagnosis_parts.append("strong content, weak packaging (improve title/thumbnail)")
    elif views_s == "strong" and sub_s == "weak":
        diagnosis_parts.append("views without subscriber conversion — deepen value/differentiation")
    elif ret_s == "strong" and watch_s == "strong":
        diagnosis_parts.append("viewers stayed — replicate topic depth and pacing")
    elif ctr_s == "weak" and ret_s == "weak":
        diagnosis_parts.append("underperforming on packaging and delivery")
    else:
        diagnosis_parts.append("mixed signals — iterate cautiously")

    meta = profile.get("content_metadata") or {}
    return {
        "title": title,
        "video_id": profile.get("video_id"),
        "views": views,
        "impressions": impressions,
        "ctr_percent": round(ctr, 2),
        "retention_percent": round(ret, 1),
        "watch_minutes": round(watch_min, 1),
        "subscribers_gained": subs,
        "ctr_strength": ctr_s,
        "retention_strength": ret_s,
        "watch_time_strength": watch_s,
        "views_velocity_strength": views_s,
        "subscriber_strength": sub_s,
        "topic_category": (meta.get("topic_category") or "")[:80],
        "title_pattern": meta.get("title_pattern") or "",
        "hook_type": meta.get("hook_type") or "",
        "diagnosis": "; ".join(diagnosis_parts),
        "confidence": "low" if n <= 2 else ("medium" if n <= 5 else "high"),
    }


def _summarize_audience(bundle: dict | None) -> list[str]:
    lines: list[str] = []
    if not bundle:
        return lines

    grid = bundle.get("hour_grid") or {}
    if grid.get("has_data"):
        top = grid.get("buckets") or []
        if top:
            b = top[0]
            lines.append(
                f"Peak viewer activity: {b.get('day_name', '?')} "
                f"{int(b.get('hour', 0)):02d}:00 audience local grid "
                f"({b.get('views', 0)} views in period)"
            )

    traffic = bundle.get("traffic_sources") or {}
    if traffic.get("has_data"):
        srcs = traffic.get("sources") or []
        if srcs:
            top3 = ", ".join(
                f"{s['source_type']} ({s['views']})" for s in srcs[:3]
            )
            lines.append(f"Traffic sources: {top3}")

    demo = bundle.get("demographics") or {}
    if demo.get("has_data"):
        segs = demo.get("segments") or []
        if segs:
            top = segs[0]
            lines.append(
                f"Top demographic: {top.get('age_group')} {top.get('gender')} "
                f"({top.get('viewer_percentage')}% of viewers)"
            )

    geo = bundle.get("geography") or {}
    if geo.get("has_data"):
        countries = geo.get("countries") or []
        if countries:
            top_c = ", ".join(f"{c['country']} ({c['views']})" for c in countries[:3])
            lines.append(f"Top geographies: {top_c}")

    sub = bundle.get("subscriber_watch") or {}
    if sub.get("has_data"):
        segs = {s["status"]: s for s in sub.get("segments") or []}
        subbed = segs.get("SUBSCRIBED") or segs.get("subscribed")
        unsub = segs.get("UNSUBSCRIBED") or segs.get("unsubscribed")
        if subbed and unsub:
            lines.append(
                f"Watch time split: subscribers {subbed.get('estimated_minutes_watched', 0):.0f} min "
                f"vs non-subscribers {unsub.get('estimated_minutes_watched', 0):.0f} min"
            )

    monthly = bundle.get("monthly") or {}
    if monthly.get("has_data") and len(monthly.get("months") or []) >= 2:
        months = monthly["months"]
        recent = months[-1].get("views", 0)
        prior = months[-2].get("views", 0)
        if prior > 0:
            delta = (recent - prior) / prior * 100
            lines.append(f"Monthly views trend: {delta:+.0f}% vs prior month")

    return lines


def build_action_signals(
    profiles: list[dict],
    baselines: dict,
    video_cards: list[dict],
    audience_lines: list[str],
    insights: dict | None = None,
) -> list[str]:
    """Deterministic strategy actions — compared to channel history only."""
    signals: list[str] = []
    n = baselines.get("sample_size") or 0
    insights = insights or {}

    if n == 0:
        signals.append("INSUFFICIENT DATA — use preferences; do not claim performance patterns.")
        return signals
    if n <= 2:
        signals.append(
            f"EARLY SAMPLE (n={n}) — conservative strategy only; topic dedup always enforced."
        )
    elif n <= 5:
        signals.append(f"GROWING SAMPLE (n={n}) — prefer trends across multiple videos, not one outlier.")

    conf = (insights.get("channel_confidence") or {}).get("level", "LOW")
    signals.append(f"Channel confidence: {conf} (n={n})")

    overpromise = sum(
        1 for c in video_cards
        if c.get("ctr_strength") == "strong" and c.get("retention_strength") == "weak"
    )
    if overpromise:
        signals.append(
            f"PACKAGING RISK — {overpromise} video(s) show high CTR + weak retention; "
            "tone down title/thumbnail promises, deliver earlier value in script."
        )

    weak_pack = sum(
        1 for c in video_cards
        if c.get("ctr_strength") == "weak" and c.get("retention_strength") == "strong"
    )
    if weak_pack:
        signals.append(
            f"PACKAGING OPPORTUNITY — {weak_pack} video(s) retain well but CTR is weak; "
            "sharpen titles/thumbnails without changing core topic depth."
        )

    low_sub = sum(
        1 for c in video_cards
        if c.get("views_velocity_strength") in ("strong", "average")
        and c.get("subscriber_strength") == "weak"
    )
    if low_sub and n >= 3:
        signals.append(
            "SUBSCRIBER GAP — views without conversion; strengthen differentiation and subscribe-worthy payoff."
        )

    for line in audience_lines[:6]:
        signals.append(f"AUDIENCE — {line}")

    for s in (insights.get("signals") or [])[:8]:
        if s not in signals:
            signals.append(s)

    return signals


def build_compact_learning_summary(
    profiles: list[dict],
    insights: dict | None = None,
    *,
    channel_bundle: dict | None = None,
) -> dict:
    """
    Build compact learning artifact for strategy LLM + cervello prompts.
    Never includes raw API rows — only interpreted signals.
    """
    insights = insights or {}
    baselines = compute_channel_baselines(profiles)
    ranked = sorted(
        profiles,
        key=lambda p: float((p.get("metrics") or {}).get("views") or 0),
        reverse=True,
    )
    video_cards = [diagnose_video_card(p, baselines) for p in ranked[:8]]
    audience_lines = _summarize_audience(channel_bundle)
    action_signals = build_action_signals(
        profiles, baselines, video_cards, audience_lines, insights,
    )

    text_lines = [
        f"Channel baselines (n={baselines['sample_size']}): "
        f"CTR {baselines['median_ctr']}% | retention {baselines['median_retention']}% | "
        f"views/day {baselines['median_views_per_day']}",
    ]
    for card in video_cards[:5]:
        text_lines.append(
            f"- '{card['title']}' — CTR {card.get('ctr_strength')}, "
            f"retention {card.get('retention_strength')}, "
            f"watch {card.get('watch_time_strength')}: {card.get('diagnosis')}"
        )
    for sig in action_signals[:12]:
        text_lines.append(f"→ {sig}")

    return {
        "baselines": baselines,
        "video_cards": video_cards,
        "audience_summary": audience_lines,
        "action_signals": action_signals,
        "text_block": "\n".join(text_lines),
        "reports_available": (channel_bundle or {}).get("reports_available") or [],
    }


def enrich_insights_with_learning(
    insights: dict,
    profiles: list[dict],
    *,
    channel_bundle: dict | None = None,
) -> dict:
    """Attach compact learning summary to strategia insights dict."""
    summary = build_compact_learning_summary(profiles, insights, channel_bundle=channel_bundle)
    insights = dict(insights)
    insights["learning_summary"] = summary
    insights["signals"] = summary["action_signals"]
    return insights


def insights_for_llm(insights: dict) -> dict:
    """Trim insights for LLM prompt — compact signals, not full nested analyses."""
    summary = insights.get("learning_summary") or {}
    return {
        "video_count": insights.get("video_count"),
        "channel_confidence": insights.get("channel_confidence"),
        "baselines": summary.get("baselines") or insights.get("channel_median_score"),
        "avg_ctr": insights.get("avg_ctr"),
        "avg_retention": insights.get("avg_retention"),
        "suggested_target_minutes": insights.get("suggested_target_minutes"),
        "winning_patterns": (insights.get("winning_patterns") or [])[:6],
        "losing_patterns": (insights.get("losing_patterns") or [])[:6],
        "action_signals": (summary.get("action_signals") or insights.get("signals") or [])[:15],
        "video_diagnoses": [
            {
                "title": c.get("title"),
                "ctr": c.get("ctr_strength"),
                "retention": c.get("retention_strength"),
                "diagnosis": c.get("diagnosis"),
            }
            for c in (summary.get("video_cards") or [])[:5]
        ],
        "audience_summary": summary.get("audience_summary") or [],
        "reports_available": summary.get("reports_available") or [],
    }


def learning_block_for_prompt(strategy: dict) -> str:
    """Compact block for topic/content prompts."""
    parts: list[str] = []
    structured = strategy.get("structured") or {}
    summary = strategy.get("_learning_summary") or structured.get("learning_summary")
    if isinstance(summary, dict):
        block = summary.get("text_block")
        if block:
            parts.append(block)
    elif isinstance(summary, str) and summary.strip():
        parts.append(summary.strip())

    try:
        from moduli.shared_learning import shorts_insights_for_longform
        shorts_lines = shorts_insights_for_longform()
        for line in shorts_lines[:4]:
            parts.append(f"Shorts learning: {line}")
    except Exception:
        pass

    try:
        from moduli.channel_learning import load_channel_learning
        cl = load_channel_learning()
        stage = cl.get("learning_stage")
        if stage:
            parts.append(f"Learning stage: {stage}")
        for lesson in (cl.get("content_quality_lessons") or [])[:3]:
            parts.append(f"Quality lesson: {lesson}")
        traps = cl.get("clickbait_traps") or []
        for t in traps[:2]:
            parts.append(f"Clickbait trap to avoid: {t}")
        from moduli.channel_learning import category_reuse_reminder
        parts.append(category_reuse_reminder())
    except Exception:
        pass

    if not parts:
        return "(no analytics learning yet — preferences only)"
    return "\n".join(parts)


def persist_content_quality_lessons(summary: dict) -> None:
    """Cumulative packaging/retention lessons in channel_learning.json."""
    try:
        from moduli.channel_learning import load_channel_learning, save_channel_learning
    except ImportError:
        return
    data = load_channel_learning()
    lessons = list(data.get("content_quality_lessons") or [])
    for card in summary.get("video_cards") or []:
        if card.get("confidence") == "insufficient_data":
            continue
        diag = card.get("diagnosis") or ""
        if "overpromise" in diag or "packaging" in diag.lower():
            entry = f"{card.get('title', '')[:40]}: {diag}"
            if entry not in lessons:
                lessons.append(entry)
    data["content_quality_lessons"] = lessons[-20:]
    save_channel_learning(data)
