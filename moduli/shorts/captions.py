"""Word-group timed captions → ASS for vertical burn-in."""

from __future__ import annotations

import os
import re


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def resolve_caption_font_size(height: int, font_size: int | None = None) -> int:
    """Pick a mobile-readable caption size for 9:16 Shorts (~4.5% of frame height)."""
    if font_size and font_size > 0:
        return font_size
    # ~86px at 1920p — much more legible than the old 52px default
    return max(72, int(round(height * 0.045)))


def caption_layout(
    *,
    width: int = 1080,
    height: int = 1920,
    font_size: int | None = None,
) -> dict[str, int]:
    """ASS style numbers tuned for YouTube Shorts on mobile."""
    base = resolve_caption_font_size(height, font_size)
    scale = height / 1920
    outline = max(5, int(round(6 * scale)))
    shadow = max(2, int(round(2 * scale)))
    hook_outline = outline + 1
    return {
        "font_size": base,
        "hook_font_size": base + max(8, int(round(10 * scale))),
        "outline": outline,
        "hook_outline": hook_outline,
        "shadow": shadow,
        "hook_shadow": shadow + 1,
        # Keep captions above Shorts UI chrome (channel name, buttons, description)
        "margin_v": int(height * 0.22),
        "margin_lr": max(48, int(width * 0.06)),
    }


def _word_groups(script: str, group_size: int = 3) -> list[str]:
    words = re.findall(r"\S+", (script or "").strip())
    groups = []
    for i in range(0, len(words), group_size):
        groups.append(" ".join(words[i : i + group_size]))
    return [g for g in groups if g]


def generate_ass(
    script: str,
    audio_duration: float,
    output_path: str,
    *,
    width: int = 1080,
    height: int = 1920,
    font_size: int | None = None,
    hook_words: str = "",
    uppercase: bool = True,
    words_per_group: int = 3,
) -> str:
    """Generate ASS subtitle file timed proportionally to audio duration."""
    layout = caption_layout(width=width, height=height, font_size=font_size)
    groups = _word_groups(script, group_size=max(2, words_per_group))
    if not groups:
        groups = [script[:80]] if script else ["..."]

    total_chars = sum(len(g) for g in groups) or 1
    raw_durs = [audio_duration * (len(g) / total_chars) for g in groups]
    clamped_durs = [max(0.25, d) for d in raw_durs]
    total_clamped = sum(clamped_durs) or audio_duration
    scale = audio_duration / total_clamped
    group_durs = [d * scale for d in clamped_durs]

    t = 0.0
    events = []
    hook_set = {w.lower() for w in hook_words.split() if len(w) > 2}

    for i, group in enumerate(groups):
        dur = group_durs[i]
        end = audio_duration if i == len(groups) - 1 else min(t + dur, audio_duration)
        style = "Hook" if any(w.lower() in hook_set for w in group.split()) else "Default"
        text = group.replace("\n", " ")
        if uppercase:
            text = text.upper()
        events.append(
            f"Dialogue: 0,{_ass_time(t)},{_ass_time(end)},{style},,0,0,0,,{text}"
        )
        t = end

    fs = layout["font_size"]
    hfs = layout["hook_font_size"]
    ass = f"""[Script Info]
Title: Shorts Captions
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,{fs},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,{layout["outline"]},{layout["shadow"]},2,{layout["margin_lr"]},{layout["margin_lr"]},{layout["margin_v"]},1
Style: Hook,Arial Black,{hfs},&H0000FFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,{layout["hook_outline"]},{layout["hook_shadow"]},2,{layout["margin_lr"]},{layout["margin_lr"]},{layout["margin_v"]},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass += "\n".join(events) + "\n"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass)
    return output_path


def caption_coverage_ratio(ass_path: str, audio_duration: float) -> float:
    """Estimate how much of the audio timeline ASS covers."""
    if not os.path.exists(ass_path) or audio_duration <= 0:
        return 0.0
    try:
        with open(ass_path, encoding="utf-8") as f:
            text = f.read()
        times = re.findall(r"Dialogue: \d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+)", text)
        if not times:
            return 0.0

        def _parse(t: str) -> float:
            parts = t.split(":")
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

        last_end = max(_parse(end) for _, end in times)
        return min(1.0, last_end / audio_duration)
    except Exception:
        return 0.0
