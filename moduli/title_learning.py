"""
Analisi pattern titoli storici e guida sperimentale per generazione futura.

Correla pattern (Why X Failed, curiosity, numbered, ecc.) con CTR,
retention e views velocity — senza forzare un solo formato vincente.
"""

from __future__ import annotations

import json
import os
import random
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone

TITLE_STATS_FILE = "title_learning.json"
DEFAULT_EXPLOIT_RATIO = 0.75

# (pattern_id, regex, human label)
TITLE_PATTERN_RULES: tuple[tuple[str, str, str], ...] = (
    ("why_x_failed", r"\bwhy\b.{0,60}\b(fail(?:ed|ure)?|collapsed?|lost|died|bankrupt|flop(?:ped)?|shutdown)\b",
     "Why X Failed"),
    ("truth_about", r"\b(the truth about|truth behind|real (story|reason)|what really happened)\b",
     "The Truth About X"),
    ("how_x_changed", r"\bhow\b.{0,50}\b(changed|transformed|revolutionized|reshaped|killed|replaced|ended)\b",
     "How X Changed..."),
    ("hidden_reason", r"\b(hidden reason|real reason|nobody talks about|they don't want you to know)\b",
     "hidden reason"),
    ("curiosity", r"\b(secret|hidden|nobody (talks|knows)|don't know|you didn't know|they don't want)\b",
     "curiosity title"),
    ("unexpected", r"\b(shocking|unexpected|nobody expected|plot twist|blew up|insane)\b",
     "unexpected outcome"),
    ("numbered", r"\b\d+\s+(ways|reasons|things|mistakes|lessons|secrets|facts|signs)\b",
     "numbered title"),
    ("controversy", r"\b(controversy|scandal|exposed|debunked|backlash|outrage|lie)\b",
     "controversy"),
    ("vs_comparison", r"\bvs\.?\b|\bversus\b",
     "versus comparison"),
    ("question", r"\?\s*$",
     "question title"),
    ("colon_hook", r":",
     "colon hook"),
    ("how_why_what", r"^(how|why|what|when|where)\b",
     "How/Why/What opener"),
)

from moduli.channel_confidence import channel_confidence, confidence_prompt_block

PATTERN_LABELS = {pid: label for pid, _, label in TITLE_PATTERN_RULES}

# Pattern da provare quando si esplora (anche senza dati)
_EXPLORE_PATTERNS = (
    "truth_about", "unexpected", "numbered", "controversy", "vs_comparison",
    "curiosity", "hidden_reason", "how_x_changed",
)


def classify_title_pattern(title: str) -> str:
    """Classifica il pattern strutturale di un titolo."""
    t = (title or "").strip()
    if not t:
        return "unknown"
    for pid, pattern, _label in TITLE_PATTERN_RULES:
        if re.search(pattern, t, re.I):
            return pid
    return "statement"


def pattern_label(pattern_id: str) -> str:
    return PATTERN_LABELS.get(pattern_id, pattern_id.replace("_", " "))


def exploit_ratio() -> float:
    raw = os.environ.get("TITLE_EXPLOIT_RATIO") or os.environ.get("TOPIC_EXPLOIT_RATIO", "0.75")
    try:
        return max(0.5, min(0.95, float(raw)))
    except ValueError:
        return DEFAULT_EXPLOIT_RATIO


def _load_stats() -> dict:
    if not os.path.exists(TITLE_STATS_FILE):
        return {"exploit": 0, "explore": 0, "recent": []}
    try:
        with open(TITLE_STATS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("exploit", 0)
            data.setdefault("explore", 0)
            data.setdefault("recent", [])
            return data
    except Exception:
        pass
    return {"exploit": 0, "explore": 0, "recent": []}


def _save_stats(stats: dict) -> None:
    stats["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(TITLE_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


def record_title_mode(mode: str, pattern_id: str, title: str = "") -> None:
    if mode not in ("exploit", "explore"):
        return
    stats = _load_stats()
    stats[mode] = int(stats.get(mode, 0)) + 1
    recent = stats.get("recent") or []
    recent.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode,
        "pattern_id": pattern_id,
        "title": (title or "")[:100],
    })
    stats["recent"] = recent[-40:]
    _save_stats(stats)


