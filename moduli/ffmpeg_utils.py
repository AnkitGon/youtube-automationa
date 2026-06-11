"""Localizzazione dei binari ffmpeg/ffprobe — condivisa da audio e montaggio."""

import os
import shutil

_CANDIDATI_FFMPEG = [
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
]


def ffmpeg_path() -> str:
    """Percorso di ffmpeg: FFMPEG_PATH > PATH > posizioni note. Solleva
    FileNotFoundError con istruzioni se non trovato."""
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    for p in _CANDIDATI_FFMPEG:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "ffmpeg not found. Install it and add to PATH, or set FFMPEG_PATH=/path/to/ffmpeg"
    )


def ffprobe_path() -> str:
    """ffprobe accanto a ffmpeg se possibile, altrimenti dal PATH."""
    try:
        ff = ffmpeg_path()
    except FileNotFoundError:
        return "ffprobe"
    if ff != "ffmpeg":
        for nome in ("ffprobe.exe", "ffprobe"):
            candidato = os.path.join(os.path.dirname(ff), nome)
            if os.path.exists(candidato):
                return candidato
    if shutil.which("ffprobe"):
        return "ffprobe"
    return "ffprobe"
