"""9:16 vertical FFmpeg montage with burned ASS captions."""

from __future__ import annotations

import os
import subprocess
import tempfile

from moduli.ffmpeg_utils import ffmpeg_path, media_duration
from moduli.shorts.config import ShortsConfig, load_config


def _vertical_vf(width: int, height: int, ass_path: str | None = None) -> str:
    base = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )
    if ass_path and os.path.exists(ass_path):
        escaped = ass_path.replace("\\", "/").replace(":", "\\:")
        base += f",subtitles='{escaped}'"
    return base


def _render_segment(
    src: str | None,
    dst: str,
    duration: float,
    *,
    width: int,
    height: int,
    ass_path: str | None = None,
) -> None:
    ff = ffmpeg_path()
    vf = _vertical_vf(width, height, ass_path=None)  # captions burned at concat stage
    if src and os.path.exists(src):
        try:
            src_dur = media_duration(src)
        except Exception:
            src_dur = duration
        if src_dur < duration:
            cmd = [ff, "-y", "-stream_loop", "-1", "-i", src, "-t", f"{duration:.3f}"]
        else:
            cmd = [ff, "-y", "-ss", "0", "-i", src, "-t", f"{duration:.3f}"]
    else:
        # Solid color fallback
        cmd = [
            ff, "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x1a1a2e:s={width}x{height}:d={duration:.3f}",
        ]
    cmd += [
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-r", "30",
        "-movflags", "+faststart",
        dst,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg segment failed: {result.stderr[-1500:]}")


def _concat_segments(segment_paths: list[str], output_path: str) -> None:
    ff = ffmpeg_path()
    list_file = output_path + ".list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [
        ff, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "copy", "-movflags", "+faststart", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(list_file)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-1500:]}")


def _burn_captions(video_path: str, ass_path: str, output_path: str, width: int, height: int) -> None:
    ff = ffmpeg_path()
    vf = _vertical_vf(width, height, ass_path)
    cmd = [
        ff, "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-an", "-movflags", "+faststart", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg caption burn failed: {result.stderr[-1500:]}")


def _mux_audio(video_path: str, audio_path: str, output_path: str) -> None:
    ff = ffmpeg_path()
    cmd = [
        ff, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {result.stderr[-1500:]}")


def _segment_durations(segments: list[dict], audio_dur: float, cfg: ShortsConfig) -> list[float]:
    """Allocate clip time proportional to each segment's narration text."""
    weights = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        w = max(1, len(text.split()))
        weights.append(w)
    total = sum(weights) or 1
    durs = []
    for w in weights:
        dur = audio_dur * w / total
        dur = max(cfg.segment_min_seconds, min(cfg.segment_max_seconds * 1.5, dur))
        durs.append(dur)
    # Rescale so sum matches audio (after clamping)
    scale = audio_dur / (sum(durs) or audio_dur)
    return [d * scale for d in durs]


def monta_short(
    audio_path: str,
    segments: list[dict],
    ass_path: str,
    output_path: str,
    *,
    config: ShortsConfig | None = None,
) -> float:
    """
    Render vertical Short video.
    segments: list from visuals.acquire_segment_clips()
    Returns final duration in seconds.
    """
    cfg = config or load_config()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    audio_dur = media_duration(audio_path)
    seg_durations = _segment_durations(segments, audio_dur, cfg)

    tmpdir = tempfile.mkdtemp(prefix="shorts_render_")
    seg_paths = []
    try:
        for i, seg in enumerate(segments):
            dur = seg_durations[i] if i < len(seg_durations) else audio_dur / max(len(segments), 1)
            seg_out = os.path.join(tmpdir, f"seg_{i:04d}.mp4")
            _render_segment(
                seg.get("clip_path"),
                seg_out,
                dur,
                width=cfg.width,
                height=cfg.height,
            )
            seg_paths.append(seg_out)

        if not seg_paths:
            seg_out = os.path.join(tmpdir, "seg_0000.mp4")
            _render_segment(None, seg_out, audio_dur, width=cfg.width, height=cfg.height)
            seg_paths = [seg_out]

        raw_video = os.path.join(tmpdir, "concat.mp4")
        _concat_segments(seg_paths, raw_video)

        captioned = os.path.join(tmpdir, "captioned.mp4")
        if ass_path and os.path.exists(ass_path):
            _burn_captions(raw_video, ass_path, captioned, cfg.width, cfg.height)
        else:
            captioned = raw_video

        _mux_audio(captioned, audio_path, output_path)
        return media_duration(output_path)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def extract_first_frame(video_path: str, thumb_path: str, width: int = 1080, height: int = 1920) -> str:
    """Extract first frame as thumbnail for YouTube upload requirement."""
    ff = ffmpeg_path()
    os.makedirs(os.path.dirname(thumb_path) or ".", exist_ok=True)
    cmd = [
        ff, "-y", "-i", video_path,
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        "-vframes", "1", thumb_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return thumb_path
