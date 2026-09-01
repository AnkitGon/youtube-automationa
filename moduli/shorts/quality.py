"""Pre-upload quality gate for Shorts."""

from __future__ import annotations

import os

from moduli.ffmpeg_utils import media_duration
from moduli.shorts.captions import caption_coverage_ratio
from moduli.shorts.config import ShortsConfig, load_config
from moduli.shorts.history import find_duplicate
from moduli.content_quality import detect_ai_filler


def validate_short(
    *,
    content: dict,
    concept: dict,
    audio_path: str,
    video_path: str,
    ass_path: str,
    segments: list[dict],
    config: ShortsConfig | None = None,
) -> tuple[bool, list[str]]:
    cfg = config or load_config()
    if cfg.skip_quality_gate:
        return True, []

    errors: list[str] = []

    # Content
    if not content.get("hook"):
        errors.append("missing hook")
    dup, _, reason = find_duplicate(
        topic=concept.get("topic", ""),
        angle=content.get("angle", ""),
        hook=content.get("hook", ""),
        title=content.get("title", ""),
        script=content.get("script", ""),
        source_topic=concept.get("source_topic", ""),
    )
    if dup:
        errors.append(f"dedup: {reason}")

    script = content.get("script") or ""
    if len(detect_ai_filler(script)) >= 3:
        errors.append("excessive AI filler")

    # Audio
    if not os.path.exists(audio_path):
        errors.append("audio file missing")
    else:
        try:
            adur = media_duration(audio_path)
            if adur < cfg.min_duration * 0.85:
                errors.append(f"audio too short ({adur:.1f}s)")
            if adur > cfg.max_duration * 1.1:
                errors.append(f"audio too long ({adur:.1f}s)")
        except Exception:
            errors.append("audio duration unreadable")

    # Visual segments
    if not segments:
        errors.append("no visual segments")
    else:
        with_clips = sum(1 for s in segments if s.get("clip_path"))
        ratio = with_clips / len(segments)
        if ratio < 0.5:
            errors.append(f"too few matching clips ({with_clips}/{len(segments)})")
        elif all(not s.get("clip_path") for s in segments):
            errors.append("no clips acquired (fallback color only)")

    # Captions
    if not os.path.exists(ass_path):
        errors.append("ASS captions missing")
    else:
        try:
            adur = media_duration(audio_path)
            cov = caption_coverage_ratio(ass_path, adur)
            if cov < 0.8:
                errors.append(f"caption coverage too low ({cov:.0%})")
        except Exception:
            errors.append("caption validation failed")

    # Video
    if not os.path.exists(video_path):
        errors.append("video file missing")
    else:
        size = os.path.getsize(video_path)
        if size < 50_000:
            errors.append(f"video file too small ({size} bytes)")
        try:
            vdur = media_duration(video_path)
            if vdur > cfg.max_duration * 1.15:
                errors.append(f"video too long ({vdur:.1f}s)")
            if vdur < cfg.min_duration * 0.8:
                errors.append(f"video too short ({vdur:.1f}s)")
        except Exception:
            errors.append("video duration unreadable")

    # Metadata
    if not content.get("title"):
        errors.append("missing title")
    if not content.get("description"):
        errors.append("missing description")
    tags = content.get("tags") or []
    if not tags:
        errors.append("missing tags")

    return len(errors) == 0, errors
