import asyncio
import os
import shutil
import subprocess
import sys
import tempfile


def _ffmpeg() -> str:
    # env override first
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "ffmpeg not found. Install it and add to PATH, or set FFMPEG_PATH=/path/to/ffmpeg"
    )

VOICE_DEFAULT = "en-US-GuyNeural"
TTS_TIMEOUT = 45
CHUNK_WORDS = 300


def _split_chunks(text: str, max_words: int = CHUNK_WORDS) -> list[str]:
    sentences = text.replace("\n", " ").split(". ")
    chunks, current, count = [], [], 0
    for s in sentences:
        w = len(s.split())
        if count + w > max_words and current:
            chunks.append(". ".join(current) + ".")
            current, count = [], 0
        current.append(s)
        count += w
    if current:
        chunks.append(". ".join(current))
    return chunks


def _tts_worker(text: str, output_path: str, voice: str) -> None:
    import asyncio
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        await asyncio.wait_for(communicate.save(output_path), timeout=TTS_TIMEOUT - 5)

    asyncio.run(_run())


def _edge_tts_chunk(text: str, output_path: str, voice: str) -> bool:
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0,'.');"
         f"from moduli.audio import _tts_worker;"
         f"_tts_worker({repr(text)}, {repr(output_path)}, {repr(voice)})"],
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


def _concat_audio(parts: list[str], output_path: str) -> None:
    if len(parts) == 1:
        shutil.move(parts[0], output_path)
        return
    try:
        ff = _ffmpeg()
        list_file = output_path + ".list.txt"
        with open(list_file, "w") as f:
            for p in parts:
                f.write(f"file '{os.path.abspath(p)}'\n")
        subprocess.run(
            [ff, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
             "-c", "copy", output_path],
            check=True, capture_output=True,
        )
        os.remove(list_file)
        return
    except FileNotFoundError:
        pass
    # Fallback: raw MP3 byte concat (works since edge-tts chunks share codec/bitrate)
    with open(output_path, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                out.write(f.read())


def _edge_tts(text: str, output_path: str, voice: str) -> bool:
    chunks = _split_chunks(text)
    print(f"[TTS] Edge TTS — voce: {voice} — {len(chunks)} chunk da ~{CHUNK_WORDS} parole", flush=True)
    tmp_parts = []
    try:
        for i, chunk in enumerate(chunks):
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_chunk{i}.mp3")
            tmp = tmp_file.name
            tmp_file.close()
            tmp_parts.append(tmp)
            ok = False
            for attempt in range(2):
                print(f"[TTS]   chunk {i+1}/{len(chunks)} tentativo {attempt+1}/2...", flush=True)
                if _edge_tts_chunk(chunk, tmp, voice):
                    ok = True
                    break
            if not ok:
                print(f"[TTS]   chunk {i+1} fallito definitivamente", flush=True)
                return False
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
        return carica().get("tts_voce", VOICE_DEFAULT)
    except Exception:
        return VOICE_DEFAULT


def _gtts_lang(voice: str) -> str:
    """Estrae codice lingua da voice name Edge TTS (es. it-IT-DiegoNeural → it)."""
    parts = voice.split("-")
    return parts[0] if parts else "en"


def genera_audio(text: str, output_path: str, retries: int = 2) -> None:
    voice = _load_voice()
    words = len(text.split())
    print(f"[TTS] Edge TTS avvio — voce: {voice} ({words} parole)...", flush=True)
    if _edge_tts(text, output_path, voice):
        print(f"[TTS] Audio salvato: {output_path}", flush=True)
        return

    print("[TTS] Edge TTS fallito — provo gTTS...", flush=True)
    if _gtts(text, output_path, lang=_gtts_lang(voice)):
        print(f"[TTS] Audio salvato (gTTS): {output_path}", flush=True)
        return

    raise RuntimeError("TTS fallito: né Edge TTS né gTTS hanno funzionato")
