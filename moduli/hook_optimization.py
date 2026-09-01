"""
Analisi hook di apertura e correlazione con retention (focus primi 30 secondi).

Classifica come i video aprono lo script, misura retention associata,
e guida la generazione futura con sperimentazione exploit/explore.
"""

from __future__ import annotations

import json
import os
import random
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone

HOOK_STATS_FILE = "hook_learning.json"
OPENING_WORDS = 80  # ~30s parlato ≈ 70-90 parole
DEFAULT_EXPLOIT_RATIO = 0.75

# (hook_id, regex, label, script_instruction)
HOOK_TYPE_RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "surprising_fact",
        r"\b(did you know|shocking|nobody expected|\d+[%+]|\d+\s*(million|billion)|almost no one)\b",
        "surprising fact opener",
        "Open with a specific, verifiable surprising fact or statistic in the first 2 sentences.",
    ),
    (
        "question",
        r"^(what if|why (do|did|does|would)|how (do|did|does|can|could)|is it true|have you ever|could .{3,40}\?)",
        "question opener",
        "Open with a sharp, specific question that creates curiosity — answer it later.",
    ),
    (
        "outcome_first",
        r"\b(by the end|this (company|product|decision).{0,50}(failed|collapsed|died|lost|bankrupt)|"
        r"here's what happened|the ending was|spoiler)\b",
        "outcome-first opener",
        "Reveal the outcome or stakes in the first 15 seconds, then rewind to explain how.",
    ),
    (
        "immediate_stakes",
        r"\b(you need to|you have to|could (cost|change|destroy|kill)|at stake|before it's too late|"
        r"right now|this matters because|if you)\b",
        "immediate stakes opener",
        "Create personal stakes for the viewer within the first 15 seconds — why they should care NOW.",
    ),
    (
        "story_opening",
        r"\b(in \d{4}|it was (a |the )?(cold|quiet|ordinary)|one (morning|day|afternoon)|"
        r"when (he|she|they|the company)|years ago)\b",
        "story opener",
        "Drop the viewer into a concrete scene or moment — character, place, tension.",
    ),
    (
        "delayed_context",
        r"\b(before we (begin|start|dive)|let me (first )?explain|in this video (we'll|i'll)|"
        r"today (we're|i'm) going to (talk|discuss|explore)|welcome back|hey everyone)\b",
        "delayed context opener",
        "AVOID slow intros — do NOT open with 'in this video we will...' or channel greetings.",
    ),
)

HOOK_LABELS = {hid: label for hid, _, label, _ in HOOK_TYPE_RULES}
HOOK_INSTRUCTIONS = {hid: instr for hid, _, _, instr in HOOK_TYPE_RULES}

_EXPLORE_HOOKS = (
    "outcome_first", "immediate_stakes", "surprising_fact", "question", "story_opening",
)

# Raccomandazioni derivate dai pattern vincenti
_STRATEGY_TEMPLATES = {
    "immediate_stakes": "Top-performing videos create stakes within the first 15 seconds.",
    "outcome_first": "Winners often reveal the outcome first, then explain how it happened.",
    "surprising_fact": "Strong openers lead with a specific surprising fact — not vague hype.",
    "question": "High-retention videos open with a question the viewer needs answered.",
    "story_opening": "Narrative scene-setting in the opening 30 seconds holds attention.",
    "direct_statement": "Bold declarative claims in sentence one outperform slow warm-ups.",
}


def classify_hook_type(script_excerpt: str) -> str:
    """Classifica il tipo di hook dai primi ~30 secondi di script."""
    text = (script_excerpt or "").strip()
    if not text:
        return "unknown"
    opening = " ".join(text.split()[:OPENING_WORDS]).lower()
    for hid, pattern, _label, _instr in HOOK_TYPE_RULES:
        if re.search(pattern, opening, re.I):
            return hid
    if opening.strip().endswith("?"):
        return "question"
    return "direct_statement"


def hook_label(hook_id: str) -> str:
    return HOOK_LABELS.get(hook_id, hook_id.replace("_", " "))


