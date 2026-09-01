"""
Pattern da evitare — raccolta centralizzata, prompt e validazione programmatica.

Gli avoid_patterns della strategia devono essere rispettati in topic, titolo,
script, thumbnail — non solo menzionati nel prompt.
"""

from __future__ import annotations

import re

_AVOID_STOP = frozenset({
    "a", "an", "the", "of", "and", "in", "on", "for", "to", "with", "about",
    "is", "are", "was", "were", "be", "been", "being", "will", "would",
    "this", "that", "these", "those", "or", "vs", "versus", "its", "it",
})


class AvoidPatternError(ValueError):
    """Contenuto viola un pattern avoid della strategia."""

    def __init__(self, field: str, text: str, pattern: str):
        self.field = field
        self.text = text
        self.pattern = pattern
        super().__init__(
            f"{field} matches avoided pattern '{pattern}': {(text or '')[:80]}"
        )


def _parse_pattern_strings(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                val = (item.get("pattern") or item.get("value") or item.get("topic") or "").strip()
            else:
                val = str(item).strip()
            if val:
                out.append(val)
        return out
    text = str(raw).strip()
    if not text:
        return []
    parts = re.split(r"[;\n]+", text)
    return [p.strip().strip('"\'') for p in parts if p.strip()]


def collect_avoid_patterns(strategy: dict | None = None, pref: dict | None = None) -> list[str]:
    """Unisce tutte le fonti avoid in lista deduplicata."""
    strategy = strategy or {}
    pref = pref or {}
    seen: set[str] = set()
    patterns: list[str] = []

    def _add(raw) -> None:
        for p in _parse_pattern_strings(raw):
            key = p.lower()
            if key and key not in seen:
                seen.add(key)
                patterns.append(p)

    _add(strategy.get("avoid_patterns"))
    for lp in strategy.get("_losing_patterns") or []:
        if isinstance(lp, dict):
            _add(lp.get("pattern") or lp.get("value"))
        else:
            _add(lp)
    for title in strategy.get("_recent_underperformers") or []:
        if title:
            _add(f"title like: {title}")

    _add(pref.get("argomenti_evitare"))

    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        _add(mem.get("avoid_patterns"))
        for item in (mem.get("historical_losing_patterns") or [])[:8]:
            if isinstance(item, dict):
                _add(item.get("pattern") or item.get("value"))
            else:
                _add(item)
        for item in (mem.get("unsuccessful_topics") or [])[:6]:
            if isinstance(item, dict):
                _add(item.get("topic") or item.get("value"))
            else:
                _add(item)
        for item in (mem.get("unsuccessful_title_patterns") or [])[:6]:
            if isinstance(item, dict):
                _add(item.get("value") or item.get("pattern"))
            else:
                _add(item)
    except Exception:
        pass

    try:
        from moduli.experimentation import experiment_stats
        for item in (experiment_stats().get("losing_pool") or [])[:6]:
            _add(item.get("label"))
    except Exception:
        pass

    return patterns


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _tokens(text: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-z0-9']+", (text or "").lower())
        if w not in _AVOID_STOP and len(w) > 1
    ]


def _bigrams(text: str) -> set[tuple[str, str]]:
    words = _tokens(text)
    return {(words[i], words[i + 1]) for i in range(len(words) - 1)}


def find_avoid_match(text: str, patterns: list[str] | None = None) -> str | None:
    """Ritorna il primo pattern evitato che matcha il testo, o None."""
    if not text or not patterns:
        return None
    text_n = _normalize(text)
    text_words = set(_tokens(text))
    text_bigrams = _bigrams(text)
    for pattern in patterns:
        pat = (pattern or "").strip()
        if not pat:
            continue
        # "title like: Foo Bar" — confronta sul titolo estratto
        m = re.match(r"^title\s+like:\s*(.+)$", pat, re.I)
        if m:
            pat = m.group(1).strip()

        pat_n = _normalize(pat)
        if pat_n and pat_n in text_n:
            return pattern
        if text_n and text_n in pat_n and len(text_n.split()) >= 3:
            return pattern

        pat_words = _tokens(pat)
        if not pat_words:
            continue
        if _bigrams(pat) & text_bigrams:
            return pattern
        overlap = sum(1 for w in pat_words if w in text_words)
        if len(pat_words) == 1:
            if overlap == 1:
                return pattern
        elif len(pat_words) == 2:
            if overlap >= 2:
                return pattern
        elif overlap / len(pat_words) >= 0.5:
            return pattern
    return None


def assert_not_avoided(
    text: str,
    field: str,
    strategy: dict | None = None,
    pref: dict | None = None,
    *,
    patterns: list[str] | None = None,
) -> None:
    """Solleva AvoidPatternError se il testo viola un avoid pattern."""
    pats = patterns if patterns is not None else collect_avoid_patterns(strategy, pref)
    hit = find_avoid_match(text, pats)
    if hit:
        raise AvoidPatternError(field, text, hit)


def validate_content_fields(
    content: dict,
    strategy: dict | None = None,
    pref: dict | None = None,
) -> list[str]:
    """Ritorna lista errori per campi content che violano avoid patterns."""
    patterns = collect_avoid_patterns(strategy, pref)
    if not patterns:
        return []
    errors: list[str] = []
    checks = (
        ("title", content.get("title") or ""),
        ("thumbnail_phrase", content.get("thumbnail_phrase") or ""),
        ("thumbnail_description", content.get("thumbnail_description") or ""),
        ("description", content.get("description") or ""),
    )
    script = content.get("script") or ""
    if script:
        opening = " ".join(script.split()[:90])
        checks = checks + (("script opening", opening),)

    for field, text in checks:
        if not text:
            continue
        hit = find_avoid_match(text, patterns)
        if hit:
            errors.append(f"{field} matches avoided pattern '{hit}'")
    return errors


def avoid_prompt_section(
    strategy: dict | None = None,
    pref: dict | None = None,
    *,
    stage: str = "content",
) -> str:
    """
    Blocco prompt MANDATORY per topic/title/content/thumbnail.
    stage: topic | title | hook | content | thumbnail
    """
    patterns = collect_avoid_patterns(strategy, pref)
    if not patterns:
        return ""

    stage_rules = {
        "topic": "Do NOT propose topics, angles, or subjects matching any pattern below.",
        "title": "Do NOT use these title structures, phrases, or angles.",
        "hook": "Do NOT open the script with these angles, framings, or phrases.",
        "thumbnail": "Do NOT describe thumbnail visuals that evoke these patterns or clichés.",
        "content": "Do NOT use these patterns in title, hook, script, description, or thumbnail fields.",
    }
    rule = stage_rules.get(stage, stage_rules["content"])
    lines = [
        f"=== AVOID PATTERNS (MANDATORY — {stage.upper()}) ===",
        rule,
        "Violating any item below causes automatic rejection — choose a different angle.",
    ]
    for p in patterns[:12]:
        lines.append(f"- {p[:160]}")
    if len(patterns) > 12:
        lines.append(f"- ... and {len(patterns) - 12} more accumulated avoid patterns")
    return "\n".join(lines)


def avoid_block_for_content(strategy: dict | None = None, pref: dict | None = None) -> str:
    """Blocco compatto per CONTENT_PROMPT (include successi storici + avoid)."""
    parts: list[str] = []
    section = avoid_prompt_section(strategy, pref, stage="content")
    if section:
        parts.append(section)

    try:
        from moduli.strategy_memory import memory_for_llm
        mem = memory_for_llm()
        hist_wins = mem.get("historical_winning_patterns") or []
        if hist_wins:
            wins = "; ".join(
                (p.get("pattern") or p.get("value") or p.get("topic") or "")[:80]
                for p in hist_wins[:3]
                if isinstance(p, dict) and (p.get("pattern") or p.get("value") or p.get("topic"))
            )
            if wins:
                parts.append(f"HISTORICAL SUCCESSES (repeat these patterns): {wins}")
    except Exception:
        pass

    winning = (strategy or {}).get("_winning_patterns") or []
    if winning:
        wins = "; ".join(p.get("pattern", "") for p in winning[:3] if p.get("pattern"))
        if wins:
            parts.append(f"DOUBLE DOWN on these winning channel patterns: {wins}")

    if not parts:
        return ""
    return "\n".join(parts) + "\n"
