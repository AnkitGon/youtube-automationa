"""TTS audio module — Edge TTS synthesis with gap-aware assembly."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

from moduli.ffmpeg_utils import ffmpeg_path as _ffmpeg
from moduli.ffmpeg_utils import media_duration

VOICE_DEFAULT = "en-US-GuyNeural"
TTS_TIMEOUT = 45
CHUNK_WORDS = 300
_INVALID_VOICE_MARKERS = frozenset({"...", "…", "-", "default", "auto", "none", "null"})


def _normalize_voice(voice: str | None) -> str:
    """Return a usable Edge TTS voice id, falling back to the default."""
    v = (voice or "").strip()
    if not v or v.lower() in _INVALID_VOICE_MARKERS:
        return VOICE_DEFAULT
    # Edge voices look like en-US-GuyNeural (locale + name)
    if len(v) < 8 or v.count("-") < 2:
        return VOICE_DEFAULT
    return v


def _split_chunks(text: str, max_words: int = CHUNK_WORDS) -> list[str]:
    """Split long scripts for Edge TTS without breaking mid-sentence when possible."""
    text = " ".join((text or "").split())
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        w = len(s.split())
        if count + w > max_words and current:
            chunks.append(" ".join(current))
            current, count = [], 0
        current.append(s)
        count += w
    if current:
        chunks.append(" ".join(current))
    return chunks


def _tts_rate() -> str | None:
    raw = os.environ.get("TTS_RATE", "").strip() or os.environ.get("SHORTS_TTS_RATE", "").strip()
    return raw or None


def _tts_worker(text: str, output_path: str, voice: str, rate: str | None = None) -> None:
    import asyncio
    import edge_tts

    async def _run():
        kwargs = {}
        if rate:
            kwargs["rate"] = rate
        communicate = edge_tts.Communicate(text, voice, **kwargs)
        await asyncio.wait_for(communicate.save(output_path), timeout=TTS_TIMEOUT - 5)

    asyncio.run(_run())


def _edge_tts_chunk(text: str, output_path: str, voice: str, rate: str | None = None) -> bool:
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0,'.');"
         f"from moduli.audio import _tts_worker;"
         f"_tts_worker({repr(text)}, {repr(output_path)}, {repr(voice)}, {repr(rate)})"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _, stderr = proc.communicate(timeout=TTS_TIMEOUT)
        if proc.returncode == 0:
            return True
        err = stderr.decode(errors="replace").strip()
        print(f"[TTS] Edge TTS errore chunk: {err}", flush=True)
        return False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        print(f"[TTS] Edge TTS TIMEOUT {TTS_TIMEOUT}s su chunk", flush=True)
        return False


def _trim_chunk_edges(path: str) -> None:
    """Trim synthesis padding at chunk boundaries before concat."""
    from moduli.tts_pacing import trim_edge_silence

    if os.environ.get("TTS_CHUNK_EDGE_TRIM", "1").strip().lower() in {"0", "false", "no"}:
        return
    tmp = path + ".trim.tmp.mp3"
    try:
        trim_edge_silence(path, tmp)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[TTS] chunk edge trim skip: {e}", flush=True)
        if os.path.exists(tmp):
            os.remove(tmp)


def _concat_audio(parts: list[str], output_path: str) -> None:
    """Gapless concat via ffmpeg demuxer + re-encode (never raw byte concat)."""
    if len(parts) == 1:
        shutil.move(parts[0], output_path)
        return

    ff = _ffmpeg()
    list_file = output_path + ".list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    try:
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
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        err = ""
        if isinstance(e, subprocess.CalledProcessError):
            err = (e.stderr or "")[-500:]
        raise RuntimeError(f"TTS audio concat failed: {err}") from e
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


def _edge_tts(text: str, output_path: str, voice: str) -> bool:
    chunks = _split_chunks(text)
    rate = _tts_rate()
    print(
        f"[TTS] Edge TTS — voce: {voice} — {len(chunks)} chunk"
        f"{'s' if len(chunks) != 1 else ''} (~{CHUNK_WORDS} parole max)",
        flush=True,
    )
    tmp_parts: list[str] = []
    try:
        for i, chunk in enumerate(chunks):
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_chunk{i}.mp3")
            tmp = tmp_file.name
            tmp_file.close()
            ok = False
            for attempt in range(2):
                print(f"[TTS]   chunk {i+1}/{len(chunks)} tentativo {attempt+1}/2...", flush=True)
                if _edge_tts_chunk(chunk, tmp, voice, rate):
                    ok = True
                    break
            if not ok:
                print(f"[TTS]   chunk {i+1} fallito definitivamente", flush=True)
                return False
            if len(chunks) > 1:
                _trim_chunk_edges(tmp)
            tmp_parts.append(tmp)

        _concat_audio(tmp_parts, output_path)
        return True
    finally:
        for p in tmp_parts:
            if os.path.exists(p) and p != output_path:
                os.remove(p)


def _gtts(text: str, output_path: str, lang: str = "en") -> bool:
    try:
        from gtts import gTTS
        print(f"[TTS] Uso gTTS (Google) come fallback — lingua: {lang}...", flush=True)
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(output_path)
        return True
    except Exception as e:
        print(f"[TTS] gTTS errore: {e}", flush=True)
        return False


def _load_voice() -> str:
    try:
        from moduli.preferenze import carica
        return _normalize_voice(carica().get("tts_voce"))
    except Exception:
        return VOICE_DEFAULT


def _gtts_lang(voice: str) -> str:
    parts = voice.split("-")
    return parts[0] if parts else "en"


def _postprocess_narration(path: str) -> None:
    from moduli.tts_pacing import pacing_summary, postprocess_tts_audio

    try:
        before = media_duration(path)
        stats = postprocess_tts_audio(path)
        after = media_duration(path)
        print(pacing_summary(stats), flush=True)
        print(f"[TTS] durata finale: {after:.1f}s (raw {before:.1f}s)", flush=True)
    except Exception as e:
        print(f"[TTS] pacing post-process skip: {e}", flush=True)


def genera_audio(text: str, output_path: str, voice: str | None = None) -> None:
    from moduli.narration_quality import normalize_script_for_tts

    text = normalize_script_for_tts(text)
    voice = _normalize_voice(voice) if voice else _load_voice()
    words = len(text.split())
    print(f"[TTS] Edge TTS avvio — voce: {voice} ({words} parole)...", flush=True)
    if _edge_tts(text, output_path, voice):
        _postprocess_narration(output_path)
        print(f"[TTS] Audio salvato: {output_path}", flush=True)
        return

    print("[TTS] Edge TTS fallito — provo gTTS...", flush=True)
    if _gtts(text, output_path, lang=_gtts_lang(voice)):
        _postprocess_narration(output_path)
        print(f"[TTS] Audio salvato (gTTS): {output_path}", flush=True)
        return

    raise RuntimeError("TTS fallito: né Edge TTS né gTTS hanno funzionato")