def hook_instruction(hook_id: str) -> str:
    return HOOK_INSTRUCTIONS.get(
        hook_id,
        "Open strong: no greetings, no 'in this video' — hook in the first 15 seconds.",
    )


def opening_excerpt(script: str, max_words: int = OPENING_WORDS) -> str:
    words = (script or "").split()
    return " ".join(words[:max_words]).strip()


def exploit_ratio() -> float:
    raw = os.environ.get("HOOK_EXPLOIT_RATIO") or os.environ.get("TOPIC_EXPLOIT_RATIO", "0.75")
    try:
        return max(0.5, min(0.95, float(raw)))
    except ValueError:
        return DEFAULT_EXPLOIT_RATIO


def _load_stats() -> dict:
    if not os.path.exists(HOOK_STATS_FILE):
        return {"exploit": 0, "explore": 0, "recent": []}
    try:
        with open(HOOK_STATS_FILE, encoding="utf-8") as f:
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
    with open(HOOK_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


def record_hook_mode(mode: str, hook_id: str, excerpt: str = "") -> None:
    if mode not in ("exploit", "explore"):
        return
    stats = _load_stats()
    stats[mode] = int(stats.get(mode, 0)) + 1
    recent = stats.get("recent") or []
    recent.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode,
        "hook_id": hook_id,
        "excerpt": (excerpt or "")[:120],
    })
    stats["recent"] = recent[-40:]
    _save_stats(stats)


def _profile_hook_id(profile: dict) -> str:
    meta = profile.get("content_metadata") or {}
    hid = (meta.get("hook_type") or "").strip()
    if hid:
        return hid
    excerpt = meta.get("script_hook_excerpt") or ""
    if not excerpt and profile.get("topic"):
        excerpt = str(profile.get("topic"))
    return classify_hook_type(excerpt)


def _retention(profile: dict) -> float:
    m = profile.get("metrics") or {}
    ret = float(m.get("retention_percent") or 0)
    if ret:
        return ret
    dur = max(float(m.get("duration_seconds") or 1), 1.0)
    return float(m.get("avg_view_duration_seconds") or 0) / dur * 100


def _retention_30s(profile: dict) -> float | None:
    m = profile.get("metrics") or {}
    val = m.get("retention_at_30s_percent")
    if val is not None:
        return float(val)
    return None


def _profile_score(profile: dict) -> float:
    if profile.get("performance_score") is not None:
        return float(profile["performance_score"])
    from moduli.performance import compute_score_breakdown
    return float(compute_score_breakdown(profile).get("performance_score") or 0)


