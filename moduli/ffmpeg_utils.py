"""Localizzazione dei binari ffmpeg/ffprobe — condivisa da audio e montaggio."""

import glob
import os
import re
import shutil
import subprocess

_CANDIDATI_FFMPEG = [
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
]

_DURATION_RE = re.compile(
    r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _bundled_ffmpeg() -> str | None:
    """ffmpeg incluso in imageio_ffmpeg (dipendenza MoviePy) — utile su Windows."""
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


def _laragon_ffmpeg() -> str | None:
    for pattern in (
        r"C:\laragon\bin\ffmpeg\*\bin\ffmpeg.exe",
        r"C:\laragon\bin\ffmpeg\ffmpeg.exe",
    ):
        for path in sorted(glob.glob(pattern)):
            if os.path.isfile(path):
                return path
    return None


def ffmpeg_path() -> str:
    """Percorso di ffmpeg: FFMPEG_PATH > PATH > posizioni note > bundle MoviePy."""
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    for finder in (_laragon_ffmpeg,):
        found = finder()
        if found:
            return found
    for p in _CANDIDATI_FFMPEG:
        if os.path.exists(p):
            return p
    bundled = _bundled_ffmpeg()
    if bundled:
        return bundled
    raise FileNotFoundError(
        "ffmpeg not found. Install it and add to PATH, or set FFMPEG_PATH=/path/to/ffmpeg"
    )


def ffprobe_path() -> str | None:
    """ffprobe se disponibile; None se solo ffmpeg (es. bundle imageio_ffmpeg)."""
    try:
        ff = ffmpeg_path()
    except FileNotFoundError:
        return shutil.which("ffprobe")
    if ff != "ffmpeg":
        for nome in ("ffprobe.exe", "ffprobe"):
            candidato = os.path.join(os.path.dirname(ff), nome)
            if os.path.exists(candidato):
                return candidato
    return shutil.which("ffprobe")


def _duration_via_ffprobe(path: str) -> float:
    probe = ffprobe_path()
    if not probe:
        raise FileNotFoundError("ffprobe not available")
    cmd = [
        probe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()
    return max(float(out or 0), 0.01)


def _duration_via_ffmpeg(path: str) -> float:
    """Fallback quando ffprobe non c'è (tipico con il bundle imageio_ffmpeg su Windows)."""
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", path],
        capture_output=True,
        text=True,
    )
    # ffmpeg -i scrive metadati su stderr anche in caso di errore parziale
    stream = (proc.stderr or "") + (proc.stdout or "")
    match = _DURATION_RE.search(stream)
    if not match:
        raise RuntimeError(f"ffmpeg could not read duration for {path}")
    hours, minutes, seconds = match.groups()
    return max(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 0.01)


def media_duration(path: str) -> float:
    """Durata media in secondi — ffprobe se presente, altrimenti parsing ffmpeg -i."""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(path or "missing clip")
    if ffprobe_path():
        try:
            return _duration_via_ffprobe(path)
        except (subprocess.CalledProcessError, ValueError, OSError):
            pass
    return _duration_via_ffmpeg(path)
