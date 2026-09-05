"""Generazione sottotitoli SRT dallo script narrato.

Il timing è stimato distribuendo la durata reale dell'audio in modo
proporzionale al numero di parole di ogni blocco — non è una trascrizione
forzata ma per una narrazione TTS a ritmo costante è molto vicina.
"""

import os
import re

MAX_PAROLE_BLOCCO = 5


def _blocchi(script: str) -> list[str]:
    """Spezza lo script in blocchi leggibili: frasi/clausole, poi max 5 parole."""
    testo = re.sub(r"\s+", " ", script or "").strip()
    if not testo:
        return []
    frasi = [s.strip() for s in re.split(r"(?<=[.!?])\s+", testo) if s.strip()]
    blocchi = []
    for frase in frasi:
        clausole = [c.strip() for c in re.split(r"(?<=[,;:—])\s+", frase) if c.strip()]
        for clausola in clausole:
            parole = clausola.split()
            for i in range(0, len(parole), MAX_PAROLE_BLOCCO):
                blocchi.append(" ".join(parole[i : i + MAX_PAROLE_BLOCCO]))
    return blocchi


def _timestamp(secondi: float) -> str:
    ms = max(0, int(round(secondi * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def genera_srt(script: str, durata_audio: float, output_path: str) -> str | None:
    """Scrive il file SRT e ne ritorna il percorso (None se input vuoto)."""
    blocchi = _blocchi(script)
    if not blocchi or durata_audio <= 0:
        return None
    tot_parole = sum(len(b.split()) for b in blocchi)
    righe = []
    t = 0.0
    for i, blocco in enumerate(blocchi, 1):
        durata = durata_audio * len(blocco.split()) / tot_parole
        fine = min(t + durata, durata_audio)
        righe.append(f"{i}\n{_timestamp(t)} --> {_timestamp(fine)}\n{blocco}\n")
        t = fine
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(righe))
    return output_path


def estimate_duration_from_script(script: str, wpm: float = 150.0) -> float:
    """Stima durata TTS da conteggio parole (fallback se ffmpeg non legge il file)."""
    words = len(re.sub(r"\s+", " ", script or "").split())
    if words <= 0:
        return 0.0
    return max(words / max(wpm, 80.0) * 60.0, 1.0)


def resolve_narration_duration(
    script: str,
    audio_path: str | None = None,
    video_path: str | None = None,
) -> float:
    """Durata reale da audio/video; stima dallo script se i media non sono leggibili."""
    from moduli.ffmpeg_utils import media_duration

    for path in (audio_path, video_path):
        if not path or not os.path.isfile(path):
            continue
        try:
            dur = float(media_duration(path))
            if dur > 0:
                return dur
        except Exception:
            continue
    return estimate_duration_from_script(script)


def prepare_srt(
    script: str,
    output_path: str,
    *,
    audio_path: str | None = None,
    video_path: str | None = None,
) -> str:
    """Genera SRT con fallback sulla stima — solleva ValueError se impossibile."""
    durata = resolve_narration_duration(script, audio_path, video_path)
    result = genera_srt(script, durata, output_path)
    if not result or not os.path.isfile(output_path) or os.path.getsize(output_path) < 50:
        raise ValueError("subtitle generation failed — empty script or zero duration")
    return result
