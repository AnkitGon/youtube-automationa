import os
import glob
import random
import subprocess
import time
import platform
import tempfile
import re

from moduli.ffmpeg_utils import ffmpeg_path as _ffmpeg, ffprobe_path as _ffprobe

import moviepy.config as _mpy_cfg
try:
    _mpy_cfg.FFMPEG_BINARY = _ffmpeg()
except FileNotFoundError:
    # niente crash all'import (es. CI senza ffmpeg): l'errore chiaro
    # arriverà comunque al momento del render
    pass

SEGMENT_DURATION = 5.0


def _build_clip_sequence(clip_files: list, n_segments: int) -> list:
    """Assegna a ogni segmento una clip distinta. Ogni clip e' usata una sola
    volta finche' il pool non e' esaurito; solo allora si ricomincia (shuffle,
    senza ripetere la clip a cavallo tra un giro e l'altro). Se il pool e'
    grande quanto i segmenti, nessuna clip viene ripetuta nel video."""
    uniq = list(dict.fromkeys(p for p in clip_files if p))  # dedup file fisici
    if not uniq:
        raise RuntimeError("montaggio: nessuna clip disponibile")
    seq = []
    pool = []
    last = None
    for _ in range(n_segments):
        if not pool:
            pool = uniq[:]
            random.shuffle(pool)
            if last is not None and len(pool) > 1 and pool[0] == last:
                pool.append(pool.pop(0))
        clip = pool.pop(0)
        last = clip
        seq.append(clip)
    return seq


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _is_arm_device() -> bool:
    machine = platform.machine().lower()
    return machine in {"aarch64", "arm64", "armv7l", "armv6l"} or machine.startswith("arm")


PI_SAFE_MODE = os.environ.get("PI_SAFE_MODE", "auto").lower()
_PI_LIMITED = PI_SAFE_MODE in {"1", "true", "yes", "on"} or (PI_SAFE_MODE == "auto" and _is_arm_device())

OUTPUT_W = _env_int("VIDEO_WIDTH", 1280 if _PI_LIMITED else 1920)
OUTPUT_H = _env_int("VIDEO_HEIGHT", 720 if _PI_LIMITED else 1080)
OUTPUT_FPS = _env_int("VIDEO_FPS", 24 if _PI_LIMITED else 30)
FFMPEG_THREADS = _env_int("FFMPEG_THREADS", 2 if _PI_LIMITED else 4)
X264_CRF = _env_int("X264_CRF", 28 if _PI_LIMITED else 23)
X264_PRESET = os.environ.get("X264_PRESET", "ultrafast" if _PI_LIMITED else "fast")
USE_FFMPEG_RENDER = os.environ.get("USE_FFMPEG_RENDER", "auto").lower()
_FFMPEG_ONLY = USE_FFMPEG_RENDER in {"1", "true", "yes", "on"} or (
    USE_FFMPEG_RENDER == "auto" and _PI_LIMITED
)
VIDEO_CAPTIONS = os.environ.get("VIDEO_CAPTIONS", "1").lower() not in {"0", "false", "no", "off"}
MAX_KEY_CAPTIONS = _env_int("MAX_KEY_CAPTIONS", 8)
CAPTION_FONT_SIZE = _env_int("CAPTION_FONT_SIZE", 42 if OUTPUT_H >= 720 else 32)
CAPTION_MIN_GAP_SECONDS = _env_int("CAPTION_MIN_GAP_SECONDS", 12)

_GPU_CODEC = None

def _detect_gpu_codec() -> str:
    """Rileva codec H.264 hardware disponibile (NVENC/AMF/QSV), fallback libx264."""
    global _GPU_CODEC
    if _GPU_CODEC is not None:
        return _GPU_CODEC
    try:
        out = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10
        ).stdout
        for codec in ("h264_nvenc", "h264_amf", "h264_qsv"):
            if codec in out:
                test = subprocess.run(
                    [_ffmpeg(), "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
                     "-c:v", codec, "-f", "null", "-"],
                    capture_output=True, timeout=15
                )
                if test.returncode == 0:
                    _GPU_CODEC = codec
                    print(f"[montaggio] GPU codec: {codec}", flush=True)
                    return codec
    except Exception as e:
        print(f"[montaggio] Rilevamento GPU fallito: {e}", flush=True)
    _GPU_CODEC = "libx264"
    print(f"[montaggio] Nessuna GPU compatibile — uso CPU (libx264)", flush=True)
    return _GPU_CODEC
