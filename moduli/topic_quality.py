"""
Validazione qualità topic — gate programmatico prima del dedup semantico.

Target: 3-12 parole, soggetto concreto, niente reasoning/markdown/JSON.
"""

from __future__ import annotations

import json
import os
import re

MIN_TOPIC_WORDS = int(os.environ.get("TOPIC_MIN_WORDS", "3"))
MAX_TOPIC_WORDS = int(os.environ.get("TOPIC_MAX_WORDS", "12"))


class TopicQualityError(ValueError):
    def __init__(self, candidate: str, reason: str):
        self.candidate = candidate
        self.reason = reason
        super().__init__(reason)


# Topic troppo vaghi — non descrivono un soggetto concreto
_GENERIC_PATTERNS = (
    r"^(the\s+)?(future\s+of\s+)?(ai|artificial intelligence)(\s+and\s+technology)?$",
    r"^ai\s+(news|updates?|trends?|technology|revolution|takeover|age|hype)$",
    r"^(latest|newest|new)\s+(ai|tech|technology)(\s+news|\s+updates?)?$",
    r"^technology\s+trends?$",
    r"^(everything|all)\s+about\s+(ai|tech|technology)$",
    r"^how\s+ai\s+(will|is)\s+(change|transform|replace)",
    r"^(the\s+)?(ai|tech)\s+revolution$",
    r"^artificial\s+intelligence(\s+explained)?$",
    r"^(ai|tech)\s+in\s+\d{4}$",
    r"^top\s+(ai|tech)\s+(tools|trends|news)",
    r"^what\s+is\s+(ai|artificial intelligence|machine learning)$",
)

# Output LLM non valido come topic
_REASONING_MARKERS = (
    r"here'?s\s+(a\s+|my\s+)?(thinking|thought)\s+process",
    r"\bthinking\s+process\b",
    r"^let\s+me\s+(think|explain|break|start)",
    r"^(sure|okay|ok)[,!.\s]",
    r"^(i\s+think|i'll|i\s+would|as\s+an\s+ai|as\s+a\s+language)",
    r"^(explanation|reasoning|analysis|note)\s*:",
    r"^step\s+\d",
    r"^\s*[\{\[]",  # JSON / array start
    r"^```",
    r"^\|",  # markdown table
    r"^#{1,6}\s",  # markdown heading
    r"\*\*[^*]+\*\*",  # bold markdown span
)

_GENERIC_VOCAB = frozenset({
    "a", "an", "the", "of", "and", "in", "on", "for", "to", "with", "about",
    "ai", "tech", "technology", "future", "new", "latest", "trends", "news",
    "how", "what", "why", "when", "where", "is", "are", "was", "will", "be",
    "its", "it", "this", "that", "these", "those", "or", "vs", "versus",
})


def _word_count(text: str) -> int:
    return len(re.findall(r"[a-z0-9']+", (text or "").lower()))


def _extract_topic_line(raw: str) -> str:
    """Estrae la prima riga plausibile se il modello ha aggiunto spiegazioni."""
    text = (raw or "").strip()
    if not text:
        return ""
    # JSON object con campo topic/title
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("topic", "title", "subject", "idea"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
        except json.JSONDecodeError:
            pass
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    # Preferisci riga dopo "Topic:" se presente
    for ln in lines:
        m = re.match(r"^(?:topic|subject|idea)\s*:\s*(.+)$", ln, re.I)
        if m:
            return m.group(1).strip().strip('"\'')
    first = lines[0]
    # Se prima riga è reasoning e la seconda è corta, usa la seconda
    if len(lines) > 1 and _looks_like_reasoning(first) and _word_count(lines[1]) <= MAX_TOPIC_WORDS:
        return lines[1].strip().strip('"\'')
    return first.strip().strip('"\'').strip("*_")


def _looks_like_reasoning(text: str) -> bool:
    from moduli.ai_validation import contains_banned_reasoning
    if contains_banned_reasoning(text):
        return True
    t = (text or "").strip()
    if not t:
        return True
    for pat in _REASONING_MARKERS:
        if re.search(pat, t, re.I | re.M):
            return True
    if len(t) > 120:
        return True
    if t.count(".") >= 2 and _word_count(t) > MAX_TOPIC_WORDS:
        return True
    return False


def _is_too_generic(topic: str) -> bool:
    t = (topic or "").strip().lower()
    if not t:
        return True
    for pat in _GENERIC_PATTERNS:
        if re.search(pat, t, re.I):
            return True
    words = re.findall(r"[a-z0-9']+", t)
    specific = [w for w in words if w not in _GENERIC_VOCAB and len(w) > 2]
    if len(specific) < 1:
        return True
    # Solo aggettivi generici + "AI"
    if len(words) <= 3 and all(w in _GENERIC_VOCAB or w == "ai" for w in words):
        return True
    return False


def validate_topic_quality(candidate: str) -> tuple[bool, str, str]:
    """
    Valida qualità topic.
    Ritorna (ok, cleaned_topic, reason).
    """
    from moduli.ai_validation import contains_markdown
    raw = (candidate or "").strip()
    if raw and contains_markdown(raw):
        return False, raw, "contains markdown"

    for ln in raw.splitlines():
        if re.match(r"^(analysis|reasoning|explanation)\s*:", ln.strip(), re.I):
            return False, raw, "contains reasoning or explanation"

    cleaned = _extract_topic_line(candidate)
    if not cleaned:
        return False, "", "empty topic"

    if _looks_like_reasoning(cleaned):
        return False, cleaned, "contains reasoning or explanation"

    if re.search(r"[\{\}\[\]]", cleaned) and _word_count(cleaned) > MAX_TOPIC_WORDS:
        return False, cleaned, "contains JSON or structured markup"

    if re.search(r"```|^\s*#+\s|\*\*.*\*\*", cleaned, re.M):
        return False, cleaned, "contains markdown"

    wc = _word_count(cleaned)
    if wc < MIN_TOPIC_WORDS:
        return False, cleaned, f"too short ({wc} words, min {MIN_TOPIC_WORDS})"
    if wc > MAX_TOPIC_WORDS:
        return False, cleaned, f"too long ({wc} words, max {MAX_TOPIC_WORDS})"

    if _is_too_generic(cleaned):
        return False, cleaned, "too generic — needs a concrete subject (company, product, event, or specific story)"

    return True, cleaned, ""


def assert_topic_quality(candidate: str) -> str:
    """Solleva TopicQualityError se non valido; altrimenti ritorna topic pulito."""
    ok, cleaned, reason = validate_topic_quality(candidate)
    if not ok:
        raise TopicQualityError(candidate or "", reason)
    return cleaned


def try_topic_quality(candidate: str) -> tuple[bool, str, str]:
    """API per Telegram/coda: (ok, cleaned_or_original, error_message)."""
    ok, cleaned, reason = validate_topic_quality(candidate)
    if ok:
        return True, cleaned, ""
    return False, candidate or "", reason
