"""
Spoken-narration quality — write for the EAR, not the page.

Used in long-form and Shorts script generation prompts, quality gates,
and TTS preprocessing.
"""

from __future__ import annotations

import re
import statistics
from typing import Literal

Format = Literal["longform", "short"]

_CONNECTIVES = re.compile(
    r"\b(and|but|because|which meant|while|instead|so|yet|although|"
    r"that's when|the problem was|here's the interesting part|"
    r"what happened next was|which is why|that meant|as a result|"
    r"however|meanwhile|after that|by contrast)\b",
    re.I,
)

_STACCATO_EXAMPLE_BAD = (
    '"Nokia was huge. Then Apple arrived. Everything changed. Nokia failed."'
)
_STACCATO_EXAMPLE_GOOD = (
    '"Nokia was huge, but then Apple arrived with a completely different idea '
    "of what a phone could be, and that changed the game almost overnight.\""
)


def narration_prompt_block(fmt: Format = "longform") -> str:
    """Prompt block injected into script-generation requests."""
    extra = ""
    if fmt == "short":
        extra = """
SHORTS PACING:
- Faster information flow — no artificial pause between every sentence
- Open with immediate story momentum; hook in the first breath
- Visual segment beats should follow narration beats, not isolated sentence gaps
- BAD: "There's something interesting about Nokia. And it has to do with Apple."
- GOOD: "There's one thing about Nokia's collapse most people miss—and it has everything to do with Apple."
"""
    else:
        extra = """
LONG-FORM PACING:
- Relaxed but never sleepy — continuous storytelling momentum
- BAD: "First... Nokia was successful. Then... Apple launched the iPhone."
- GOOD: "For years, Nokia looked almost impossible to beat. Then Apple launched the iPhone, and suddenly the definition of a great phone changed."
"""

    return f"""SPOKEN NARRATION RULES (mandatory — optimize for AUDIO, not reading):
Write for the EAR. The script must sound like a real human creator speaking naturally, NOT an AI reading an article.

CORE:
- Flowing connected speech, not isolated statements
- Vary rhythm: medium sentence → short emphasis → longer explanation → medium
- Use natural connectors: and, but, because, which meant, while, instead, so, yet, although, that's when, the problem was
- Periods = genuine thought boundaries only — not after every micro-fact
- Commas for light pauses; avoid excessive line breaks, ellipses, or one-sentence paragraphs
- NO article/essay tone ("Furthermore, the organizational structure...") — sound like a smart person explaining to a friend
- Do NOT create dramatic pauses by stacking short sentences

BAD (robotic, creates dead-air in TTS): {_STACCATO_EXAMPLE_BAD}
GOOD (continuous conversational flow): {_STACCATO_EXAMPLE_GOOD}

TTS AWARENESS:
- Output script as continuous prose (single flowing paragraph or a few natural paragraphs max)
- No headers, bullet lists, or line-break pacing tricks
- Avoid tongue-twisters and sentences too long to speak in one breath (~35 words max per sentence)
- Each sentence should connect naturally to the previous one
{extra}
FINAL CHECK before output: Would a professional YouTube narrator speak this without awkward gaps? If not, rewrite."""


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _sentence_word_counts(sentences: list[str]) -> list[int]:
    return [len(re.findall(r"\S+", s)) for s in sentences]


def analyze_narration_flow(script: str) -> dict:
    """Return metrics about spoken-flow quality."""
    raw = (script or "").strip()
    sentences = _split_sentences(raw)
    counts = _sentence_word_counts(sentences)
    n = len(sentences) or 1

    short_thresh = 5
    very_short = sum(1 for c in counts if c <= short_thresh)
    tiny = sum(1 for c in counts if c <= 3)

    max_streak = 0
    streak = 0
    for c in counts:
        if c <= short_thresh:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    connective_hits = len(_CONNECTIVES.findall(raw))
    connective_ratio = connective_hits / max(n, 1)

    newline_paragraphs = len([p for p in re.split(r"\n\s*\n", raw) if p.strip()])
    single_line_breaks = raw.count("\n")

    ellipsis_count = raw.count("...") + raw.count("…")

    length_std = statistics.pstdev(counts) if len(counts) > 1 else 0.0
    avg_len = statistics.mean(counts) if counts else 0.0

    return {
        "sentence_count": n,
        "short_sentence_ratio": very_short / n,
        "tiny_sentence_ratio": tiny / n,
        "max_short_streak": max_streak,
        "connective_ratio": connective_ratio,
        "newline_paragraphs": newline_paragraphs,
        "single_line_breaks": single_line_breaks,
        "ellipsis_count": ellipsis_count,
        "avg_sentence_words": avg_len,
        "sentence_length_std": length_std,
    }


