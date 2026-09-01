"""
Memoria strategica persistente — rollup cumulativo + snapshot per ciclo.

- strategia_storia.json: lista cronologica (compatibile con formato legacy)
- strategy_memory.json: apprendimenti aggregati con evidenze e confidence
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

MEMORY_FILE = "strategy_memory.json"
HISTORY_FILE = "strategia_storia.json"
MAX_HISTORY = 30
MAX_ROLLUP_PATTERNS = 40

_WINNER_TIERS = frozenset({"breakout", "strong"})
_LOSER_TIERS = frozenset({"weak", "poor"})


def _now_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_history() -> list:
    data = _load_json(HISTORY_FILE, [])
    return data if isinstance(data, list) else []


def save_history(history: list) -> None:
    _save_json(HISTORY_FILE, history[-MAX_HISTORY:])


def load_memory() -> dict:
    data = _load_json(MEMORY_FILE, {})
    if not isinstance(data, dict):
        return _empty_memory()
    data.setdefault("rollup", _empty_rollup())
    data.setdefault("recent_cycles", [])
    return data


def _empty_rollup() -> dict:
    return {
        "winning_patterns": [],
        "losing_patterns": [],
        "successful_topics": [],
        "unsuccessful_topics": [],
        "successful_title_patterns": [],
        "unsuccessful_title_patterns": [],
        "successful_thumbnail_patterns": [],
        "unsuccessful_thumbnail_patterns": [],
        "successful_formats": [],
        "unsuccessful_formats": [],
        "recommended_topic_directions": [],
        "recommended_title_directions": [],
        "recommended_hook_directions": [],
        "recommended_duration_minutes": None,
        "recommended_publish_hours_utc": [],
        "avoid_patterns": [],
    }


def _empty_memory() -> dict:
    return {
        "updated_at": None,
        "cycles": 0,
        "rollup": _empty_rollup(),
        "recent_cycles": [],
    }


def _confidence(times_seen: int, evidence_count: int, vs_median: float = 0) -> float:
    base = 0.25 + times_seen * 0.12 + min(evidence_count, 5) * 0.08
    if abs(vs_median) >= 15:
        base += 0.1
    if evidence_count >= 3:
        base += 0.1
    return round(min(base, 0.95), 2)


def _video_ref(profile: dict) -> dict:
    meta = profile.get("content_metadata") or {}
    m = profile.get("metrics") or {}
    score = profile.get("performance_score")
    return {
        "video_id": profile.get("video_id"),
        "title": (profile.get("title") or "")[:60],
        "topic": (profile.get("topic") or meta.get("topic") or "")[:80],
        "tier": profile.get("performance_tier", "average"),
        "score": round(float(score) * 100, 1) if score is not None else None,
        "ctr_pct": m.get("ctr_percent"),
        "retention_pct": m.get("retention_percent"),
    }


def _collect_from_profiles(profiles: list[dict]) -> dict:
    """Estrae topic/titoli/thumbnail/formati da profili per tier."""
    winners, losers = [], []
    for p in profiles:
        tier = p.get("performance_tier", "average")
        ref = _video_ref(p)
        meta = p.get("content_metadata") or {}
        if tier in _WINNER_TIERS:
            winners.append((p, ref, meta))
        elif tier in _LOSER_TIERS:
            losers.append((p, ref, meta))

    def _topics(group):
        """Categorie/temi vincenti — mai il topic letterale da ripetere."""
        out = []
        for _p, ref, meta in group:
            category = (meta.get("topic_category") or meta.get("topic_angle") or "").strip()
            if not category:
                try:
                    from moduli.performance import infer_topic_themes
                    themes = infer_topic_themes(ref.get("title") or "", ref.get("topic") or "")
                    category = themes[0] if themes else ""
                except Exception:
                    category = ""
            if not category:
                continue
            out.append({
                "value": category,
                "pattern": category,
                "story_category": category,
                "example_title": (ref.get("title") or "")[:60],
                "video_id": ref.get("video_id"),
                "score": ref.get("score"),
            })
        return out

    def _values(group, key):
        out = []
        for _p, ref, meta in group:
            val = (meta.get(key) or "").strip()
            if val:
                out.append({
                    "value": val,
                    "video_id": ref.get("video_id"),
                    "title": ref.get("title"),
                    "score": ref.get("score"),
                })
        return out

    publish_hours: dict[int, list[float]] = defaultdict(list)
    durations: list[tuple[float, int]] = []
    for p in profiles:
        score = float(p.get("performance_score") or 0)
        hour = p.get("published_hour_utc")
        if hour is not None:
            publish_hours[int(hour)].append(score)
        dur = (p.get("metrics") or {}).get("duration_seconds")
        if dur:
            durations.append((score, int(dur)))

    rec_hours = sorted(
        publish_hours.keys(),
        key=lambda h: sum(publish_hours[h]) / len(publish_hours[h]),
        reverse=True,
    )[:4]

    rec_duration = None
    if durations:
        best = max(durations, key=lambda x: x[0])
        rec_duration = max(1, round(best[1] / 60))

    hooks_win = _values(winners, "hook_strength")
    hooks_lose = _values(losers, "hook_strength")

    return {
        "successful_topics": _topics(winners),
        "unsuccessful_topics": _topics(losers),
        "successful_title_patterns": _values(winners, "title_pattern"),
        "unsuccessful_title_patterns": _values(losers, "title_pattern"),
        "successful_thumbnail_patterns": _values(winners, "thumbnail_concept"),
        "unsuccessful_thumbnail_patterns": _values(losers, "thumbnail_concept"),
        "successful_formats": _values(winners, "content_format"),
        "unsuccessful_formats": _values(losers, "content_format"),
        "recommended_hook_directions": [
            h["value"] for h in hooks_win if h["value"] not in {x["value"] for x in hooks_lose}
        ][:5],
        "recommended_publish_hours_utc": rec_hours,
        "recommended_duration_minutes": rec_duration,
    }


def build_cycle_entry(
    profiles: list[dict],
    insights: dict,
    strategy: dict,
    top_performers: list[dict],
    underperformers: list[dict],
) -> dict:
    """Snapshot ricco per un ciclo strategia — estende formato legacy."""
    collected = _collect_from_profiles(profiles)
    video_ids = [p.get("video_id") for p in profiles if p.get("video_id")]
    winning = insights.get("winning_patterns") or []
    losing = insights.get("losing_patterns") or []

    avoid = (strategy.get("avoid_patterns") or "").strip()
    if not avoid:
        avoid = "; ".join(lp.get("pattern", "") for lp in losing[:4])

    confidence = 0.35
    if insights.get("video_count", 0) >= 3:
        confidence = 0.55
    if insights.get("video_count", 0) >= 5 and (winning or losing):
        confidence = 0.72
    if insights.get("winners_count", 0) >= 2 and winning:
        confidence = min(0.9, confidence + 0.15)

    entry = {
        "date": _now_label(),
        # --- campi memoria estesa ---
        "videos_analyzed": insights.get("video_count", len(profiles)),
        "video_ids": video_ids,
        "evidence_video_ids": video_ids,
        "winning_patterns": winning,
        "losing_patterns": losing,
        "successful_topics": collected["successful_topics"],
        "unsuccessful_topics": collected["unsuccessful_topics"],
        "successful_title_patterns": collected["successful_title_patterns"],
        "unsuccessful_title_patterns": collected["unsuccessful_title_patterns"],
        "successful_thumbnail_patterns": collected["successful_thumbnail_patterns"],
        "unsuccessful_thumbnail_patterns": collected["unsuccessful_thumbnail_patterns"],
        "successful_formats": collected["successful_formats"],
        "unsuccessful_formats": collected["unsuccessful_formats"],
        "recommended_topic_directions": [
            v for v in (strategy.get("topic_focus", ""), strategy.get("preferred_angle", "")) if v
        ],
        "recommended_title_directions": [v for v in (strategy.get("title_style", ""),) if v],
        "recommended_hook_directions": collected["recommended_hook_directions"] or [
            strategy.get("hook_strength", "")
        ],
        "recommended_duration_minutes": (
            strategy.get("target_minutes") or collected["recommended_duration_minutes"]
        ),
        "recommended_publish_hours_utc": collected["recommended_publish_hours_utc"],
        "avoid_patterns": avoid,
        "confidence_level": confidence,
        # --- compatibilità legacy strategia_storia.json ---
        "strategy": strategy,
        "top_performers": top_performers,
        "underperformers": underperformers,
        "analytics_insights": insights,
    }
    return entry


def _merge_evidence_list(existing: list, new_items: list, key_field: str = "pattern") -> list:
    """Accumula evidenze per pattern/topic con confidence crescente."""
    index: dict[str, dict] = {}
    for item in existing:
        key = str(item.get(key_field) or item.get("value") or item.get("topic") or "")
        if key:
            index[key] = dict(item)

    for item in new_items:
        if isinstance(item, str):
            key, payload = item, {"value": item}
        else:
            key = str(item.get(key_field) or item.get("value") or item.get("topic") or "")
            payload = dict(item)
        if not key:
            continue

        prev = index.get(key, {key_field: key, "value": key, "evidence_video_ids": [], "times_seen": 0})
        prev_times = int(prev.get("times_seen") or 0)
        new_ids = []
        if isinstance(item, dict):
            vid = item.get("video_id")
            if vid:
                new_ids.append(vid)
            for vid in item.get("evidence_video_ids") or []:
                new_ids.append(vid)
        evidence = list(dict.fromkeys((prev.get("evidence_video_ids") or []) + new_ids))
        vs = float(payload.get("vs_channel_median") or prev.get("vs_channel_median") or 0)
        index[key] = {
            **prev,
            **{k: v for k, v in payload.items() if v is not None},
            "evidence_video_ids": evidence[:20],
            "times_seen": prev_times + 1,
            "last_seen": _now_label(),
            "confidence_level": _confidence(prev_times + 1, len(evidence), vs),
        }

    ranked = sorted(index.values(), key=lambda x: (x.get("confidence_level", 0), x.get("times_seen", 0)), reverse=True)
    return ranked[:MAX_ROLLUP_PATTERNS]


def _merge_simple_list(existing: list, new_items: list, key_field: str = "value") -> list:
    return _merge_evidence_list(existing, new_items, key_field=key_field)


def absorb_experiment_outcome(
    label: str,
    outcome: str,
    profile: dict,
    dimensions: dict | None = None,
) -> None:
    """Promuove o demote un esperimento nel rollup strategico persistente."""
    label = (label or "").strip()
    if not label:
        return
    memory = load_memory()
    rollup = memory.get("rollup") or _empty_rollup()
    vid = profile.get("video_id")
    score = profile.get("performance_score")
    payload = {
        "pattern": label,
        "value": label,
        "video_id": vid,
        "source": "controlled_experiment",
        "performance_tier": profile.get("performance_tier"),
        "score": round(float(score) * 100, 1) if score is not None else None,
    }
    if outcome == "win":
        rollup["winning_patterns"] = _merge_evidence_list(
            rollup.get("winning_patterns", []),
            [payload],
            key_field="pattern",
        )
        topic = (profile.get("topic") or "").strip()
        meta = profile.get("content_metadata") or {}
        category = (meta.get("topic_category") or meta.get("topic_angle") or "").strip()
        if not category and topic:
            try:
                from moduli.performance import infer_topic_themes
                themes = infer_topic_themes(profile.get("title") or "", topic)
                category = themes[0] if themes else ""
            except Exception:
                category = ""
        if category:
            rollup["successful_topics"] = _merge_simple_list(
                rollup.get("successful_topics", []),
                [{
                    "value": category,
                    "story_category": category,
                    "example_title": (profile.get("title") or "")[:60],
                    "video_id": vid,
                    "score": payload.get("score"),
                }],
                key_field="value",
            )
        fmt = (dimensions or {}).get("content_format") or ""
        if fmt:
            rollup["successful_formats"] = _merge_simple_list(
                rollup.get("successful_formats", []),
                [{"value": fmt, "video_id": vid}],
                key_field="value",
            )
        title_pat = (dimensions or {}).get("title_pattern") or ""
        if title_pat:
            rollup["successful_title_patterns"] = _merge_simple_list(
                rollup.get("successful_title_patterns", []),
                [{"value": title_pat, "video_id": vid}],
                key_field="value",
            )
    elif outcome == "loss":
        rollup["losing_patterns"] = _merge_evidence_list(
            rollup.get("losing_patterns", []),
            [payload],
            key_field="pattern",
        )
        topic = (profile.get("topic") or "").strip()
        meta = profile.get("content_metadata") or {}
        category = (meta.get("topic_category") or meta.get("topic_angle") or "").strip()
        if category:
            rollup["unsuccessful_topics"] = _merge_simple_list(
                rollup.get("unsuccessful_topics", []),
                [{
                    "value": category,
                    "story_category": category,
                    "example_title": (profile.get("title") or "")[:60],
                    "video_id": vid,
                }],
                key_field="value",
            )
        rollup["avoid_patterns"] = _merge_evidence_list(
            rollup.get("avoid_patterns", []),
            [{"pattern": label, "video_id": vid}],
            key_field="pattern",
        )

    memory["rollup"] = rollup
    memory["updated_at"] = _now_label()
    _save_json(MEMORY_FILE, memory)


def update_memory(cycle_entry: dict) -> dict:
    """Aggiorna strategy_memory.json con nuovo ciclo."""
    memory = load_memory()
    rollup = memory.get("rollup") or _empty_rollup()

    rollup["winning_patterns"] = _merge_evidence_list(
        rollup.get("winning_patterns", []),
        cycle_entry.get("winning_patterns") or [],
        key_field="pattern",
    )
    rollup["losing_patterns"] = _merge_evidence_list(
        rollup.get("losing_patterns", []),
        cycle_entry.get("losing_patterns") or [],
        key_field="pattern",
    )
    for field, key in (
        ("successful_topics", "value"),
        ("unsuccessful_topics", "value"),
        ("successful_title_patterns", "value"),
        ("unsuccessful_title_patterns", "value"),
        ("successful_thumbnail_patterns", "value"),
        ("unsuccessful_thumbnail_patterns", "value"),
        ("successful_formats", "value"),
        ("unsuccessful_formats", "value"),
    ):
        rollup[field] = _merge_simple_list(
            rollup.get(field, []),
            cycle_entry.get(field) or [],
            key_field=key,
        )

    # Recommended directions — keep latest high-confidence cycle + historical winners
    for direction_field in (
        "recommended_topic_directions",
        "recommended_title_directions",
        "recommended_hook_directions",
    ):
        new_vals = [v for v in (cycle_entry.get(direction_field) or []) if v]
        prev = [x.get("value") if isinstance(x, dict) else x for x in rollup.get(direction_field, [])]
        merged = list(dict.fromkeys(new_vals + prev))[:8]
        rollup[direction_field] = [
            {"value": v, "last_seen": _now_label(), "confidence_level": cycle_entry.get("confidence_level", 0.5)}
            for v in merged if v
        ]

    if cycle_entry.get("recommended_duration_minutes"):
        rollup["recommended_duration_minutes"] = cycle_entry["recommended_duration_minutes"]
    if cycle_entry.get("recommended_publish_hours_utc"):
        rollup["recommended_publish_hours_utc"] = cycle_entry["recommended_publish_hours_utc"]

    avoid_new = cycle_entry.get("avoid_patterns") or ""
    if avoid_new:
        avoid_list = rollup.get("avoid_patterns") or []
        for part in [a.strip() for a in str(avoid_new).split(";") if a.strip()]:
            avoid_list = _merge_evidence_list(avoid_list, [{"pattern": part}], key_field="pattern")
        rollup["avoid_patterns"] = avoid_list[:20]

    memory["rollup"] = rollup
    memory["updated_at"] = _now_label()
    memory["cycles"] = int(memory.get("cycles") or 0) + 1
    recent = memory.get("recent_cycles") or []
    recent.append(_compact_cycle(cycle_entry))
    memory["recent_cycles"] = recent[-10:]
    _save_json(MEMORY_FILE, memory)
    return memory


def _compact_cycle(entry: dict) -> dict:
    """Versione compatta per recent_cycles."""
    return {
        "date": entry.get("date"),
        "videos_analyzed": entry.get("videos_analyzed"),
        "confidence_level": entry.get("confidence_level"),
        "video_ids": entry.get("video_ids", [])[:10],
        "winning_patterns": [p.get("pattern") for p in (entry.get("winning_patterns") or [])[:5]],
        "losing_patterns": [p.get("pattern") for p in (entry.get("losing_patterns") or [])[:5]],
        "recommended_duration_minutes": entry.get("recommended_duration_minutes"),
        "avoid_patterns": entry.get("avoid_patterns", "")[:200],
    }


def record_strategy_cycle(
    profiles: list[dict],
    insights: dict,
    strategy: dict,
    top_performers: list[dict],
    underperformers: list[dict],
) -> dict:
    """Salva ciclo in strategia_storia.json + aggiorna strategy_memory.json."""
    entry = build_cycle_entry(profiles, insights, strategy, top_performers, underperformers)
    history = load_history()
    history.append(entry)
    save_history(history)
    memory = update_memory(entry)
    return {"entry": entry, "memory": memory}


def memory_for_llm(max_patterns: int = 8) -> dict:
    """Vista compatta per prompt LLM — successi e fallimenti storici."""
    memory = load_memory()
    rollup = memory.get("rollup") or _empty_rollup()

    def _top(items, n=max_patterns):
        return sorted(
            items or [],
            key=lambda x: float(x.get("confidence_level") or 0),
            reverse=True,
        )[:n]

    return {
        "cycles_recorded": memory.get("cycles", 0),
        "updated_at": memory.get("updated_at"),
        "historical_winning_patterns": _top(rollup.get("winning_patterns")),
        "historical_losing_patterns": _top(rollup.get("losing_patterns")),
        "successful_topics": _top(rollup.get("successful_topics")),
        "unsuccessful_topics": _top(rollup.get("unsuccessful_topics")),
        "successful_title_patterns": _top(rollup.get("successful_title_patterns")),
        "unsuccessful_title_patterns": _top(rollup.get("unsuccessful_title_patterns")),
        "successful_thumbnail_patterns": _top(rollup.get("successful_thumbnail_patterns")),
        "unsuccessful_thumbnail_patterns": _top(rollup.get("unsuccessful_thumbnail_patterns")),
        "successful_formats": _top(rollup.get("successful_formats")),
        "unsuccessful_formats": _top(rollup.get("unsuccessful_formats")),
        "recommended_topic_directions": rollup.get("recommended_topic_directions", [])[:5],
        "recommended_title_directions": rollup.get("recommended_title_directions", [])[:3],
        "recommended_hook_directions": rollup.get("recommended_hook_directions", [])[:3],
        "recommended_duration_minutes": rollup.get("recommended_duration_minutes"),
        "recommended_publish_hours_utc": rollup.get("recommended_publish_hours_utc", []),
        "avoid_patterns": _top(rollup.get("avoid_patterns")),
        "recent_cycles": memory.get("recent_cycles", [])[-5:],
    }


def memory_context_block() -> str:
    """Testo leggibile per prompt."""
    data = memory_for_llm()
    if not data.get("cycles_recorded"):
        return "(no strategy memory yet — first cycles will build historical learning)"
    lines = [
        f"Cycles recorded: {data['cycles_recorded']} (updated {data.get('updated_at', '?')})",
    ]
    for label, key in (
        ("Historical WINNING patterns", "historical_winning_patterns"),
        ("Historical LOSING patterns", "historical_losing_patterns"),
        ("Successful story categories (new subject required)", "successful_topics"),
        ("Unsuccessful story categories", "unsuccessful_topics"),
        ("Successful title patterns", "successful_title_patterns"),
        ("Unsuccessful title patterns", "unsuccessful_title_patterns"),
        ("Successful thumbnails", "successful_thumbnail_patterns"),
        ("Unsuccessful thumbnails", "unsuccessful_thumbnail_patterns"),
        ("Successful formats", "successful_formats"),
        ("Unsuccessful formats", "unsuccessful_formats"),
    ):
        items = data.get(key) or []
        if not items:
            continue
        lines.append(f"\n{label}:")
        for item in items[:6]:
            if isinstance(item, dict):
                name = item.get("pattern") or item.get("value") or item.get("topic") or "?"
                conf = item.get("confidence_level", "?")
                vids = item.get("evidence_video_ids") or []
                vid_hint = f" [evidence: {', '.join(vids[:3])}]" if vids else ""
                lines.append(f"  - {name} (confidence {conf}){vid_hint}")
            else:
                lines.append(f"  - {item}")
    if data.get("recommended_duration_minutes"):
        lines.append(f"\nRecommended duration: {data['recommended_duration_minutes']} min")
    if data.get("recommended_publish_hours_utc"):
        lines.append(f"Recommended publish hours UTC: {data['recommended_publish_hours_utc']}")
    avoid = data.get("avoid_patterns") or []
    if avoid:
        lines.append("\nAccumulated AVOID patterns:")
        for a in avoid[:6]:
            lines.append(f"  - {a.get('pattern') or a}")
    return "\n".join(lines)
