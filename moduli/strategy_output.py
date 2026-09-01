"""
Output strategico strutturato — aggrega analytics, learning e LLM strategy.

Compatibilità: il dict piatto esistente (topic_focus string, avoid_patterns string)
resta invariato; il payload strutturato vive in strategy["structured"].
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from moduli.avoid_patterns import collect_avoid_patterns


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _split_focus(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    if not text:
        return []
    parts = re.split(r"[;\n]+|,(?=\s*[A-Za-z])", text)
    return [p.strip() for p in parts if p.strip()]


def _pattern_items(items: list | None, *, label_key: str = "pattern") -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items or []:
        if isinstance(item, str):
            val = item.strip()
            if not val or val.lower() in seen:
                continue
            seen.add(val.lower())
            out.append({label_key: val, "value": val})
        elif isinstance(item, dict):
            val = (item.get(label_key) or item.get("value") or item.get("topic") or "").strip()
            if not val or val.lower() in seen:
                continue
            seen.add(val.lower())
            row = dict(item)
            row.setdefault(label_key, val)
            row.setdefault("value", val)
            out.append(row)
    return out


def _title_pattern_items(analysis: dict | None) -> list[dict]:
    if not analysis:
        return []
    rows: list[dict] = []
    for wp in (analysis.get("winning_title_patterns") or [])[:8]:
        rows.append({
            "pattern_id": wp.get("pattern_id"),
            "label": wp.get("pattern_label"),
            "outcome": "winning",
            "avg_ctr": wp.get("avg_ctr"),
            "ctr_vs_channel": wp.get("ctr_vs_channel"),
            "sample_size": wp.get("sample_size"),
        })
    for lp in (analysis.get("losing_title_patterns") or [])[:4]:
        rows.append({
            "pattern_id": lp.get("pattern_id"),
            "label": lp.get("pattern_label"),
            "outcome": "losing",
            "score_vs_channel": lp.get("score_vs_channel"),
            "sample_size": lp.get("sample_size"),
        })
    return rows


def _hook_pattern_items(analysis: dict | None) -> list[dict]:
    if not analysis:
        return []
    rows: list[dict] = []
    for wp in (analysis.get("winning_hook_patterns") or [])[:6]:
        rows.append({
            "hook_id": wp.get("hook_id"),
            "label": wp.get("hook_label"),
            "outcome": "winning",
            "retention_vs_channel": wp.get("retention_vs_channel"),
            "sample_size": wp.get("sample_size"),
        })
    for lp in (analysis.get("losing_hook_patterns") or [])[:4]:
        rows.append({
            "hook_id": lp.get("hook_id"),
            "label": lp.get("hook_label"),
            "outcome": "losing",
            "retention_vs_channel": lp.get("retention_vs_channel"),
            "sample_size": lp.get("sample_size"),
        })
    return rows


def _thumbnail_pattern_items(analysis: dict | None) -> list[dict]:
    if not analysis:
        return []
    rows: list[dict] = []
    for wt in (analysis.get("winning_traits") or [])[:6]:
        rows.append({
            "dimension": wt.get("dimension"),
            "value": wt.get("value"),
            "outcome": "winning",
            "avg_ctr": wt.get("avg_ctr"),
            "ctr_vs_channel": wt.get("ctr_vs_channel"),
            "sample_size": wt.get("sample_size"),
        })
    for lt in (analysis.get("losing_traits") or [])[:4]:
        rows.append({
            "dimension": lt.get("dimension"),
            "value": lt.get("value"),
            "outcome": "losing",
            "ctr_vs_channel": lt.get("ctr_vs_channel"),
            "sample_size": lt.get("sample_size"),
        })
    return rows


def _preferred_formats(strategy: dict, insights: dict) -> list[str]:
    formats: list[str] = []
    seen: set[str] = set()

    def _add(val: str) -> None:
        v = (val or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            formats.append(v)

    _add(strategy.get("content_format"))
    for item in insights.get("script_optimization", {}).get("recommendations") or []:
        if item.get("dimension") == "content_format":
            _add(item.get("value"))
    try:
        from moduli.strategy_memory import memory_for_llm
        for fmt in memory_for_llm().get("successful_formats") or []:
            if isinstance(fmt, dict):
                _add(fmt.get("value") or fmt.get("pattern"))
            else:
                _add(str(fmt))
    except Exception:
        pass
    for exp in (insights.get("experimentation") or {}).get("winning_pool") or []:
        dims = exp.get("dimensions") or {}
        _add(dims.get("content_format"))
    return formats[:8]


def _evidence_video_ids(profiles: list[dict] | None, insights: dict) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for p in profiles or []:
        vid = p.get("video_id")
        if vid and vid not in seen:
            seen.add(vid)
            ids.append(vid)
    for wp in (insights.get("winning_patterns") or []):
        for vid in wp.get("evidence_video_ids") or []:
            if vid and vid not in seen:
                seen.add(vid)
                ids.append(vid)
    return ids[:30]


def build_structured_strategy(
    strategy: dict,
    insights: dict,
    *,
    state: dict | None = None,
    profiles: list | None = None,
    pref: dict | None = None,
) -> dict:
    """
    Costruisce l'oggetto strategico strutturato da strategy LLM + insights analytics.
    """
    strategy = strategy or {}
    insights = insights or {}
    state = state or {}
    pref = pref or {}

    conf = insights.get("channel_confidence") or {}
    confidence = str(conf.get("level") or "LOW").lower()
    sample_size = int(conf.get("video_count") or insights.get("video_count") or 0)

    topic_focus = _split_focus(strategy.get("topic_focus"))
    try:
        from moduli.strategy_memory import memory_for_llm
        for item in memory_for_llm().get("successful_topics") or []:
            val = item.get("topic") if isinstance(item, dict) else str(item)
            if val and val not in topic_focus:
                topic_focus.append(val.strip())
    except Exception:
        pass
    topic_focus = topic_focus[:10]

    winning = _pattern_items(
        (strategy.get("_winning_patterns") or insights.get("winning_patterns") or []),
    )
    losing = _pattern_items(
        (strategy.get("_losing_patterns") or insights.get("losing_patterns") or []),
    )

    avoid_list = collect_avoid_patterns(strategy, pref)
    if not avoid_list:
        avoid_list = _split_focus(strategy.get("avoid_patterns"))

    title_analysis = insights.get("title_pattern_analysis") or {}
    hook_analysis = insights.get("hook_pattern_analysis") or {}
    thumb_analysis = insights.get("thumbnail_pattern_analysis") or {}
    pub = insights.get("publish_timing_analysis") or {}

    best_hours = list(state.get("best_hours_utc") or [])
    if not best_hours:
        best_hours = list(pub.get("recommended_hours_utc") or [])
    try:
        from moduli.strategy_memory import memory_for_llm
        mem_hours = memory_for_llm().get("recommended_publish_hours_utc") or []
        for h in mem_hours:
            if isinstance(h, int) and h not in best_hours:
                best_hours.append(h)
    except Exception:
        pass
    best_hours = sorted({int(h) for h in best_hours if h is not None})[:6]

    try:
        from moduli.topic_diversity import explore_ratio
        exploration_ratio = round(float(explore_ratio()), 3)
    except Exception:
        exploration_ratio = 0.25

    preferred_duration = strategy.get("target_minutes")
    if preferred_duration is None:
        preferred_duration = insights.get("suggested_target_minutes")
    try:
        preferred_duration = int(preferred_duration) if preferred_duration is not None else None
    except (TypeError, ValueError):
        preferred_duration = None

    notes = strategy.get("notes") or ""
    if isinstance(notes, list):
        notes = "; ".join(str(n) for n in notes)

    structured = {
        "generated_at": _now(),
        "topic_focus": topic_focus,
        "winning_patterns": winning,
        "losing_patterns": losing,
        "avoid_patterns": avoid_list,
        "title_patterns": _title_pattern_items(title_analysis),
        "hook_patterns": _hook_pattern_items(hook_analysis),
        "thumbnail_patterns": _thumbnail_pattern_items(thumb_analysis),
        "preferred_formats": _preferred_formats(strategy, insights),
        "preferred_duration": preferred_duration,
        "best_hours_utc": best_hours,
        "exploration_ratio": exploration_ratio,
        "confidence": confidence,
        "sample_size": sample_size,
        "notes": str(notes).strip(),
        "evidence_video_ids": _evidence_video_ids(profiles, insights),
        # estensioni utili — non rompono il contratto base
        "optimization_mode": conf.get("optimization_mode"),
        "avg_ctr": insights.get("avg_ctr"),
        "avg_retention": insights.get("avg_retention"),
        "avg_performance_score": insights.get("avg_performance_score"),
        "publish_timing": {
            "recommended_hours_utc": pub.get("recommended_hours_utc") or [],
            "recommended_days": pub.get("recommended_days") or [],
            "sufficient_evidence": bool(pub.get("sufficient_evidence")),
        },
        "experimentation": {
            "pending": (insights.get("experimentation") or {}).get("pending_experiments", 0),
            "promoted": (insights.get("experimentation") or {}).get("promoted_experiments", 0),
            "recent": (insights.get("experimentation") or {}).get("recent") or [],
        },
        "learning_summary": insights.get("learning_summary"),
        "audience_summary": (insights.get("learning_summary") or {}).get("audience_summary") or [],
    }
    return structured


def attach_structured_strategy(
    strategy: dict,
    insights: dict,
    *,
    state: dict | None = None,
    profiles: list | None = None,
    pref: dict | None = None,
) -> dict:
    """Aggiunge strategy['structured'] mantenendo i campi piatti legacy."""
    structured = build_structured_strategy(
        strategy, insights, state=state, profiles=profiles, pref=pref,
    )
    strategy["structured"] = structured
    # Mirror chiave campione per tool esterni / Telegram
    strategy["_confidence"] = structured.get("confidence")
    strategy["_sample_size"] = structured.get("sample_size")
    return strategy


def structured_summary_text(structured: dict | None) -> str:
    """Riepilogo compatto per log / Telegram."""
    if not structured:
        return "No structured strategy available."
    lines = [
        f"Confidence: {structured.get('confidence', '?').upper()} "
        f"(n={structured.get('sample_size', 0)})",
        f"Exploration ratio: {structured.get('exploration_ratio', '?')}",
        f"Preferred duration: {structured.get('preferred_duration', '?')} min",
    ]
    if structured.get("best_hours_utc"):
        lines.append(f"Best hours UTC: {structured['best_hours_utc']}")
    if structured.get("topic_focus"):
        lines.append(f"Topic focus: {', '.join(structured['topic_focus'][:4])}")
    if structured.get("winning_patterns"):
        wins = [
            (w.get("pattern") or w.get("value") or "")[:50]
            for w in structured["winning_patterns"][:3]
        ]
        lines.append(f"Winning: {'; '.join(w for w in wins if w)}")
    if structured.get("avoid_patterns"):
        lines.append(f"Avoid: {'; '.join(structured['avoid_patterns'][:4])}")
    if structured.get("notes"):
        lines.append(f"Notes: {str(structured['notes'])[:200]}")
    return "\n".join(lines)