BG_MUSIC_PATH = "assets/background.mp3"
BG_MUSIC_DIR = "assets/music"
BG_MUSIC_VOLUME = 0.1
ALLOWED_MOODS = {"epic", "chill", "mysterious", "upbeat", "tense"}


def _bg_volume() -> float:
    """Volume musica di sottofondo dalla preferenza utente `musica_volume`."""
    try:
        from moduli.preferenze import carica
        vol = float(carica().get("musica_volume", BG_MUSIC_VOLUME))
        return max(0.0, min(1.0, vol))
    except Exception:
        return BG_MUSIC_VOLUME


def _pick_music(mood: str | None) -> str | None:
    if mood and mood.lower() in ALLOWED_MOODS:
        tracks = glob.glob(os.path.join(BG_MUSIC_DIR, mood.lower(), "*.mp3"))
        if tracks:
            return random.choice(tracks)
    tracks = glob.glob(os.path.join(BG_MUSIC_DIR, "*.mp3"))
    if tracks:
        return random.choice(tracks)
    if os.path.exists(BG_MUSIC_PATH):
        return BG_MUSIC_PATH
    return None



def _resize_to_target(src: str) -> str:
    root, ext = os.path.splitext(src)
    target_suffix = f"_{OUTPUT_H}p"
    if root.endswith(target_suffix):
        return src
    for suffix in ("_1080p", "_720p", "_480p"):
        if root.endswith(suffix):
            root = root[:-len(suffix)]
            break
    dst = f"{root}{target_suffix}{ext}"
    if os.path.exists(dst):
        return dst
    codec = _detect_gpu_codec()
    if codec == "h264_nvenc":
        cmd = [_ffmpeg(), '-y', '-hwaccel', 'cuda', '-i', src,
               '-vf', f'scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=disable',
               '-c:v', codec, '-preset', 'p4', '-cq', '23', '-an', dst]
    elif codec in ("h264_amf", "h264_qsv"):
        cmd = [_ffmpeg(), '-y', '-i', src,
               '-vf', f'scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=disable',
               '-c:v', codec, '-quality', 'speed', '-an', dst]
    else:
        cmd = [_ffmpeg(), '-y', '-i', src,
               '-vf', f'scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=disable',
               '-c:v', 'libx264', '-preset', X264_PRESET, '-crf', str(X264_CRF),
               '-threads', str(FFMPEG_THREADS), '-an', dst]
    subprocess.run(cmd, check=True, capture_output=True)
    # elimina originale — teniamo solo il 1080p convertito
    try:
        os.remove(src)
    except OSError:
        pass
    return dst