def validate_spoken_narration(
    script: str,
    *,
    fmt: Format = "longform",
) -> tuple[bool, list[str], float]:
    """
    Narration-focused quality check for TTS delivery.
    Returns (ok, errors, score 0-1).
    """
    errors: list[str] = []
    raw = (script or "").strip()
    if not raw:
        return False, ["empty script"], 0.0

    metrics = analyze_narration_flow(raw)
    n = metrics["sentence_count"]

    # Thresholds — shorts allow slightly more punchy rhythm, not staccato stacks
    if fmt == "short":
        max_short_ratio = 0.55
        max_streak = 4
        min_connective = 0.12
        max_ellipsis = 2
    else:
        max_short_ratio = 0.45
        max_streak = 3
        min_connective = 0.10
        max_ellipsis = 3

    if metrics["short_sentence_ratio"] > max_short_ratio and n >= 4:
        errors.append(
            f"too many very short sentences ({metrics['short_sentence_ratio']:.0%}) — "
            "merge related thoughts for natural TTS flow"
        )

    if metrics["max_short_streak"] >= max_streak:
        errors.append(
            f"{metrics['max_short_streak']} consecutive short sentences — "
            "creates robotic stop-start delivery and dead-air gaps"
        )

    if n >= 6 and metrics["connective_ratio"] < min_connective:
        errors.append(
            "weak sentence connections — use and/but/because/so to link ideas naturally"
        )

    if metrics["newline_paragraphs"] > 2 or metrics["single_line_breaks"] > 4:
        errors.append(
            "excessive line breaks — write as continuous spoken prose, not stacked one-liners"
        )

    if metrics["ellipsis_count"] > max_ellipsis:
        errors.append("too many ellipses — do not use ... for artificial dramatic pauses")

    # Monotonous rhythm: all sentences similar short length
    if (
        n >= 5
        and metrics["avg_sentence_words"] < 10
        and metrics["sentence_length_std"] < 3.0
    ):
        errors.append(
            "monotonous sentence rhythm — vary length (short emphasis + longer explanations)"
        )

    # Article tone markers
    if re.search(
        r"\b(furthermore|moreover|in addition|it is worth noting|"
        r"the aforementioned|subsequently|nevertheless)\b",
        raw,
        re.I,
    ):
        errors.append("article/essay phrasing — rewrite in conversational spoken voice")

    # Staccato list pattern: "Word. Word. Word."
    if re.search(r"(?:\b\w+\.\s+){4,}", raw):
        errors.append("staccato one/two-word sentence pattern detected")

    score = 1.0
    score -= 0.18 * len(errors)
    score = max(0.0, min(1.0, score))
    return len(errors) == 0, errors, score


def normalize_script_for_tts(script: str) -> str:
    """
    Pre-TTS cleanup: remove formatting that causes unnatural pauses.
    Does not rewrite content — only normalizes delivery surface.
    """
    text = (script or "").strip()
    if not text:
        return text

    # Unify whitespace — newlines become spaces (line breaks cause TTS gaps)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"\s+", " ", text)

    # Collapse excessive ellipsis
    text = re.sub(r"\.{3,}", ".", text)
    text = re.sub(r"…+", ".", text)

    # Ensure space after sentence punctuation
    text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)

    return text.strip()


def narration_summary_for_log(script: str, fmt: Format = "longform") -> str:
    ok, errors, score = validate_spoken_narration(script, fmt=fmt)
    m = analyze_narration_flow(script)
    return (
        f"narration={score:.2f} ok={ok} "
        f"sentences={m['sentence_count']} "
        f"short_ratio={m['short_sentence_ratio']:.2f} "
        f"streak={m['max_short_streak']} "
        f"issues={len(errors)}"
    )
