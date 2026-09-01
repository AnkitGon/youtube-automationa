"""Word-group timed captions → ASS for vertical burn-in."""

from __future__ import annotations

import os
import re


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _word_groups(script: str, group_size: int = 4) -> list[str]:
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
    font_size: int = 52,
    hook_words: str = "",
) -> str:
    """Generate ASS subtitle file timed proportionally to audio duration."""
    groups = _word_groups(script, group_size=4)
    if not groups:
        groups = [script[:80]] if script else ["..."]

    total_chars = sum(len(g) for g in groups) or 1
    t = 0.0
    events = []
    hook_set = set(w.lower() for w in hook_words.split() if len(w) > 2)

    for group in groups:
        frac = len(group) / total_chars
        dur = max(0.4, audio_duration * frac)
        end = min(t + dur, audio_duration)
        style = "Hook" if any(w.lower() in hook_set for w in group.split()) else "Default"
        text = group.replace("\n", " ")
        events.append(
            f"Dialogue: 0,{_ass_time(t)},{_ass_time(end)},{style},,0,0,0,,{text}"
        )
        t = end

    margin_v = int(height * 0.12)
    ass = f"""[Script Info]
Title: Shorts Captions
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,{margin_v},1
Style: Hook,Arial Black,{font_size + 4},&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,{margin_v},1

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
