"""Shorts pipeline configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ShortsConfig:
    enabled: bool = True
    per_day: int = 3
    # Local audience hours (SHORTS_TIMEZONE) — one Short produced per slot per day
    production_hours: list[int] = field(default_factory=lambda: [10, 15, 20])
    timezone: str = "Asia/Kolkata"
    fallback_hours: list[int] = field(default_factory=lambda: [10, 15, 20])
    publish_lead_minutes: int = 20
    min_duration: int = 20
    max_duration: int = 60
    topic_reuse: bool = True
    similarity_threshold: float = 0.78
    width: int = 1080
    height: int = 1920
    caption_font_size: int = 0  # 0 = auto (~4.5% of frame height)
    caption_uppercase: bool = True
    caption_words_per_group: int = 3
    segment_min_seconds: float = 1.5
    segment_max_seconds: float = 4.0
    analytics_min_videos: int = 6
    skip_quality_gate: bool = False
    tts_voice: str = ""
    output_dir: str = "output/shorts"
    cache_dir: str = "cache/shorts"


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _int_list(raw: str, default: list[int]) -> list[int]:
    if not raw.strip():
        return list(default)
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out or list(default)


def load_config() -> ShortsConfig:
    tz = (
        os.environ.get("SHORTS_TIMEZONE", "").strip()
        or os.environ.get("DEFAULT_PUBLISH_TIMEZONE", "Asia/Kolkata").strip()
        or "Asia/Kolkata"
    )
    prod_raw = (
        os.environ.get("SHORTS_PRODUCTION_HOURS", "").strip()
        or os.environ.get("SHORTS_PIPELINE_TRIGGER_HOURS", "").strip()
        or "10,15,20"
    )
    production_hours = _int_list(prod_raw, [10, 15, 20])
    publish_raw = os.environ.get("SHORTS_FALLBACK_HOURS", "").strip() or prod_raw
    fallback_hours = _int_list(publish_raw, production_hours)
    per_day = max(1, min(10, int(os.environ.get("SHORTS_PER_DAY", "3"))))
    per_day = min(per_day, len(production_hours))
    return ShortsConfig(
        enabled=_bool_env("SHORTS_ENABLED", True),
        per_day=per_day,
        production_hours=production_hours,
        timezone=tz,
        fallback_hours=fallback_hours,
        publish_lead_minutes=int(os.environ.get("SHORTS_PUBLISH_LEAD_MINUTES", "20")),
        min_duration=int(os.environ.get("SHORTS_MIN_DURATION", "20")),
        max_duration=int(os.environ.get("SHORTS_MAX_DURATION", "60")),
        topic_reuse=_bool_env("SHORTS_TOPIC_REUSE", True),
        similarity_threshold=float(os.environ.get("SHORTS_SIMILARITY_THRESHOLD", "0.78")),
        width=int(os.environ.get("SHORTS_WIDTH", "1080")),
        height=int(os.environ.get("SHORTS_HEIGHT", "1920")),
        caption_font_size=int(os.environ.get("SHORTS_CAPTION_FONT_SIZE", "0")),
        caption_uppercase=_bool_env("SHORTS_CAPTION_UPPERCASE", True),
        caption_words_per_group=max(2, int(os.environ.get("SHORTS_CAPTION_WORDS_PER_GROUP", "3"))),
        segment_min_seconds=float(os.environ.get("SHORTS_SEGMENT_MIN_SECONDS", "1.5")),
        segment_max_seconds=float(os.environ.get("SHORTS_SEGMENT_MAX_SECONDS", "4")),
        analytics_min_videos=int(os.environ.get("SHORTS_ANALYTICS_MIN_VIDEOS", "6")),
        skip_quality_gate=_bool_env("SHORTS_SKIP_QUALITY_GATE", False),
        tts_voice=os.environ.get("SHORTS_TTS_VOICE", "").strip(),
        output_dir=os.environ.get("SHORTS_OUTPUT_DIR", "output/shorts").strip(),
        cache_dir=os.environ.get("SHORTS_CACHE_DIR", "cache/shorts").strip(),
    )
