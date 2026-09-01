"""
Final automated quality review before YouTube upload.

Rejects weak or misleading content; returns actionable errors for regeneration.
"""

from __future__ import annotations

import os
from typing import Any

from moduli.content_quality import (
    run_content_quality_gate,
    validate_title_thumbnail_pair,
    detect_ai_filler,
)


def run_pre_publish_gate(
    content: dict,
    topic: str,
    *,
    video_path: str,
    audio_path: str,
    thumb_path: str,
    strategy: dict | None = None,
    srt_path: str | None = None,
) -> tuple[bool, list[str], list[str]]:
    """
    Returns (ok, errors, warnings).
    errors block publish; warnings are logged but non-fatal.
    """
    strategy = strategy or {}
    errors: list[str] = []
    warnings: list[str] = []

    # Topic dedup (mandatory)
    try:
        from moduli.topic_history import find_semantic_duplicate
        dup, matched, reason = find_semantic_duplicate(topic, title=content.get("title"))
        if dup:
            errors.append(f"topic duplicate: '{topic}' ~ '{matched}' ({reason})")
    except Exception as e:
        warnings.append(f"topic dedup check skipped: {e}")

    # Content quality
    ok, q_errors = run_content_quality_gate(content, topic, strategy)
    if not q_errors:
        pass
    else:
        errors.extend(q_errors)

    title = (content.get("title") or "").strip()
    if not title:
        errors.append("missing title")
    elif len(title) > 100:
        warnings.append("title exceeds 100 characters — may truncate on YouTube")

    script = content.get("script") or ""
    filler = detect_ai_filler(script)
    if len(filler) >= 4:
        errors.append("script reads as mass-produced AI content")

    pair_errors = validate_title_thumbnail_pair(title, content.get("thumbnail_phrase") or "")
    errors.extend(pair_errors)

    # Files
    for label, path in (
        ("video", video_path),
        ("audio", audio_path),
        ("thumbnail", thumb_path),
    ):
        if not path or not os.path.exists(path):
            errors.append(f"missing {label} file: {path}")
        elif label == "video" and os.path.getsize(path) < 100_000:
            errors.append("video file suspiciously small")

    # Subtitles — required unless explicitly disabled
    require_captions = os.environ.get("REQUIRE_CAPTIONS", "1").lower() not in {"0", "false", "no"}
    if require_captions:
        if not srt_path or not os.path.exists(srt_path):
            errors.append("subtitles missing — generate SRT from final narration")
        elif os.path.getsize(srt_path) < 50:
            errors.append("subtitle file empty or invalid")

    # Clickbait risk from strategy memory
    try:
        from moduli.title_learning import is_clickbait_trap_pattern
        pat = (content.get("_strategy_meta") or {}).get("title_pattern") or ""
        if pat and is_clickbait_trap_pattern(pat):
            warnings.append(f"title pattern '{pat}' flagged as high-CTR/low-retention trap")
    except Exception:
        pass

    return len(errors) == 0, errors, warnings
