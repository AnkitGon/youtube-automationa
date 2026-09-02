"""
Validazione risposte AI — reasoning, markdown, JSON malformato.

Usato da cervello (topic/contenuto), strategia e topic_history.
"""

from __future__ import annotations

import json
import re
from typing import Callable

# Sottostringhe vietate (case-insensitive) in risposte testo / wrapper JSON
_BANNED_SUBSTRINGS = (
    "here's a thinking process",
    "here is a thinking process",
    "my thinking process",
    "let me think",
    "let me explain",
)

# Pattern reasoning / meta-commento
_REASONING_PATTERNS = (
    r"here'?s\s+(a\s+|my\s+)?(thinking|thought)\s+process",
    r"\bthinking\s+process\b",
    r"^(analysis|reasoning|explanation)\s*:",
    r"^let\s+me\s+(think|explain|break|start)",
    r"^step\s+\d",
    r"^(sure|okay|ok)[,!.\s]",
    r"^(i\s+think|i'll|as\s+an\s+ai)",
)

_MARKDOWN_PATTERNS = (
    r"```",
    r"^\s*#{1,6}\s",
    r"\*\*[^*]+\*\*",
    r"^\|",
)


class AIResponseError(ValueError):
    """Risposta modello non accettabile."""

    def __init__(self, reason: str, raw: str = ""):
        self.reason = reason
        self.raw = (raw or "")[:500]
        super().__init__(reason)


def contains_banned_reasoning(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    for phrase in _BANNED_SUBSTRINGS:
        if phrase in low:
            return True
    for pat in _REASONING_PATTERNS:
        if re.search(pat, t, re.I | re.M):
            return True
    return False


def contains_markdown(text: str) -> bool:
    t = text or ""
    for pat in _MARKDOWN_PATTERNS:
        if re.search(pat, t, re.M):
            return True
    return False


def strip_markdown_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, count=1)
        t = re.sub(r"\s*```\s*$", "", t, count=1)
    return t.strip()


def strip_wrapping_quotes(text: str) -> str:
    t = (text or "").strip()
    for _ in range(2):
        if len(t) >= 2 and t[0] == t[-1] and t[0] in '"\'“”‘’':
            t = t[1:-1].strip()
    return t.strip('"\'''""')


def _json_prefix_invalid(text: str, json_start: int) -> str | None:
    """Rifiuta testo non-JSON prima dell'oggetto."""
    prefix = strip_markdown_fences(text[:json_start]).strip()
    if not prefix:
        return None
    if contains_banned_reasoning(prefix):
        return "reasoning before JSON"
    if len(prefix) > 30:
        return "non-JSON text before object"
    return None


def extract_json_text(text: str) -> tuple[str, int]:
    """Trova l'inizio del primo oggetto JSON `{`."""
    raw = (text or "").strip()
    if not raw:
        raise AIResponseError("empty response")
    if contains_banned_reasoning(raw) and "{" not in raw:
        raise AIResponseError("contains reasoning or explanation")
    start = raw.find("{")
    if start < 0:
        raise AIResponseError("no JSON object in response")
    invalid = _json_prefix_invalid(raw, start)
    if invalid:
        raise AIResponseError(invalid)
    return raw, start


def parse_json_object(
    text: str,
    required_fields: set[str] | None = None,
) -> dict:
    """
    Estrae, parsa e valida un oggetto JSON dalla risposta modello.
    Rifiuta wrapper con reasoning o markdown fence non pulito.
    """
    raw, start = extract_json_text(text)
    body = strip_markdown_fences(raw)
    if body != raw:
        start = body.find("{")
        if start < 0:
            raise AIResponseError("no JSON object after stripping fences")
        invalid = _json_prefix_invalid(body, start)
        if invalid:
            raise AIResponseError(invalid)

    decoder = json.JSONDecoder()
    try:
        data, end = decoder.raw_decode(body[start:])
    except json.JSONDecodeError as e:
        snippet = body[:500].replace("\n", "\\n")
        raise AIResponseError(f"invalid JSON: {e}; starts with: {snippet}") from e

    if not isinstance(data, dict):
        raise AIResponseError("JSON root is not an object")

    # trailing non-JSON prose
    suffix = body[start + end :].strip()
    suffix = re.sub(r"\s*```\s*$", "", suffix).strip()
    if suffix and contains_banned_reasoning(suffix):
        raise AIResponseError("reasoning after JSON")
    if suffix and len(suffix) > 40:
        raise AIResponseError("non-JSON text after object")

    if required_fields:
        missing = required_fields - set(data)
        if missing:
            raise AIResponseError(
                f"missing required fields: {', '.join(sorted(missing))}"
            )

    return data


