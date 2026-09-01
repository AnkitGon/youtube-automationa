"""TTS audio post-processing — detect and compress excessive pauses."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from moduli.ffmpeg_utils import ffmpeg_path, media_duration

_SILENCE_RE = re.compile(
    r"silence_start: (?P<start>[\d.]+).*?silence_end: (?P<end>[\d.]+).*?silence_duration: (?P<dur>[\d.]+)",
    re.S,
)


def _enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _silence_threshold_db() -> int:
    try:
        return int(os.environ.get("TTS_SILENCE_THRESHOLD_DB", "-35"))
    except ValueError:
        return -35


def _max_pause_seconds() -> float:
    try:
        return float(os.environ.get("TTS_MAX_PAUSE_SECONDS", "0.32"))
    except ValueError:
        return 0.32


def _compress_threshold_seconds() -> float:
    try:
        return float(os.environ.get("TTS_COMPRESS_THRESHOLD_SECONDS", "0.42"))
    except ValueError:
        return 0.42


def detect_silences(path: str, *, min_duration: float = 0.12) -> list[tuple[float, float, float]]:
    """Return (start, end, duration) silence regions detected by ffmpeg."""
    ff = ffmpeg_path()
    thresh = _silence_threshold_db()
    proc = subprocess.run(
        [
            ff, "-i", path,
            "-af", f"silencedetect=noise={thresh}dB:d={min_duration}",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    out = []
    for m in _SILENCE_RE.finditer(proc.stderr or ""):
        out.append((float(m["start"]), float(m["end"]), float(m["dur"])))
    return out


def speech_segments_and_gaps(path: str) -> tuple[list[tuple[float, float]], list[float]]:
    """Speech spans and pause durations between consecutive spans."""
    total = media_duration(path)
    silences = detect_silences(path)
    speech: list[tuple[float, float]] = []
    pos = 0.0
    for s, e, _d in silences:
        if s > pos + 0.01:
            speech.append((pos, s))
        pos = e
    if pos < total - 0.01:
        speech.append((pos, total))
    gaps = [speech[i + 1][0] - speech[i][1] for i in range(len(speech) - 1)]
    return speech, gaps


def trim_edge_silence(input_path: str, output_path: str) -> None:
    """Remove leading/trailing silence from a TTS clip (chunk boundaries)."""
    thresh = _silence_threshold_db()
    af = (
        f"silenceremove=start_periods=1:start_silence=0.02:start_threshold={thresh}dB,"
        f"areverse,silenceremove=start_periods=1:start_silence=0.02:start_threshold={thresh}dB,"
        f"areverse"
    )
    _run_ffmpeg_audio(input_path, output_path, af)


def compress_long_pauses(input_path: str, output_path: str) -> dict:
    """
    Shorten internal pauses longer than TTS_COMPRESS_THRESHOLD_SECONDS
    down to TTS_MAX_PAUSE_SECONDS. Preserves shorter natural breath pauses.
    """
    stats = {
        "input_seconds": 0.0,
        "output_seconds": 0.0,
        "gaps_compressed": 0,
        "skipped": False,
    }
    try:
        stats["input_seconds"] = media_duration(input_path)
    except Exception:
        shutil.copy2(input_path, output_path)
        stats["skipped"] = True
        return stats

    speech, gaps = speech_segments_and_gaps(input_path)
    if len(speech) <= 1:
        shutil.copy2(input_path, output_path)
        stats["output_seconds"] = stats["input_seconds"]
        stats["skipped"] = True
        return stats

    compress_at = _compress_threshold_seconds()
    target = _max_pause_seconds()
    tmpdir = tempfile.mkdtemp(prefix="tts_pacing_")
    part_paths: list[str] = []
    list_file = os.path.join(tmpdir, "concat.txt")

    try:
        for i, (start, end) in enumerate(speech):
            seg = os.path.join(tmpdir, f"seg_{i:04d}.mp3")
            _extract_clip(input_path, seg, start, end)
            part_paths.append(seg)

            if i >= len(gaps):
                continue
            gap = gaps[i]
            new_gap = gap
            if gap >= compress_at:
                new_gap = target
                stats["gaps_compressed"] += 1
            elif gap < 0.04:
                new_gap = 0.0
            if new_gap > 0.02:
                sil = os.path.join(tmpdir, f"gap_{i:04d}.mp3")
                _make_silence(sil, new_gap)
                part_paths.append(sil)

        with open(list_file, "w", encoding="utf-8") as f:
            for p in part_paths:
                f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")

        ff = ffmpeg_path()
        subprocess.run(
            [
                ff, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                "-c:a", "libmp3lame", "-q:a", "2",
                output_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        stats["output_seconds"] = media_duration(output_path)
        return stats
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def postprocess_tts_audio(input_path: str, output_path: str | None = None) -> dict:
    """
    Full TTS pacing pass: compress excessive internal pauses.
    If output_path is None, processes in place via temp file.
    """
    if not _enabled("TTS_COMPRESS_PAUSES", default=True):
        if output_path and output_path != input_path:
            shutil.copy2(input_path, output_path)
        return {"skipped": True, "reason": "TTS_COMPRESS_PAUSES=0"}

    dest = output_path or input_path
    tmp = dest + ".pacing.tmp.mp3"
    stats = compress_long_pauses(input_path, tmp)
    os.replace(tmp, dest)
    return stats


def pacing_summary(stats: dict) -> str:
    if stats.get("skipped"):
        return "[TTS/pacing] skipped"
    saved = stats.get("input_seconds", 0) - stats.get("output_seconds", 0)
    return (
        f"[TTS/pacing] {stats.get('input_seconds', 0):.1f}s -> "
        f"{stats.get('output_seconds', 0):.1f}s "
        f"(saved {saved:.1f}s, compressed {stats.get('gaps_compressed', 0)} gaps)"
    )


def _run_ffmpeg_audio(input_path: str, output_path: str, af: str) -> None:
    ff = ffmpeg_path()
    subprocess.run(
        [ff, "-y", "-i", input_path, "-af", af, "-c:a", "libmp3lame", "-q:a", "2", output_path],
        check=True,
        capture_output=True,
        text=True,
    )


def _extract_clip(input_path: str, output_path: str, start: float, end: float) -> None:
    af = f"atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS"
    _run_ffmpeg_audio(input_path, output_path, af)


def _make_silence(output_path: str, duration: float) -> None:
    ff = ffmpeg_path()
    subprocess.run(
        [
            ff, "-y",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
            "-t", f"{duration:.4f}",
            "-c:a", "libmp3lame", "-q:a", "2",
            output_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
