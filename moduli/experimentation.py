"""
Sistema di sperimentazione controllata a livello video.

Ogni video riceve una classificazione:
  - exploitation — formula / pattern già provati
  - experiment   — test di angolo, tema o struttura nuova

Al maturare delle metriche, gli esperimenti vengono valutati e promossi
nel pool vincente o registrati come pattern perdenti.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from moduli.channel_confidence import channel_confidence, should_claim_pattern

EXPERIMENTS_FILE = "experiments.json"
_WINNER_TIERS = frozenset({"breakout", "strong"})
_LOSER_TIERS = frozenset({"weak", "poor"})
_MIN_VIEWS_TO_EVALUATE = 20


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load() -> dict:
    if not os.path.exists(EXPERIMENTS_FILE):
        return _empty()
    try:
        with open(EXPERIMENTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("video_counter", 0)
            data.setdefault("records", [])
            data.setdefault("winning_pool", [])
            data.setdefault("losing_pool", [])
            return data
    except Exception:
        pass
    return _empty()


def _empty() -> dict:
    return {
        "video_counter": 0,
        "records": [],
        "winning_pool": [],
        "losing_pool": [],
        "updated_at": None,
    }


def _save(data: dict) -> None:
    data["updated_at"] = _now()
    with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def infer_topic_themes(title: str, topic: str) -> list[str]:
    from moduli.performance import infer_topic_themes as _infer
    return _infer(title, topic)


def _decide_mode(strategy: dict) -> str:
    """exploitation | experiment — topic explore domina."""
    topic_mode = (strategy.get("_topic_diversity_mode") or "exploit").lower()
    title_mode = (strategy.get("_title_experiment") or {}).get("mode", "exploit")
    hook_mode = (strategy.get("_hook_experiment") or {}).get("mode", "exploit")
    if topic_mode == "explore":
        return "experiment"
    explore_count = sum(1 for m in (title_mode, hook_mode) if m == "explore")
    if explore_count >= 2:
        return "experiment"
    return "exploitation"


def _proven_label(topic: str, title: str, strategy: dict) -> str:
    for wp in (strategy.get("_winning_patterns") or [])[:4]:
        pat = (wp.get("pattern") or wp.get("value") or "").strip()
        if pat:
            clean = pat.replace("topic theme:", "").replace("title structure:", "").strip()
            if clean:
                return f"proven {clean.lower()}"
    themes = infer_topic_themes(title, topic)
    if themes:
        return f"proven {themes[0].lower()}"
    title_exp = strategy.get("_title_experiment") or {}
    if title_exp.get("pattern_label"):
        return f"proven {title_exp['pattern_label'].lower()} structure"
    angle = (strategy.get("preferred_angle") or "").lower()
    if "failure" in angle or "failure" in topic.lower():
        return "proven technology failure story"
    fmt = (strategy.get("content_format") or "").strip()
    if fmt:
        return f"proven {fmt.lower()}"
    focus = (strategy.get("topic_focus") or topic or "channel formula").strip()
    return f"proven {focus[:72].lower()}"


def _experiment_label(topic: str, title: str, strategy: dict) -> str:
    sub = (strategy.get("_explore_subtheme") or "").strip()
    if sub:
        return sub[:80]
    themes = infer_topic_themes(title, topic)
    title_exp = strategy.get("_title_experiment") or {}
    hook_exp = strategy.get("_hook_experiment") or {}
    if title_exp.get("mode") == "explore" and title_exp.get("pattern_label"):
        return f"{title_exp['pattern_label']} title structure"
    if hook_exp.get("mode") == "explore" and hook_exp.get("hook_label"):
        return f"{hook_exp['hook_label']} opening hook"
    fmt = (strategy.get("content_format") or "").strip()
    if fmt:
        return f"{fmt} on {topic[:50]}".strip()
    return (topic or "new angle test")[:80]


def _collect_dimensions(strategy: dict, content: dict) -> dict:
    meta = content.get("_strategy_meta") or {}
    title_exp = strategy.get("_title_experiment") or {}
    hook_exp = strategy.get("_hook_experiment") or {}
    return {
        "topic_diversity_mode": strategy.get("_topic_diversity_mode"),
        "topic_focus": (strategy.get("topic_focus") or "")[:120],
        "preferred_angle": (strategy.get("preferred_angle") or "")[:120],
        "content_format": (strategy.get("content_format") or "")[:80],
        "title_pattern": meta.get("title_pattern") or title_exp.get("pattern_id"),
        "title_experiment_mode": title_exp.get("mode"),
        "hook_type": meta.get("hook_type") or hook_exp.get("hook_id"),
        "hook_experiment_mode": hook_exp.get("mode"),
        "topic_themes": infer_topic_themes(content.get("title") or "", content.get("topic") or ""),
    }


def classify_video_strategy(
    topic: str,
    strategy: dict | None,
    content: dict,
) -> dict:
    """
    Classificazione strategica del video corrente.
    Da chiamare dopo genera_contenuto.
    """
    strategy = strategy or {}
    title = (content.get("title") or "").strip()
    mode = _decide_mode(strategy)
    label = _experiment_label(topic, title, strategy) if mode == "experiment" else _proven_label(
        topic, title, strategy
    )
    return {
        "mode": mode,
        "label": label,
        "dimensions": _collect_dimensions(strategy, {**content, "topic": topic}),
        "classified_at": _now(),
    }


def format_classification(record: dict) -> str:
    n = record.get("video_number", "?")
    mode = str(record.get("mode", "")).upper()
    label = record.get("label", "")
    return f"Video {n}: {mode} — {label}"


def record_video_classification(
    video_id: str,
    topic: str,
    title: str,
    classification: dict,
) -> dict:
    """Registra classificazione al momento della pubblicazione."""
    data = _load()
    existing = next((r for r in data["records"] if r.get("video_id") == video_id), None)
    if existing:
        existing.update({
            "topic": topic,
            "title": title,
            **{k: v for k, v in classification.items() if v is not None},
            "status": existing.get("status") or "pending",
        })
        _save(data)
        return existing

    data["video_counter"] = int(data.get("video_counter") or 0) + 1
    record = {
        "video_id": video_id,
        "video_number": data["video_counter"],
        "topic": topic,
        "title": title,
        "mode": classification.get("mode", "exploitation"),
        "label": classification.get("label", ""),
        "dimensions": classification.get("dimensions") or {},
        "classified_at": classification.get("classified_at") or _now(),
        "recorded_at": _now(),
        "status": "pending",
        "outcome": None,
        "performance_tier": None,
        "performance_score": None,
        "evaluated_at": None,
    }
    data["records"].append(record)
    data["records"] = data["records"][-80:]
    _save(data)
    return record


def _pool_entry(record: dict, profile: dict, outcome: str) -> dict:
    m = profile.get("metrics") or {}
    score = profile.get("performance_score")
    return {
        "label": record.get("label"),
        "mode": record.get("mode"),
        "outcome": outcome,
        "video_id": record.get("video_id"),
        "video_number": record.get("video_number"),
        "topic": record.get("topic"),
        "title": (record.get("title") or "")[:60],
        "performance_tier": profile.get("performance_tier"),
        "performance_score": round(float(score) * 100, 1) if score is not None else None,
        "views": m.get("views"),
        "ctr_percent": m.get("ctr_percent"),
        "dimensions": record.get("dimensions") or {},
        "promoted_at": _now(),
    }


def _upsert_pool(pool: list, entry: dict, key_field: str = "label") -> list:
    key = str(entry.get(key_field) or "").strip().lower()
    if not key:
        return pool
    out = [p for p in pool if str(p.get(key_field) or "").strip().lower() != key]
    out.insert(0, entry)
    return out[:30]


def evaluate_pending_experiments(profiles: list[dict] | None = None) -> list[dict]:
    """
    Valuta esperimenti con metriche sufficienti.
    Promuove vincenti / registra perdenti nel pool strategico.
    """
    from moduli.performance import carica_profili

    if profiles is None:
        profiles = carica_profili()
    by_id = {p.get("video_id"): p for p in profiles if p.get("video_id")}
    data = _load()
    evaluated: list[dict] = []
    channel_n = len(profiles)
    changed = False

    for record in data.get("records") or []:
        if record.get("status") not in (None, "pending"):
            continue
        if record.get("mode") != "experiment":
            record["status"] = "tracked"
            changed = True
            continue

        vid = record.get("video_id")
        profile = by_id.get(vid)
        if not profile:
            continue

        m = profile.get("metrics") or {}
        views = int(m.get("views") or 0)
        tier = profile.get("performance_tier")
        score = profile.get("performance_score")
        if views < _MIN_VIEWS_TO_EVALUATE or not tier or score is None:
            continue

        record["performance_tier"] = tier
        record["performance_score"] = round(float(score) * 100, 1)
        record["evaluated_at"] = _now()

        if tier in _WINNER_TIERS:
            record["outcome"] = "win"
            record["status"] = "promoted" if should_claim_pattern(1, channel_n) else "win_provisional"
            entry = _pool_entry(record, profile, "win")
            data["winning_pool"] = _upsert_pool(data.get("winning_pool") or [], entry)
            try:
                from moduli.strategy_memory import absorb_experiment_outcome
                absorb_experiment_outcome(record["label"], "win", profile, record.get("dimensions") or {})
            except Exception:
                pass
        elif tier in _LOSER_TIERS:
            record["outcome"] = "loss"
            record["status"] = "demoted" if should_claim_pattern(1, channel_n) else "loss_provisional"
            entry = _pool_entry(record, profile, "loss")
            data["losing_pool"] = _upsert_pool(data.get("losing_pool") or [], entry)
            try:
                from moduli.strategy_memory import absorb_experiment_outcome
                absorb_experiment_outcome(record["label"], "loss", profile, record.get("dimensions") or {})
            except Exception:
                pass
        else:
            record["outcome"] = "neutral"
            record["status"] = "evaluated"

        changed = True
        evaluated.append(dict(record))

    if changed:
        _save(data)
    return evaluated


def experiment_stats() -> dict:
    data = _load()
    records = data.get("records") or []
    pending = sum(1 for r in records if r.get("status") == "pending" and r.get("mode") == "experiment")
    promoted = sum(1 for r in records if r.get("status") in ("promoted", "win_provisional"))
    demoted = sum(1 for r in records if r.get("status") in ("demoted", "loss_provisional"))
    return {
        "video_counter": data.get("video_counter", 0),
        "total_records": len(records),
        "pending_experiments": pending,
        "promoted_experiments": promoted,
        "demoted_experiments": demoted,
        "winning_pool": data.get("winning_pool") or [],
        "losing_pool": data.get("losing_pool") or [],
        "recent": records[-6:],
        "updated_at": data.get("updated_at"),
    }


def recent_classifications(n: int = 5) -> list[str]:
    return [format_classification(r) for r in (experiment_stats().get("recent") or [])[-n:]]


def experimentation_guidance_text() -> str:
    stats = experiment_stats()
    conf = channel_confidence(stats.get("video_counter", 0))
    lines = [
        f"Controlled experimentation (confidence {conf.level}, n={stats.get('video_counter', 0)}):",
        f"Pending experiments: {stats.get('pending_experiments', 0)} · "
        f"Promoted: {stats.get('promoted_experiments', 0)} · "
        f"Demoted: {stats.get('demoted_experiments', 0)}",
    ]
    for rec in (stats.get("recent") or [])[-4:]:
        lines.append(f"- {format_classification(rec)} [{rec.get('status', 'pending')}]")
    for wp in (stats.get("winning_pool") or [])[:3]:
        lines.append(
            f"WINNING POOL — {wp.get('label')} "
            f"(tier {wp.get('performance_tier')}, score {wp.get('performance_score')})"
        )
    for lp in (stats.get("losing_pool") or [])[:2]:
        lines.append(
            f"LOSING POOL — {lp.get('label')} "
            f"(tier {lp.get('performance_tier')}, score {lp.get('performance_score')})"
        )
    if not conf.apply_learning:
        lines.append("Channel too small — experiments tracked but not reshaping strategy yet.")
    return "\n".join(lines)


def winning_strategy_labels() -> list[str]:
    """Etichette dal pool vincente (esperimenti promossi + memoria)."""
    labels: list[str] = []
    for item in experiment_stats().get("winning_pool") or []:
        lab = (item.get("label") or "").strip()
        if lab:
            labels.append(lab)
    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        for key in ("historical_winning_patterns", "successful_topics", "successful_formats"):
            for item in mem.get(key) or []:
                if isinstance(item, dict):
                    val = item.get("pattern") or item.get("value") or item.get("topic") or ""
                else:
                    val = str(item)
                if val:
                    labels.append(val)
    except Exception:
        pass
    return list(dict.fromkeys(labels))[:20]
