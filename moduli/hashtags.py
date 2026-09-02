"""Normalize hashtags for YouTube descriptions (fix spaced-character bugs)."""

from __future__ import annotations

import re

_SPACED_HASHTAG_RE = re.compile(r"#\s*(?:[A-Za-z0-9]\s+)+[A-Za-z0-9]")
_INLINE_HASHTAG_RE = re.compile(r"#[\w]+", re.UNICODE)


def fix_spaced_hashtags(text: str) -> str:
    """Fix '# S h o r t s' -> '#Shorts' inside free text."""
    if not text:
        return text

    def _collapse(match: re.Match[str]) -> str:
        return "#" + re.sub(r"\s+", "", match.group(0)[1:])

    text = _SPACED_HASHTAG_RE.sub(_collapse, text)
    text = re.sub(r"\s+#\s*$", "", text.strip())
    return text


def normalize_hashtag(tag: str) -> str:
    """Return a single clean hashtag like '#Shorts'."""
    tag = fix_spaced_hashtags((tag or "").strip())
    if not tag:
        return ""
    if tag.startswith("#"):
        body = re.sub(r"\s+", "", tag[1:])
        return f"#{body}" if body else ""
    body = re.sub(r"\s+", "", tag)
    return f"#{body}" if body else ""


def normalize_hashtags(
    value,
    *,
    default: list[str] | None = None,
    max_count: int = 5,
) -> list[str]:
    """
    Coerce LLM output into a list of hashtags.

    Handles common failure modes:
    - string '#Shorts' (must not be joined char-by-char)
    - string '#Shorts #AI'
    - list of single-character fragments ['#', 'S', 'h', ...]
    - spaced tags '# S h o r'
    """
    default = default or ["#Shorts"]
    if value is None or value == "":
        return list(default)[:max_count]

    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        tag = normalize_hashtag(raw)
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)

    if isinstance(value, str):
        fixed = fix_spaced_hashtags(value.strip())
        found = _INLINE_HASHTAG_RE.findall(fixed)
        if found:
            for token in found:
                _add(token)
        else:
            _add(fixed)
        return (out or list(default))[:max_count]

    if isinstance(value, (list, tuple)):
        items = [str(x) for x in value if x is not None and str(x).strip()]
        if not items:
            return list(default)[:max_count]
        if all(len(item.strip()) <= 2 for item in items):
            _add("".join(items))
            return (out or list(default))[:max_count]
        for item in items:
            _add(item)
        return (out or list(default))[:max_count]

    return list(default)[:max_count]


def format_hashtag_line(
    value,
    *,
    default: list[str] | None = None,
    max_count: int = 5,
) -> str:
    """Space-join normalized hashtags for a description footer."""
    return " ".join(normalize_hashtags(value, default=default, max_count=max_count))


def append_hashtags_to_description(
    description: str,
    hashtags,
    *,
    default: list[str] | None = None,
    max_count: int = 5,
    required: str | None = None,
) -> str:
    """Append hashtag line to description; skip if required tag already present."""
    desc = fix_spaced_hashtags((description or "").strip())
    tags = normalize_hashtags(hashtags, default=default, max_count=max_count)
    if required:
        required_norm = normalize_hashtag(required).lower()
        if required_norm and required_norm.lstrip("#") in desc.lower().replace(" ", ""):
            return desc
        if not any(t.lower() == required_norm for t in tags):
            tags = [normalize_hashtag(required)] + [t for t in tags if t.lower() != required_norm]
    tag_line = " ".join(tags)
    if not tag_line:
        return desc
    # Avoid duplicate footer if hashtags already in body
    desc_compact = re.sub(r"\s+", "", desc.lower())
    if all(re.sub(r"\s+", "", t.lower()) in desc_compact for t in tags):
        return desc
    return f"{desc}\n\n{tag_line}".strip() if desc else tag_line