def clean_topic_response(raw: str) -> str:
    """
    Pulisce risposta topic plain-text.
    Rifiuta reasoning, markdown, JSON wrapper non-topic.
    """
    text = (raw or "").strip()
    if not text:
        raise AIResponseError("empty topic response")

    if contains_banned_reasoning(text):
        raise AIResponseError("contains reasoning or explanation")

    if contains_markdown(text):
        raise AIResponseError("contains markdown")

    text = strip_markdown_fences(text)
    if contains_markdown(text):
        raise AIResponseError("contains markdown")

    # JSON con campo topic — estrai prima di altri controlli
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("topic", "title", "subject", "idea"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        text = val.strip()
                        break
                else:
                    raise AIResponseError("JSON object without topic field")
        except json.JSONDecodeError:
            raise AIResponseError("invalid JSON in topic response")

    # Prima riga plausibile se multilinea
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        for ln in lines:
            m = re.match(r"^(?:topic|subject|idea)\s*:\s*(.+)$", ln, re.I)
            if m:
                text = m.group(1).strip()
                break
        else:
            if len(lines) > 1 and contains_banned_reasoning(lines[0]):
                text = lines[1]
            else:
                text = lines[0]

    text = strip_wrapping_quotes(text)
    text = text.strip().strip("*_")

    if contains_banned_reasoning(text):
        raise AIResponseError("contains reasoning or explanation")
    if contains_markdown(text):
        raise AIResponseError("contains markdown")
    if re.search(r"[\{\}\[\]]", text):
        raise AIResponseError("contains JSON or structured markup")

    return text


CONTENT_REQUIRED_FIELDS = frozenset({
    "title", "description", "tags", "script", "video_keywords",
})

STRATEGY_REQUIRED_FIELDS = frozenset({
    "topic_focus",
})

DEDUP_JUDGE_REQUIRED_FIELDS = frozenset({
    "duplicate",
})


def fill_missing_content_fields(data: dict, *, topic: str = "") -> dict:
    """Infer missing pipeline fields from other LLM JSON keys."""
    out = dict(data)
    kws: list[str] = []
    existing = out.get("video_keywords")
    if isinstance(existing, list):
        kws = [str(x).strip() for x in existing if str(x).strip()]
    elif isinstance(existing, str) and existing.strip():
        kws = [existing.strip()]

    if not kws:
        for seg in out.get("visual_segments") or []:
            if not isinstance(seg, dict):
                continue
            kw = seg.get("keyword") or seg.get("keywords")
            if isinstance(kw, str) and kw.strip():
                kws.append(kw.strip())
            elif isinstance(kw, list):
                kws.extend(str(x).strip() for x in kw if str(x).strip())

    if not kws:
        tags = out.get("tags") or []
        if isinstance(tags, list):
            kws = [str(t).strip() for t in tags if str(t).strip()]

    if not kws and topic:
        kws = [topic.strip()[:80]]
    if not kws:
        title = (out.get("title") or "").strip()
        if title:
            kws = [title[:80]]

    if kws:
        out["video_keywords"] = list(dict.fromkeys(kws))[:20]
    return out


def parse_content_json(text: str, *, topic: str = "") -> dict:
    data = parse_json_object(text, CONTENT_REQUIRED_FIELDS - {"video_keywords"})
    data = fill_missing_content_fields(data, topic=topic)
    missing = CONTENT_REQUIRED_FIELDS - set(data)
    if missing:
        raise AIResponseError(
            f"missing required fields: {', '.join(sorted(missing))}"
        )
    if not data.get("video_keywords"):
        raise AIResponseError("missing required fields: video_keywords")
    return data


def fetch_json_with_retries(
    fetch: Callable[[], str],
    *,
    required_fields: set[str] | None = None,
    max_attempts: int = 3,
    log_prefix: str = "[ai_validation]",
) -> dict:
    """Chiama il modello, valida JSON, ritenta se invalido."""
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = fetch()
            return parse_json_object(raw, required_fields)
        except (AIResponseError, ValueError, json.JSONDecodeError) as e:
            last_err = e
            print(
                f"{log_prefix} JSON invalid (attempt {attempt}/{max_attempts}): {e}",
                flush=True,
            )
    raise AIResponseError(str(last_err or "JSON validation failed"))
