"""
Bilanciamento topic exploit vs explore.

- EXPLOIT (~75% default): nuovi topic dentro categorie/pattern vincenti
- EXPLORE (~25%): esperimenti in categorie nuove

Mai riusare lo stesso topic sottostante — topic_history resta il gate hard.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone

DIVERSITY_STATS_FILE = "topic_diversity.json"
DEFAULT_EXPLOIT_RATIO = 0.75


def exploit_ratio() -> float:
    """Frazione target di generazioni in modalità exploit (default 0.75)."""
    raw = os.environ.get("TOPIC_EXPLOIT_RATIO", str(DEFAULT_EXPLOIT_RATIO))
    try:
        return max(0.5, min(0.95, float(raw)))
    except ValueError:
        return DEFAULT_EXPLOIT_RATIO


def explore_ratio() -> float:
    """Frazione target explore — derivata da exploit salvo TOPIC_EXPLORE_RATIO esplicito."""
    raw = os.environ.get("TOPIC_EXPLORE_RATIO", "").strip()
    if raw:
        try:
            return max(0.05, min(0.5, float(raw)))
        except ValueError:
            pass
    return round(1.0 - exploit_ratio(), 4)


def _load_stats() -> dict:
    if not os.path.exists(DIVERSITY_STATS_FILE):
        return {"exploit": 0, "explore": 0, "recent": []}
    try:
        with open(DIVERSITY_STATS_FILE, encoding="utf-8") as f:
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
    with open(DIVERSITY_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


def diversity_stats() -> dict:
    stats = _load_stats()
    total = stats.get("exploit", 0) + stats.get("explore", 0)
    return {
        **stats,
        "total": total,
        "exploit_ratio_target": exploit_ratio(),
        "explore_ratio_target": explore_ratio(),
        "exploit_ratio_actual": round(stats.get("exploit", 0) / total, 3) if total else None,
        "explore_ratio_actual": round(stats.get("explore", 0) / total, 3) if total else None,
    }


def has_winning_signals(strategy: dict | None) -> bool:
    """True se abbiamo pattern vincenti da sfruttare."""
    strategy = strategy or {}
    if strategy.get("_winning_patterns"):
        return True
    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        return bool(
            mem.get("historical_winning_patterns")
            or mem.get("successful_formats")
            or mem.get("successful_topics")
        )
    except Exception:
        return False


def decide_mode(strategy: dict | None = None) -> str:
    """
    Sceglie exploit o explore per bilanciare verso il target configurato.
    Cold start senza winner → explore per raccogliere dati.
    """
    if not has_winning_signals(strategy):
        return "explore"

    stats = _load_stats()
    exploit_n = int(stats.get("exploit", 0))
    explore_n = int(stats.get("explore", 0))
    total = exploit_n + explore_n
    target_exploit = exploit_ratio()

    if total == 0:
        return "exploit"

    current_exploit = exploit_n / total
    if current_exploit < target_exploit:
        return "exploit"
    return "explore"


def record_mode(mode: str, topic: str) -> None:
    if mode not in ("exploit", "explore"):
        return
    stats = _load_stats()
    stats[mode] = int(stats.get(mode, 0)) + 1
    recent = stats.get("recent") or []
    recent.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode,
        "topic": (topic or "")[:120],
    })
    stats["recent"] = recent[-40:]
    _save_stats(stats)


def _winning_lines(strategy: dict) -> str:
    lines: list[str] = []
    for p in (strategy.get("_winning_patterns") or [])[:5]:
        pat = p.get("pattern") or p.get("value") or ""
        if pat:
            lines.append(f"- {pat}")
    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        for key, label in (
            ("historical_winning_patterns", "Winning pattern"),
            ("successful_formats", "Successful format"),
            ("successful_topics", "Successful story category"),
            ("recommended_topic_directions", "Recommended direction"),
        ):
            for item in (mem.get(key) or [])[:3]:
                if isinstance(item, dict):
                    val = (
                        item.get("story_category")
                        or item.get("pattern")
                        or item.get("value")
                        or ""
                    ).strip()
                    example = (item.get("example_title") or "").strip()
                    if val and example:
                        val = f"{val} (e.g. «{example[:50]}» — pick NEW subject)"
                else:
                    val = str(item)
                if val:
                    lines.append(f"- {label}: {val}")
    except Exception:
        pass
    if strategy.get("topic_focus"):
        lines.append(f"- Strategy focus: {strategy['topic_focus'][:120]}")
    if strategy.get("preferred_angle"):
        lines.append(f"- Winning angle: {strategy['preferred_angle'][:120]}")
    if strategy.get("content_format"):
        lines.append(f"- Winning format: {strategy['content_format'][:80]}")
    return "\n".join(dict.fromkeys(lines)) or "- Use strategy topic_focus and proven CTR/retention patterns"


def diversity_prompt_block(mode: str, strategy: dict, subtheme: str) -> str:
    pct_exploit = int(exploit_ratio() * 100)
    pct_explore = int(explore_ratio() * 100)
    if mode == "exploit":
        return (
            f"TOPIC DIVERSITY — EXPLOITATION MODE (~{pct_exploit}% of channel videos)\n"
            "Create a NEW video topic that fits PROVEN winning categories/patterns below.\n"
            "Same winning CATEGORY and FORMAT — but a DIFFERENT company, entity, event, and story.\n"
            "NEVER reuse any banned topic or semantically similar story.\n"
            "Example GOOD: Nokia failure story → then BlackBerry failure → then Kodak failure.\n"
            "Example BAD: three different Nokia smartphone failure angles — FORBIDDEN.\n"
            f"{_winning_lines(strategy or {})}\n"
        )
    return (
        f"TOPIC DIVERSITY — EXPLORATION MODE (~{pct_explore}% of channel videos)\n"
        "Experiment with a genuinely NEW category, niche, or angle for this channel.\n"
        f"Lean into this sub-theme: {subtheme}\n"
        "Do NOT default to generic AI news or repeat dominant channel patterns.\n"
        "Still pick a specific, concrete topic — not vague or broad.\n"
    )


def map_winning_pattern_to_levers(strategy: dict, angles: list[str], formats: list[str]) -> tuple[str, str, str]:
    """Sceglie angolo/formato/focus da pattern vincenti + strategia."""
    angle = (strategy.get("preferred_angle") or "").strip()
    fmt = (strategy.get("content_format") or "").strip()
    focus = (strategy.get("topic_focus") or "").strip()

    failure_angle = "a story of a spectacular failure and its lesson"
    for p in strategy.get("_winning_patterns") or []:
        pat = (p.get("pattern") or "").lower()
        dim = (p.get("dimension") or "").lower()
        val = (p.get("value") or "").strip()
        if "failure" in pat or "why" in pat:
            angle = angle or failure_angle
            fmt = fmt or "case study"
        if dim == "content_format" and val:
            fmt = val
        if dim == "topic_angle" and val:
            angle = val
        if dim == "topic_theme" and val:
            focus = focus or val

    if not angle:
        angle = random.choice(angles)
    if not fmt:
        fmt = random.choice(formats)
    subtheme = focus[:120] if focus and len(focus) > 10 else ""
    return angle, fmt, subtheme