def _views_per_day(profile: dict) -> float:
    from moduli.performance import compute_score_breakdown
    breakdown = compute_score_breakdown(profile)
    return float(breakdown.get("views_per_day") or 0)


def _retention(profile: dict) -> float:
    m = profile.get("metrics") or {}
    ret = float(m.get("retention_percent") or 0)
    if ret:
        return ret
    dur = max(float(m.get("duration_seconds") or 1), 1.0)
    return float(m.get("avg_view_duration_seconds") or 0) / dur * 100


def _profile_score(profile: dict) -> float:
    if profile.get("performance_score") is not None:
        return float(profile["performance_score"])
    from moduli.performance import compute_score_breakdown
    return float(compute_score_breakdown(profile).get("performance_score") or 0)


def analyze_title_patterns(profiles: list[dict]) -> dict:
    """
    Analizza correlazioni pattern titolo ↔ CTR / retention / velocity / score.
    """
    empty = {
        "has_data": False,
        "video_count": 0,
        "patterns": [],
        "winning_title_patterns": [],
        "losing_title_patterns": [],
        "channel_baseline": {},
    }
    usable = [p for p in profiles if (p.get("title") or "").strip()]
    if not usable:
        return empty

    ctrs, retentions, velocities, scores = [], [], [], []
    buckets: dict[str, list[dict]] = defaultdict(list)

    for p in usable:
        title = (p.get("title") or "").strip()
        pid = classify_title_pattern(title)
        m = p.get("metrics") or {}
        ctr = float(m.get("ctr_percent") or 0)
        ret = _retention(p)
        vel = _views_per_day(p)
        score = _profile_score(p)
        ctrs.append(ctr)
        retentions.append(ret)
        velocities.append(vel)
        scores.append(score)
        buckets[pid].append({
            "video_id": p.get("video_id"),
            "title": title[:80],
            "ctr": ctr,
            "retention": ret,
            "velocity": vel,
            "score": score,
        })

    base_ctr = statistics.mean(ctrs) if ctrs else 0.0
    base_ret = statistics.mean(retentions) if retentions else 0.0
    base_vel = statistics.mean(velocities) if velocities else 0.0
    base_score = statistics.mean(scores) if scores else 0.0

    min_samples = 1 if len(usable) <= 4 else 2
    pattern_rows: list[dict] = []

    for pid, items in buckets.items():
        if not items:
            continue
        avg_ctr = statistics.mean(i["ctr"] for i in items)
        avg_ret = statistics.mean(i["retention"] for i in items)
        avg_vel = statistics.mean(i["velocity"] for i in items)
        avg_score = statistics.mean(i["score"] for i in items)
        pattern_rows.append({
            "pattern_id": pid,
            "pattern_label": pattern_label(pid),
            "sample_size": len(items),
            "avg_ctr": round(avg_ctr, 2),
            "ctr_vs_channel": round(avg_ctr - base_ctr, 2),
            "avg_retention": round(avg_ret, 1),
            "retention_vs_channel": round(avg_ret - base_ret, 1),
            "avg_velocity": round(avg_vel, 1),
            "velocity_vs_channel": round(avg_vel - base_vel, 1),
            "avg_score": round(avg_score * 100, 1),
            "score_vs_channel": round((avg_score - base_score) * 100, 1),
            "example_titles": [i["title"] for i in items[:2]],
        })

    pattern_rows.sort(key=lambda x: x["score_vs_channel"], reverse=True)

    winning: list[dict] = []
    losing: list[dict] = []
    for row in pattern_rows:
        if row["sample_size"] < min_samples:
            continue
        if row["score_vs_channel"] >= 5 or (
            row["ctr_vs_channel"] >= 0.8 and row["retention_vs_channel"] >= 0
        ):
            winning.append(row)
        elif row["score_vs_channel"] <= -5 or (
            row["ctr_vs_channel"] <= -0.8 and row["retention_vs_channel"] <= 0
        ):
            losing.append(row)

    return {
        "has_data": True,
        "video_count": len(usable),
        "patterns": pattern_rows,
        "winning_title_patterns": winning[:6],
        "losing_title_patterns": losing[:6],
        "clickbait_traps": _detect_clickbait_traps(pattern_rows, base_ctr, base_ret),
        "channel_baseline": {
            "avg_ctr": round(base_ctr, 2),
            "avg_retention": round(base_ret, 1),
            "avg_velocity": round(base_vel, 1),
            "avg_score": round(base_score * 100, 1),
        },
    }


