"""
Pre-script research and trend signals for topic/content generation.

Combines web search, channel performance memory, and heuristic scoring.
Does NOT invent facts — separates verified snippets from interpretation.
"""

from __future__ import annotations

import re
from datetime import datetime

from moduli.web_search import cerca_notizie


def _year() -> str:
    return str(datetime.now().year)


def fetch_trending_block(strategy: dict | None = None, subtheme: str = "") -> str:
    """Timely news/trends for topic generation — strategy-aware query."""
    strategy = strategy or {}
    focus = (strategy.get("topic_focus") or "").strip()
    niche = subtheme or focus or "technology business documentary"
    query = f"{niche} news breakthrough {_year()}"
    try:
        results = cerca_notizie(query, max_results=6)
        if results:
            return (
                "CURRENT TRENDS (inspiration only — find a unique educational angle, "
                "do not copy headlines verbatim):\n"
                f"{results}\n"
            )
    except Exception:
        pass
    return ""


def build_research_brief(topic: str, *, max_snippets: int = 8) -> dict:
    """
    Gather web snippets before script writing.
    Returns structured brief — facts are unverified until script cites carefully.
    """
    topic = (topic or "").strip()
    if not topic:
        return {"topic": "", "snippets": [], "prompt_block": ""}

    queries = [
        topic,
        f"{topic} history facts timeline",
        f"{topic} why happened consequences",
    ]
    snippets: list[dict] = []
    seen: set[str] = set()
    for q in queries[:2]:
        text = cerca_notizie(q, max_results=max_snippets // 2 + 1)
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            snippets.append({"source": "web_search", "text": line[:400]})
            if len(snippets) >= max_snippets:
                break
        if len(snippets) >= max_snippets:
            break

    lines = [
        "RESEARCH BRIEF (use for accuracy — do NOT invent statistics, quotes, or dates):",
        "- Label claims: verified fact | reasonable interpretation | speculation",
        "- Prefer explaining WHY and consequences, not headline repetition",
        "- If a fact is uncertain, say so in the narration",
    ]
    for i, s in enumerate(snippets[:max_snippets], 1):
        lines.append(f"{i}. {s['text']}")
    if not snippets:
        lines.append("- No live research snippets — rely on well-known public facts only; avoid inventing details.")

    return {
        "topic": topic,
        "snippets": snippets,
        "prompt_block": "\n".join(lines),
    }


def infer_topic_source(
    strategy: dict,
    *,
    diversity_mode: str = "",
    from_trending: bool = False,
    from_queue: bool = False,
) -> str:
    """Tag how the topic was chosen — for later learning."""
    if from_queue:
        return "manual"
    if from_trending:
        return "trending"
    if diversity_mode == "explore":
        return "experiment"
    if strategy.get("_winning_patterns") or strategy.get("topic_focus"):
        return "analytics"
    return "evergreen"


def score_topic_candidate(
    topic: str,
    strategy: dict,
    *,
    source: str = "evergreen",
    trending_relevance: float = 0.5,
) -> float:
    """
    Heuristic 0-1 score for internal candidate ranking.
    Higher = better fit for channel strategy right now.
    """
    t = (topic or "").strip().lower()
    if not t or len(t.split()) < 3:
        return 0.0
    score = 0.45
    # Concrete entity bonus
    if re.search(r"\b(inc|corp|ltd|apple|google|microsoft|nokia|kodak|ibm|tesla)\b", t):
        score += 0.08
    if re.search(r"\b(how|why|what)\b", t):
        score += 0.05
    # Penalize generic AI slop
    if re.search(r"\b(future of ai|ai revolution|everything about|ultimate guide)\b", t):
        score -= 0.25
    focus = (strategy.get("topic_focus") or "").lower()
    if focus and any(w in t for w in focus.split()[:6] if len(w) > 4):
        score += 0.1
    if source == "analytics":
        score += 0.12
    elif source == "trending":
        score += 0.08 * min(1.0, trending_relevance)
    elif source == "experiment":
        score += 0.05
    return max(0.0, min(1.0, score))