def analyze_hook_patterns(profiles: list[dict]) -> dict:
    """Correla tipi di hook con retention (overall + primi 30s se disponibile)."""
    empty = {
        "has_data": False,
        "video_count": 0,
        "patterns": [],
        "winning_hook_patterns": [],
        "losing_hook_patterns": [],
        "strategy_recommendations": [],
        "channel_baseline": {},
    }
    usable = [p for p in profiles if _profile_hook_id(p) != "unknown"]
    if not usable:
        return empty

    retentions, retentions_30s, scores = [], [], []
    buckets: dict[str, list[dict]] = defaultdict(list)

    for p in usable:
        hid = _profile_hook_id(p)
        ret = _retention(p)
        ret30 = _retention_30s(p)
        score = _profile_score(p)
        retentions.append(ret)
        if ret30 is not None:
            retentions_30s.append(ret30)
        scores.append(score)
        meta = p.get("content_metadata") or {}
        buckets[hid].append({
            "video_id": p.get("video_id"),
            "title": (p.get("title") or "")[:60],
            "retention": ret,
            "retention_30s": ret30,
            "score": score,
            "excerpt": (meta.get("script_hook_excerpt") or "")[:100],
        })

    base_ret = statistics.mean(retentions) if retentions else 0.0
    base_ret30 = statistics.mean(retentions_30s) if retentions_30s else None
    base_score = statistics.mean(scores) if scores else 0.0
    min_samples = 1 if len(usable) <= 4 else 2

    pattern_rows: list[dict] = []
    for hid, items in buckets.items():
        if hid == "delayed_context" and len(items) == 1:
            pass  # include for losing detection
        avg_ret = statistics.mean(i["retention"] for i in items)
        ret30_vals = [i["retention_30s"] for i in items if i["retention_30s"] is not None]
        avg_ret30 = statistics.mean(ret30_vals) if ret30_vals else None
        avg_score = statistics.mean(i["score"] for i in items)
        row = {
            "hook_id": hid,
            "hook_label": hook_label(hid),
            "sample_size": len(items),
            "avg_retention": round(avg_ret, 1),
            "retention_vs_channel": round(avg_ret - base_ret, 1),
            "avg_score": round(avg_score * 100, 1),
            "score_vs_channel": round((avg_score - base_score) * 100, 1),
            "example_excerpts": [i["excerpt"] for i in items[:2] if i["excerpt"]],
        }
        if avg_ret30 is not None and base_ret30 is not None:
            row["avg_retention_30s"] = round(avg_ret30, 1)
            row["retention_30s_vs_channel"] = round(avg_ret30 - base_ret30, 1)
        pattern_rows.append(row)

    pattern_rows.sort(
        key=lambda x: x.get("retention_30s_vs_channel", x.get("retention_vs_channel", 0)),
        reverse=True,
    )

    winning, losing = [], []
    for row in pattern_rows:
        if row["sample_size"] < min_samples:
            continue
        ret_delta = row.get("retention_30s_vs_channel", row.get("retention_vs_channel", 0))
        if row["hook_id"] == "delayed_context":
            losing.append(row)
            continue
        if ret_delta >= 3 or row["score_vs_channel"] >= 5:
            winning.append(row)
        elif ret_delta <= -3 or row["score_vs_channel"] <= -5:
            losing.append(row)

    recommendations: list[str] = []
    for w in winning[:3]:
        tpl = _STRATEGY_TEMPLATES.get(w["hook_id"])
        if tpl:
            recommendations.append(tpl)
        elif w.get("retention_30s_vs_channel", 0) >= 3:
            recommendations.append(
                f"Videos opening with {w['hook_label']} retain "
                f"+{w['retention_30s_vs_channel']:.0f}% more viewers at 30 seconds."
            )
        else:
            recommendations.append(
                f"Strong retention with {w['hook_label']} "
                f"(+{w['retention_vs_channel']:.0f}% vs channel)."
            )
    if not recommendations:
        recommendations.append(
            "Hook hard in the first 15 seconds — no greetings, no 'in this video we will'."
        )

    return {
        "has_data": True,
        "video_count": len(usable),
        "has_30s_data": base_ret30 is not None,
        "patterns": pattern_rows,
        "winning_hook_patterns": winning[:6],
        "losing_hook_patterns": losing[:6],
        "strategy_recommendations": recommendations,
        "channel_baseline": {
            "avg_retention": round(base_ret, 1),
            "avg_retention_30s": round(base_ret30, 1) if base_ret30 is not None else None,
            "avg_score": round(base_score * 100, 1),
        },
    }


def _decide_hook_mode() -> str:
    stats = _load_stats()
    total = int(stats.get("exploit", 0)) + int(stats.get("explore", 0))
    target = exploit_ratio()
    if total == 0:
        return "exploit"
    if stats.get("exploit", 0) / total < target:
        return "exploit"
    return "explore"