def _detect_clickbait_traps(
    pattern_rows: list[dict],
    base_ctr: float,
    base_ret: float,
) -> list[dict]:
    """High CTR + poor retention = misleading packaging."""
    traps = []
    for row in pattern_rows:
        if row["sample_size"] < 2:
            continue
        if row["ctr_vs_channel"] >= 1.0 and row["retention_vs_channel"] <= -5:
            traps.append({
                "pattern_id": row["pattern_id"],
                "pattern_label": row["pattern_label"],
                "ctr_vs_channel": row["ctr_vs_channel"],
                "retention_vs_channel": row["retention_vs_channel"],
                "reason": "high CTR but weak retention — likely misleading packaging",
            })
    return traps


_CLICKBAIT_TRAP_IDS: set[str] = set()


def refresh_clickbait_traps(profiles: list[dict]) -> list[str]:
    """Update in-memory trap set from latest analysis; return pattern ids."""
    global _CLICKBAIT_TRAP_IDS
    analysis = analyze_title_patterns(profiles)
    traps = analysis.get("clickbait_traps") or []
    _CLICKBAIT_TRAP_IDS = {t["pattern_id"] for t in traps}
    return list(_CLICKBAIT_TRAP_IDS)


def is_clickbait_trap_pattern(pattern_id: str) -> bool:
    return (pattern_id or "") in _CLICKBAIT_TRAP_IDS


def _decide_title_mode() -> str:
    stats = _load_stats()
    total = int(stats.get("exploit", 0)) + int(stats.get("explore", 0))
    target = exploit_ratio()
    if total == 0:
        return "exploit"
    if stats.get("exploit", 0) / total < target:
        return "exploit"
    return "explore"


def pick_title_experiment(analysis: dict | None = None) -> dict:
    """
    Sceglie pattern titolo da sfruttare o sperimentare.
    Non forza un solo winner — bilancia exploit/explore.
    """
    analysis = analysis or {}
    mode = _decide_title_mode()
    winners = analysis.get("winning_title_patterns") or []
    losers = {r["pattern_id"] for r in (analysis.get("losing_title_patterns") or [])}
    all_patterns = analysis.get("patterns") or []
    tested_ids = {r["pattern_id"] for r in all_patterns}

    if mode == "exploit" and winners and channel_confidence(
        analysis.get("video_count", 0)
    ).apply_learning:
        pool = [w for w in winners if w["pattern_id"] not in losers] or winners
        ranked = sorted(pool, key=lambda x: x.get("score_vs_channel", 0), reverse=True)
        top = ranked[:3]
        # Evita di ripetere gli ultimi pattern usati — sperimentazione anche in exploit
        recent_ids = {
            r.get("pattern_id")
            for r in (_load_stats().get("recent") or [])[-4:]
            if r.get("pattern_id")
        }
        candidates = [w for w in top if w["pattern_id"] not in recent_ids] or top
        weights = [max(1.0, w.get("score_vs_channel", 1) + 5) for w in candidates]
        pick = random.choices(candidates, weights=weights, k=1)[0]
        return {
            "mode": "exploit",
            "pattern_id": pick["pattern_id"],
            "pattern_label": pick["pattern_label"],
            "rationale": (
                f"CTR {pick.get('avg_ctr', 0)}% ({pick.get('ctr_vs_channel', 0):+.1f} vs channel), "
                f"retention {pick.get('avg_retention', 0)}%, "
                f"velocity {pick.get('avg_velocity', 0)}/day"
            ),
        }

    # Explore: pattern poco testati o non perdenti
    explore_pool = [
        pid for pid in _EXPLORE_PATTERNS
        if pid not in losers and (pid not in tested_ids or len(all_patterns) < 3)
    ]
    if not explore_pool:
        explore_pool = [pid for pid, _, _ in TITLE_PATTERN_RULES if pid not in losers]
    if not explore_pool:
        explore_pool = ["how_why_what"]
    pid = random.choice(explore_pool[:6])
    return {
        "mode": "explore",
        "pattern_id": pid,
        "pattern_label": pattern_label(pid),
        "rationale": "experimental title structure — gather data, do not copy a single past winner blindly",
    }


