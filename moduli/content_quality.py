"""
Content quality gates: viewer value, AI filler, title/thumbnail promise alignment.

Used during script generation retries and pre-publish validation.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns that signal generic AI narration
AI_FILLER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("rapidly_evolving", r"\bin today'?s rapidly evolving\b"),
    ("in_conclusion", r"\bin conclusion\b|\bto sum up\b|\bin summary\b"),
    ("imagine", r"\b(imagine (?:this|a world|if))\b"),
    ("but_heres", r"\bbut here'?s the (?:thing|kicker|catch)\b"),
    ("you_wont_believe", r"\byou won'?t believe\b"),
    ("subscribe_hook", r"\bsmash that (?:like|subscribe)\b"),
    ("generic_future", r"\bthe future is (?:here|now)\b"),
    ("obvious_setup", r"\blet'?s dive in\b|\bbuckle up\b"),
    ("rhetorical_spam", r"(\?\s*){3,}"),
    ("filler_transition", r"\bwithout further ado\b|\bneedless to say\b"),
)

# Minimum insight markers per ~500 words
INSIGHT_MARKERS = re.compile(
    r"\b(because|therefore|which meant|as a result|consequently|"
    r"the lesson|what this shows|in practice|specifically|for example|"
    r"by contrast|the reason|led to|caused|triggered)\b",
    re.I,
)


def detect_ai_filler(script: str) -> list[str]:
    """Return human-readable issues for AI-sounding filler."""
    text = (script or "").strip()
    if not text:
        return ["empty script"]
    issues = []
    for label, pat in AI_FILLER_PATTERNS:
        if re.search(pat, text, re.I):
            issues.append(f"AI filler pattern: {label.replace('_', ' ')}")
    questions = len(re.findall(r"\?", text))
    words = max(len(text.split()), 1)
    if questions / words > 0.04:
        issues.append("too many rhetorical questions")
    return issues


def validate_title_thumbnail_pair(title: str, thumb_phrase: str) -> list[str]:
    """Title and thumbnail must complement, not duplicate."""
    errors: list[str] = []
    title_l = (title or "").lower()
    phrase_l = (thumb_phrase or "").lower()
    if not phrase_l:
        return errors
    title_words = {w for w in re.findall(r"[a-z0-9]+", title_l) if len(w) > 3}
    phrase_words = {w for w in re.findall(r"[a-z0-9]+", phrase_l) if len(w) > 2}
    overlap = title_words & phrase_words
    if len(overlap) >= 2:
        errors.append(
            "thumbnail phrase repeats title words — use a complementary hook "
            "(e.g. title: 'How Nokia Lost the War', thumbnail: 'TOO LATE')"
        )
    elif len(overlap) == 1 and len(phrase_words) <= 3:
        errors.append(
            "thumbnail phrase repeats title words — use a complementary hook "
            "(e.g. title: 'How Nokia Lost the War', thumbnail: 'TOO LATE')"
        )
    if phrase_l in title_l or title_l in phrase_l:
        errors.append("thumbnail phrase must not repeat the title")
    return errors


def auto_fix_thumbnail_phrase(content: dict) -> bool:
    """Replace thumbnail phrase when it duplicates the title. Returns True if changed."""
    title = (content.get("title") or "").strip()
    phrase = (content.get("thumbnail_phrase") or "").strip()
    if not phrase or not validate_title_thumbnail_pair(title, phrase):
        return False
    candidates = [
        (content.get("payoff") or "").strip(),
        str((content.get("key_claims") or [""])[0]).strip(),
        "THE TRUTH",
        "TOO LATE",
        "HIDDEN COST",
        "REAL STORY",
        "WATCH THIS",
    ]
    for raw in candidates:
        cand = raw.upper()[:24].strip()
        if len(cand) < 3:
            continue
        if not validate_title_thumbnail_pair(title, cand):
            content["thumbnail_phrase"] = cand
            return True
    content["thumbnail_phrase"] = "WATCH THIS"
    return True


def validate_viewer_value(content: dict, topic: str) -> tuple[bool, list[str], float]:
    """
    Viewer value test — substantive information, promise fulfillment, insight density.
    Returns (ok, errors, score 0-1).
    """
    errors: list[str] = []
    script = (content.get("script") or "").strip()
    title = (content.get("title") or "").strip()
    if not script:
        return False, ["missing script"], 0.0

    words = script.split()
    word_count = len(words)
    if word_count < 120:
        errors.append(f"script too short for viewer value ({word_count} words)")

    insights = len(INSIGHT_MARKERS.findall(script))
    insight_ratio = insights / max(word_count / 500, 1)
    if insight_ratio < 2:
        errors.append(
            "weak explanatory depth — add WHY, consequences, and concrete examples"
        )

    # Core promise: title/topic entities should appear with explanation context
    topic_tokens = [w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) > 4]
    if topic_tokens:
        hits = sum(1 for t in topic_tokens[:4] if t in script.lower())
        if hits < min(2, len(topic_tokens)):
            errors.append("script does not clearly address the topic promise")

    filler = detect_ai_filler(script)
    if len(filler) >= 3:
        errors.extend(filler[:3])

    thumb_errors = validate_title_thumbnail_pair(title, content.get("thumbnail_phrase") or "")
    errors.extend(thumb_errors)

    # Shallow listicle without substance
    if re.search(r"\b(top \d+|here are \d+ (?:things|reasons))\b", script, re.I):
        if insight_ratio < 3:
            errors.append("listicle structure without enough explanatory depth")

    score = 1.0
    score -= 0.15 * len(errors)
    score -= 0.05 * max(0, len(filler) - 1)
    score = max(0.0, min(1.0, score))
    return len(errors) == 0, errors, score


def validate_visual_plan(content: dict) -> list[str]:
    """Ensure visual keywords / segments exist and are specific."""
    errors: list[str] = []
    segments = content.get("visual_segments") or []
    keywords = content.get("video_keywords") or []
    if segments:
        generic = sum(
            1 for s in segments
            if re.search(r"\b(ai robot|futuristic|neural network|hologram)\b", str(s.get("keyword", "")), re.I)
        )
        if generic > len(segments) * 0.6:
            errors.append("visual plan too generic — use topic-specific imagery")
    elif not keywords or len(keywords) < 8:
        errors.append("insufficient visual keywords for narrative support")
    elif keywords:
        generic_kw = sum(
            1 for k in keywords
            if re.search(r"\b(ai neural|futuristic city|robot face|holographic)\b", str(k), re.I)
        )
        if generic_kw > len(keywords) * 0.5:
            errors.append("video_keywords too generic — tie visuals to the specific story")
    return errors


_SOFT_QUALITY_MARKERS = (
    "weak explanatory depth",
    "excessive line breaks",
    "spoken narration score too low",
    "viewer value score too low",
    "weak sentence connections",
    "too many very short sentences",
    "monotonous sentence rhythm",
)


def prepare_content_for_validation(content: dict, *, topic: str = "") -> dict:
    """Normalize LLM JSON before validation gates."""
    from moduli.ai_validation import fill_missing_content_fields
    from moduli.narration_quality import normalize_script_for_tts

    out = fill_missing_content_fields(dict(content), topic=topic)
    if out.get("script"):
        out["script"] = normalize_script_for_tts(out["script"])
    auto_fix_thumbnail_phrase(out)
    return out


def run_content_quality_gate(
    content: dict,
    topic: str,
    strategy: dict | None = None,
    *,
    attempt: int = 0,
    max_attempts: int = 5,
) -> tuple[bool, list[str]]:
    """Combined gate for script acceptance during generation."""
    strategy = strategy or {}
    all_errors: list[str] = []

    ok, value_errors, score = validate_viewer_value(content, topic)
    all_errors.extend(value_errors)
    if score < 0.55:
        all_errors.append(f"viewer value score too low ({score:.2f})")

    all_errors.extend(validate_visual_plan(content))

    script = (content.get("script") or "").strip()
    if script:
        try:
            from moduli.narration_quality import validate_spoken_narration
            n_ok, n_errors, n_score = validate_spoken_narration(script, fmt="longform")
            if not n_ok:
                all_errors.extend(n_errors[:3])
            if n_score < 0.55:
                all_errors.append(f"spoken narration score too low ({n_score:.2f})")
        except Exception:
            pass

    try:
        from moduli.avoid_patterns import validate_content_fields
        from moduli.preferenze import carica
        pref = carica()
        all_errors.extend(validate_content_fields(content, strategy, pref))
    except Exception:
        pass

    # Free-tier models often need late attempts to pass soft style gates.
    if attempt >= max(2, max_attempts - 2):
        all_errors = [
            e for e in all_errors
            if not any(marker in e for marker in _SOFT_QUALITY_MARKERS)
            and "script does not clearly address" not in e
            and "consecutive short sentences" not in e
            and "staccato" not in e
        ]

    return len(all_errors) == 0, all_errors


def quality_summary_for_log(content: dict, topic: str) -> str:
    ok, errors, score = validate_viewer_value(content, topic)
    return f"viewer_value={score:.2f} ok={ok} issues={len(errors)}"