def _media_duration(path: str) -> float:
    cmd = [
        _ffprobe(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()
    return max(float(out or 0), 0.01)


def _concat_file_line(path: str) -> str:
    safe = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{safe}'\n"


def _caption_filter(caption: str | None) -> str:
    vf = [
        f"scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=disable",
        f"fps={OUTPUT_FPS}",
        "format=yuv420p",
    ]
    if caption:
        text = _escape_drawtext(_caption_text(caption))
        font_part = _drawtext_font_part()
        vf.append(
            "drawtext="
            f"{font_part}"
            f"text='{text}':"
            "x=(w-text_w)/2:"
            "y=h-text_h-72:"
            f"fontsize={CAPTION_FONT_SIZE}:"
            "fontcolor=white:"
            "borderw=3:"
            "bordercolor=black:"
            "box=1:"
            "boxcolor=black@0.55:"
            "boxborderw=22"
        )
    return ",".join(vf)


def _caption_font_path() -> str | None:
    candidates = [
        "assets/font_bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _drawtext_font_part() -> str:
    path = _caption_font_path()
    if not path:
        return ""
    safe = os.path.abspath(path).replace("\\", "/").replace(":", "\\:")
    return f"fontfile='{safe}':"


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace(",", "\\,")
    )


def _caption_text(text: str) -> str:
    cleaned = " ".join(text.replace("\n", " ").split())
    cleaned = cleaned.strip(" -–—:;,.!?\"'").upper()
    words = cleaned.split()
    if len(words) > 10:
        cleaned = " ".join(words[:10])
    return cleaned[:78]


def _split_sentences(script: str) -> list[str]:
    text = re.sub(r"\s+", " ", script or "").strip()
    if not text:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _score_sentence(sentence: str) -> int:
    s = sentence.lower()
    score = 0
    strong_terms = (
        "breakthrough", "future", "cost", "energy", "power", "privacy",
        "smaller", "faster", "cheaper", "smarter", "offline", "cloud",
        "data center", "revolution", "shift", "why", "not", "but",
        "means", "winning", "practical", "access", "efficiency",
    )
    score += sum(2 for term in strong_terms if term in s)
    if re.search(r"\d", sentence):
        score += 4
    if "—" in sentence or "-" in sentence:
        score += 1
    word_count = len(sentence.split())
    if 5 <= word_count <= 18:
        score += 3
    elif word_count > 28:
        score -= 3
    return score


def _select_key_captions(script: str, total_duration: float, n_segments: int) -> dict[int, str]:
    if not VIDEO_CAPTIONS:
        return {}
    sentences = _split_sentences(script)
    candidates = []
    for idx, sentence in enumerate(sentences):
        caption = _caption_text(sentence)
        if len(caption.split()) < 4:
            continue
        candidates.append((_score_sentence(sentence), idx, caption))
    candidates.sort(key=lambda item: (-item[0], item[1]))

    max_by_duration = max(1, int(total_duration // CAPTION_MIN_GAP_SECONDS))
    target_count = min(MAX_KEY_CAPTIONS, max_by_duration, max(1, n_segments // 3), len(candidates))
    if target_count <= 0:
        return {}

    selected = sorted(candidates[:target_count], key=lambda item: item[1])
    captions = {}
    for pos, (_, _, caption) in enumerate(selected):
        segment_index = min(n_segments - 1, int((pos + 0.5) * n_segments / target_count))
        captions[segment_index] = caption
    return captions


def _render_segment_ffmpeg(src: str, dst: str, offset: float, duration: float, caption: str | None = None) -> None:
    src_duration = _media_duration(src)
    vf = _caption_filter(caption)
    if src_duration < duration:
        cmd = [_ffmpeg(), "-y", "-stream_loop", "-1", "-i", src, "-t", f"{duration:.3f}"]
    else:
        cmd = [_ffmpeg(), "-y", "-ss", f"{offset % src_duration:.3f}", "-i", src, "-t", f"{duration:.3f}"]
    cmd += [
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", X264_PRESET,
        "-crf", str(X264_CRF),
        "-threads", str(FFMPEG_THREADS),
        "-movflags", "+faststart",
        dst,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg segment failed:\n{result.stderr[-2000:]}")


def _mux_audio_ffmpeg(video_path: str, audio_path: str, output_path: str, music_path: str | None, duration: float) -> None:
    if music_path:
        cmd = [
            _ffmpeg(), "-y",
            "-i", video_path,
            "-i", audio_path,
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex",
            f"[1:a]volume=1.0[a0];[2:a]volume={_bg_volume()},atrim=0:{duration:.3f}[a1];"
            "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        cmd = [
            _ffmpeg(), "-y",
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
        raise RuntimeError(f"ffmpeg mux failed:\n{result.stderr[-2000:]}")


def _monta_video_ffmpeg(audio_path: str, keywords: list, clip_paths: dict, output_path: str, mood: str = None, on_progress=None, custom_music: str = None, captions_text: str = None) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    total_duration = _media_duration(audio_path)
    n_segments = int(total_duration / SEGMENT_DURATION) + 1
    captions = _select_key_captions(captions_text or "", total_duration, n_segments)
    music_path = custom_music if custom_music and os.path.exists(custom_music) else _pick_music(mood)
    if music_path:
        print(f"[montaggio] BG music: {music_path} (mood={mood})", flush=True)

    print(
        f"[montaggio] FFmpeg low-power — {total_duration:.0f}s, "
        f"{OUTPUT_W}x{OUTPUT_H}, {OUTPUT_FPS}fps, threads={FFMPEG_THREADS}",
        flush=True,
    )
    if captions:
        print(f"[montaggio] Testi chiave: {len(captions)} frasi", flush=True)

    if not keywords:
        raise RuntimeError("montaggio: nessuna keyword fornita — impossibile selezionare clip")

    clip_sequence = _build_clip_sequence([clip_paths[k] for k in keywords], n_segments)
    with tempfile.TemporaryDirectory(prefix="render_", dir=os.path.dirname(output_path) or None) as tmpdir:
        segment_paths = []
        for i in range(n_segments):
            seg_start = i * SEGMENT_DURATION
            remaining = total_duration - seg_start
            if remaining <= 0:
                break
            seg_dur = min(SEGMENT_DURATION, remaining)
            clip_path = clip_sequence[i]
            seg_path = os.path.join(tmpdir, f"seg_{i:04d}.mp4")
            _render_segment_ffmpeg(clip_path, seg_path, seg_start, seg_dur, captions.get(i))
            segment_paths.append(seg_path)

            pct = int((i + 1) / n_segments * 80)
            if pct % 10 == 0:
                print(f"[montaggio] Segmenti: {pct}%", flush=True)
                if on_progress:
                    on_progress(pct, "calcolo in corso")

        list_path = os.path.join(tmpdir, "segments.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for path in segment_paths:
                f.write(_concat_file_line(path))

        silent_video = os.path.join(tmpdir, "video_senza_audio.mp4")
        subprocess.run(
            [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", silent_video],
            check=True,
        )
        if on_progress:
            on_progress(90, "mux audio")
        _mux_audio_ffmpeg(silent_video, audio_path, output_path, music_path, total_duration)


def _make_segment(clip_path: str, time_offset: float, duration: float):
    from moviepy import VideoFileClip, concatenate_videoclips
    clip = VideoFileClip(_resize_to_target(clip_path), audio=False)
    if clip.duration < duration:
        times = int(duration / clip.duration) + 1
        clip = concatenate_videoclips([clip] * times)
    offset = time_offset % clip.duration
    end = min(offset + duration, clip.duration)
    if end - offset < duration and clip.duration >= duration:
        offset = 0
        end = duration
    return clip.subclipped(offset, end)


from proglog import ProgressBarLogger


class _ProgressLogger(ProgressBarLogger):
    """Estende proglog per stampare ETA ogni 10% e chiamare un callback."""

    def __init__(self, on_progress=None):
        super().__init__()
        self._start = time.time()
        self._last_pct = -1
        self._on_progress = on_progress

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr != "index":
            return
        total = self.bars[bar].get("total", 0)
        if not total:
            return
        pct = int(value / total * 100)
        if pct == self._last_pct or pct % 10 != 0:
            return
        self._last_pct = pct
        elapsed = time.time() - self._start
        eta = (elapsed / pct * (100 - pct)) if pct > 0 else 0
        eta_str = f"{int(eta // 60)}m {int(eta % 60)}s"
        print(f"[montaggio] Rendering: {pct}% — ETA: {eta_str}", flush=True)
        if self._on_progress:
            try:
                self._on_progress(pct, eta_str)
            except Exception:
                pass


def _overlay_captions_moviepy(video, captions_text: str | None,
                              total_duration: float, n_segments: int):
    """Sovrappone i testi chiave anche nel percorso MoviePy (prima li
    disegnava solo il render ffmpeg low-power). Best-effort: qualsiasi
    problema con font/TextClip non deve far fallire il render."""
    captions = _select_key_captions(captions_text or "", total_duration, n_segments)
    if not captions:
        return video
    font = _caption_font_path()
    if not font:
        print("[montaggio] Nessun font trovato — caption saltate", flush=True)
        return video
    try:
        from moviepy import CompositeVideoClip, TextClip
        overlays = []
        for idx, caption in captions.items():
            start = idx * SEGMENT_DURATION
            dur = min(SEGMENT_DURATION, total_duration - start)
            if dur <= 0:
                continue
            txt = TextClip(
                font=font,
                text=caption,
                font_size=CAPTION_FONT_SIZE,
                color="white",
                stroke_color="black",
                stroke_width=3,
                method="caption",
                size=(int(OUTPUT_W * 0.9), None),
            )
            txt = (txt.with_start(start)
                      .with_duration(dur)
                      .with_position(("center", OUTPUT_H - txt.h - 72)))
            overlays.append(txt)
        if not overlays:
            return video
        print(f"[montaggio] Testi chiave: {len(overlays)} frasi", flush=True)
        return CompositeVideoClip([video, *overlays], size=(OUTPUT_W, OUTPUT_H))
    except Exception as e:
        print(f"[montaggio] Caption MoviePy saltate: {e}", flush=True)
        return video


def monta_video(audio_path: str, keywords: list, clip_paths: dict, output_path: str, mood: str = None, on_progress=None, custom_music: str = None, captions_text: str = None) -> None:
    if _FFMPEG_ONLY:
        _monta_video_ffmpeg(audio_path, keywords, clip_paths, output_path, mood, on_progress, custom_music, captions_text)
        return

    from moviepy import AudioFileClip, CompositeAudioClip, concatenate_videoclips, concatenate_audioclips
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    narration = AudioFileClip(audio_path)
    total_duration = narration.duration

    n_segments = int(total_duration / SEGMENT_DURATION) + 1
    segments = []

    clip_sequence = _build_clip_sequence([clip_paths[k] for k in keywords], n_segments)
    for i in range(n_segments):
        seg_start = i * SEGMENT_DURATION
        remaining = total_duration - seg_start
        if remaining <= 0:
            break
        seg_dur = min(SEGMENT_DURATION, remaining)

        clip_path = clip_sequence[i]

        seg = _make_segment(clip_path, seg_start, seg_dur)
        segments.append(seg)

    if not segments:
        raise RuntimeError("montaggio: nessun segmento video creato — audio troppo corto?")
    video = concatenate_videoclips(segments, method="compose")
    video = _overlay_captions_moviepy(video, captions_text, total_duration, n_segments)

    audio_tracks = [narration]

    music_path = custom_music if custom_music and os.path.exists(custom_music) else _pick_music(mood)
    if music_path:
        print(f"[montaggio] BG music: {music_path} (mood={mood})", flush=True)
        bg = AudioFileClip(music_path).with_volume_scaled(_bg_volume())
        if bg.duration < total_duration:
            loops = int(total_duration / bg.duration) + 1
            bg = concatenate_audioclips([bg] * loops)
        bg = bg.subclipped(0, total_duration)
        audio_tracks.append(bg)

    final_audio = CompositeAudioClip(audio_tracks)
    video = video.with_audio(final_audio)

    prog_logger = _ProgressLogger(on_progress=on_progress)
    print(
        f"[montaggio] Inizio rendering — {video.duration:.0f}s di video a "
        f"{OUTPUT_FPS}fps, {OUTPUT_W}x{OUTPUT_H}, threads={FFMPEG_THREADS}, "
        f"preset={X264_PRESET}, crf={X264_CRF}",
        flush=True,
    )

    codec = _detect_gpu_codec()
    preset = "p4" if codec == "h264_nvenc" else X264_PRESET
    video.write_videofile(
        output_path,
        fps=OUTPUT_FPS,
        codec=codec,
        audio_codec="aac",
        threads=FFMPEG_THREADS,
        preset=preset,
        logger=prog_logger,
    )

    narration.close()
    video.close()