def pick_hook_experiment(analysis: dict | None = None) -> dict:
    analysis = analysis or {}
    mode = _decide_hook_mode()
    winners = analysis.get("winning_hook_patterns") or []
    losers = {r["hook_id"] for r in (analysis.get("losing_hook_patterns") or [])}
    losers.add("delayed_context")

    if mode == "exploit" and winners:
        pool = [w for w in winners if w["hook_id"] not in losers] or winners
        ranked = sorted(
            pool,
            key=lambda x: x.get("retention_30s_vs_channel", x.get("retention_vs_channel", 0)),
            reverse=True,
        )
        top = ranked[:3]
        recent_ids = {
            r.get("hook_id") for r in (_load_stats().get("recent") or [])[-4:] if r.get("hook_id")
        }
        candidates = [w for w in top if w["hook_id"] not in recent_ids] or top
        weights = [
            max(1.0, w.get("retention_30s_vs_channel", w.get("retention_vs_channel", 1)) + 5)
            for w in candidates
        ]
        pick = random.choices(candidates, weights=weights, k=1)[0]
        hid = pick["hook_id"]
        return {
            "mode": "exploit",
            "hook_id": hid,
            "hook_label": pick["hook_label"],
            "instruction": hook_instruction(hid),
            "rationale": _STRATEGY_TEMPLATES.get(hid, pick["hook_label"]),
        }

    explore_pool = [h for h in _EXPLORE_HOOKS if h not in losers]
    if not explore_pool:
        explore_pool = [h for h, _, _, _ in HOOK_TYPE_RULES if h != "delayed_context"]
    hid = random.choice(explore_pool)
    return {
        "mode": "explore",
        "hook_id": hid,
        "hook_label": hook_label(hid),
        "instruction": hook_instruction(hid),
        "rationale": "experimental hook style — test what works for this channel",
    }


def hook_guidance_block(strategy: dict | None = None) -> str:
    """Blocco prompt per ottimizzazione hook nei primi 30 secondi."""
    if strategy is None:
        strategy = {}
    try:
        from moduli.performance import carica_profili
        profiles = carica_profili()
    except Exception:
        profiles = []

    from moduli.channel_confidence import confidence_prompt_block

    analysis = analyze_hook_patterns(profiles)
    experiment = pick_hook_experiment(analysis if analysis.get("has_data") else {})
    mode = experiment["mode"]
    pct = int(exploit_ratio() * 100)

    lines = [
        confidence_prompt_block(profiles=profiles),
        "HOOK OPTIMIZATION — opening 30 seconds (spoken ~70-90 words):",
        f"Mode: {mode.upper()} (~{pct}% exploit proven hook patterns)",
        f"Use THIS hook style: {experiment['hook_label']} ({experiment['hook_id']})",
        f"Instruction: {experiment['instruction']}",
        f"Strategy: {experiment['rationale']}",
        "CRITICAL: First 2 sentences = hook. No channel greeting. No 'in this video we will'.",
    ]

    for rec in (analysis.get("strategy_recommendations") or [])[:3]:
        lines.append(f"- Channel learning: {rec}")

    if analysis.get("has_data"):
        base = analysis.get("channel_baseline") or {}
        ret_line = f"Channel avg retention: {base.get('avg_retention', 0)}%"
        if base.get("avg_retention_30s") is not None:
            ret_line += f" | at 30s: {base['avg_retention_30s']}%"
        lines.append(ret_line)

        for w in (analysis.get("winning_hook_patterns") or [])[:3]:
            detail = f"+{w['retention_vs_channel']:.0f}% retention"
            if w.get("retention_30s_vs_channel") is not None:
                detail = (
                    f"+{w['retention_30s_vs_channel']:.0f}% at 30s, "
                    f"+{w['retention_vs_channel']:.0f}% overall"
                )
            lines.append(f"- Winner: {w['hook_label']} ({detail}, n={w['sample_size']})")

        for lp in (analysis.get("losing_hook_patterns") or [])[:2]:
            lines.append(f"- Avoid: {lp['hook_label']} (underperforms channel)")

    try:
        from moduli.avoid_patterns import avoid_prompt_section
        avoid = avoid_prompt_section(strategy, stage="hook")
        if avoid:
            lines.append(avoid)
    except Exception:
        pass

    strategy["_hook_experiment"] = experiment
    return "\n".join(lines)


def record_generated_hook(script: str, strategy: dict | None = None) -> None:
    if strategy is None:
        strategy = {}
    exp = strategy.get("_hook_experiment") or {}
    mode = exp.get("mode", "exploit")
    excerpt = opening_excerpt(script)
    hid = classify_hook_type(excerpt)
    record_hook_mode(mode, hid, excerpt)