def title_guidance_block(strategy: dict | None = None) -> str:
    """Blocco prompt per generazione titolo con learning + sperimentazione."""
    if strategy is None:
        strategy = {}
    try:
        from moduli.performance import carica_profili
        profiles = carica_profili()
    except Exception:
        profiles = []

    analysis = analyze_title_patterns(profiles)
    experiment = pick_title_experiment(analysis if analysis.get("has_data") else {})
    mode = experiment["mode"]
    pct = int(exploit_ratio() * 100)

    lines = [
        confidence_prompt_block(profiles=profiles),
        f"TITLE LEARNING — mode: {mode.upper()} (~{pct}% exploit winning patterns on this channel)",
        f"Suggested structure for THIS video: {experiment['pattern_label']} ({experiment['pattern_id']})",
        f"Rationale: {experiment['rationale']}",
        "Apply the structure to THIS topic — do not reuse past video titles or entities.",
        "Experiment: vary phrasing and hooks; never clone one winning title forever.",
    ]

    if analysis.get("has_data"):
        base = analysis.get("channel_baseline") or {}
        lines.append(
            f"Channel baseline: CTR {base.get('avg_ctr', 0)}%, "
            f"retention {base.get('avg_retention', 0)}%, "
            f"velocity {base.get('avg_velocity', 0)} views/day"
        )
        winners = analysis.get("winning_title_patterns") or []
        if winners:
            lines.append("Patterns correlated with stronger performance:")
            for w in winners[:4]:
                lines.append(
                    f"- {w['pattern_label']}: CTR {w['avg_ctr']}% ({w['ctr_vs_channel']:+.1f}), "
                    f"retention {w['avg_retention']}% ({w['retention_vs_channel']:+.1f}), "
                    f"velocity {w['avg_velocity']}/day ({w['velocity_vs_channel']:+.1f}), "
                    f"n={w['sample_size']}"
                )
        losers = analysis.get("losing_title_patterns") or []
        if losers:
            lines.append("Patterns to avoid or use sparingly:")
            for lp in losers[:3]:
                lines.append(f"- {lp['pattern_label']} (underperformed channel median)")

    # Strategy memory supplement
    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        for item in (mem.get("successful_title_patterns") or [])[:2]:
            val = item.get("value") if isinstance(item, dict) else str(item)
            if val:
                lines.append(f"- Historical success: {val}")
        for item in (mem.get("unsuccessful_title_patterns") or [])[:2]:
            val = item.get("value") if isinstance(item, dict) else str(item)
            if val:
                lines.append(f"- Historical failure: {val}")
    except Exception:
        pass

    style = (strategy.get("title_style") or "").strip()
    if style:
        lines.append(f"Strategy title_style: {style[:200]}")

    try:
        from moduli.avoid_patterns import avoid_prompt_section
        avoid = avoid_prompt_section(strategy, stage="title")
        if avoid:
            lines.append(avoid)
    except Exception:
        pass

    # Stash for metadata recording after generation
    strategy["_title_experiment"] = experiment
    return "\n".join(lines)


def record_generated_title(title: str, strategy: dict | None = None) -> None:
    """Registra pattern usato dopo generazione titolo."""
    if strategy is None:
        strategy = {}
    exp = strategy.get("_title_experiment") or {}
    mode = exp.get("mode", "exploit")
    pid = classify_title_pattern(title)
    record_title_mode(mode, pid, title)
