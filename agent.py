
"""
Autonomous YouTube AI Agent — runs 24/7 as a daemon.

Supports:
- N videos per day (videos_per_day in state.json)
- Custom trigger hours (trigger_hours_utc list in state.json)
- Auto-scheduling based on analytics (auto_scheduling in state.json)
- Force run and skip via Telegram
"""

import os
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── env validation ────────────────────────────────────────────────────────────
def _check_env() -> None:
    missing = []
    required = {
        "TELEGRAM_BOT_TOKEN": "Telegram bot token",
        "TELEGRAM_CHAT_ID":   "Telegram chat ID",
        "AI_SERVICE":         "AI service (run the wizard: python wizard.py)",
        "PEXELS_API_KEY":     "Pexels API key",
    }
    for key, label in required.items():
        if not os.environ.get(key, "").strip():
            missing.append(f"  ✗  {key}  ({label})")

    service = os.environ.get("AI_SERVICE", "")
    service_keys = {
        "openrouter":   "OPENROUTER_API_KEY",
        "openai":       "OPENAI_API_KEY",
        "anthropic":    "ANTHROPIC_API_KEY",
        "gemini":       "GEMINI_API_KEY",
        "mistral":      "MISTRAL_API_KEY",
        "groq":         "GROQ_API_KEY",
        "deepseek":     "DEEPSEEK_API_KEY",
        "xai":          "XAI_API_KEY",
        "cohere":       "COHERE_API_KEY",
        "together":     "TOGETHER_API_KEY",
        "perplexity":   "PERPLEXITY_API_KEY",
        "fireworks":    "FIREWORKS_API_KEY",
        "ollama_cloud": "OLLAMA_API_KEY",
    }
    if service in service_keys:
        key = service_keys[service]
        if not os.environ.get(key, "").strip():
            missing.append(f"  ✗  {key}  (API key for {service})")

    if missing:
        print("\n[ERRORE] Variabili mancanti nel .env:")
        for m in missing:
            print(m)
        print("\nEsegui il wizard per configurare tutto: python wizard.py\n")
        sys.exit(1)

import sys
_check_env()

from moduli.cervello import genera_topic, genera_contenuto
from moduli.audio import genera_audio
from moduli.asset import scarica_clips
from moduli.montaggio import monta_video
from moduli.thumbnail import genera_thumbnail
from moduli.pubblica import pubblica_video, calcola_publish_slots
from moduli.analytics import leggi_performance
from moduli.strategia import calcola_strategia
from moduli.notifiche import (
notify_start, notify_step, notify_done, notify_error, notify_analytics
)
from moduli.telegram_handler import start_bot
from moduli.state_io import load_state as _load_state, save_state as _save_state

AUDIO_PATH = "output/narration.mp3"
VIDEO_PATH = "output/output_finale.mp4"
THUMB_PATH = "output/thumbnail.jpg"
PID_FILE   = ".agent.pid"

DEFAULT_VIDEOS_PER_DAY = 1
DEFAULT_TRIGGER_HOURS = [14]

_pipeline_step = "init"


def _acquire_pid_lock() -> None:
    """Blocca il doppio avvio: esce se un'altra istanza è già in esecuzione."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # signal 0 = verifica esistenza senza inviare nulla
            print(f"\n[ERRORE] Agent già in esecuzione (PID {old_pid}).")
            print("Ferma l'istanza esistente prima di avviarne un'altra:")
            print(f"  kill {old_pid}")
            print(f"  oppure: pkill -f tube-assistant\n")
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            # PID non esiste più oppure file corrotto → rimuovi il file stale
            os.remove(PID_FILE)
        except OSError:
            os.remove(PID_FILE)

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    import atexit
    atexit.register(_release_pid_lock)


def _release_pid_lock() -> None:
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


class PipelineAbort(RuntimeError):
    pass


def _check_abort() -> None:
    if _load_state().get("abort_pipeline"):
        raise PipelineAbort("Pipeline interrotta su richiesta Telegram")


def _runs_today(state: dict) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return state.get("runs_today", {}).get(today, 0)


def _increment_runs_today(state: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    runs = state.get("runs_today", {})
    runs = {today: runs.get(today, 0) + 1}  # keep only today
    state["runs_today"] = runs


def _get_trigger_hours(state: dict) -> list[int]:
    """Return sorted list of hours when pipeline should run today."""
    if state.get("auto_scheduling") and state.get("best_hours_utc"):
        hours = state["best_hours_utc"]
    else:
        hours = state.get("trigger_hours_utc", DEFAULT_TRIGGER_HOURS)
    n = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    # use only the first N hours
    return sorted(hours)[:n]


def _should_run(state: dict, now: datetime) -> bool:
    if state.get("force_run"):
        return True
    videos_per_day = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    if _runs_today(state) >= videos_per_day:
        return False
    trigger_hours = _get_trigger_hours(state)
    return now.hour in trigger_hours and now.minute == 0


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding), flush=True)


def run_pipeline(state: dict, dry_run: bool = False) -> None:
    global _pipeline_step
    os.makedirs("output", exist_ok=True)
    _log("━━━ PIPELINE AVVIATA ━━━")

    # ── ANALYTICS ──────────────────────────────────────────────────────────
    _pipeline_step = "analytics"
    _log("📊 [1/7] Analytics — lettura performance canale...")
    notify_step("strategy", "Analizzo le performance del canale...")
    try:
        performance = leggi_performance(n_video=10)
        _log(f"  → {len(performance)} video analizzati")
        if performance:
            for v in performance:
                _log(f"     · {v['title'][:50]} — {v['views']} views, {v['likes']} likes")
            notify_analytics(performance)
            if state.get("auto_scheduling"):
                _update_best_hours(state, performance)
        else:
            _log("  → Nessun video precedente (canale nuovo)")
    except Exception as e:
        _log(f"  → Skipped: {e}")
        performance = []

    strategy = calcola_strategia(performance)
    _check_abort()
    _log(f"  → Strategia: {strategy.get('notes', '')}")

    # ── TOPIC & CONTENUTO ───────────────────────────────────────────────────
    _pipeline_step = "contenuto"
    _log("🧠 [2/7] Topic & Contenuto — generazione script...")
    queue = state.get("topic_queue", [])
    if queue:
        topic = queue.pop(0)
        state["topic_queue"] = queue
        _log(f"  → Topic dalla coda: {topic}")
    else:
        _log("  → Coda vuota, genero topic con AI...")
        topic = genera_topic(strategy=strategy, recent_topics=state.get("recent_topics", []))
        _log(f"  → Topic generato: {topic}")

    notify_start(topic)
    _log("  → Generazione script in corso (può richiedere 30-60s)...")
    content = genera_contenuto(topic, strategy=strategy)
    _log(f"  → Titolo: {content['title']}")
    _log(f"  → Tag: {', '.join(content.get('tags', [])[:5])}...")
    _log(f"  → Keyword video: {', '.join(content.get('video_keywords', [])[:4])}...")
    script_words = len(content.get('script', '').split())
    _check_abort()
    _log(f"  → Script: ~{script_words} parole")

    # ── AUDIO ───────────────────────────────────────────────────────────────
    _pipeline_step = "audio"
    _log("🎙️ [3/7] Audio — sintesi vocale con Edge TTS...")
    notify_step("audio", f"Sintetizzo audio: <i>{content['title']}</i>")
    genera_audio(content["script"], AUDIO_PATH)
    size = os.path.getsize(AUDIO_PATH) // 1024
    _check_abort()
    _log(f"  → Audio salvato: {AUDIO_PATH} ({size} KB)")

    # ── CLIP ────────────────────────────────────────────────────────────────
    _pipeline_step = "clips"
    _log("🎞️ [4/7] Clip — scarico video da Pexels...")
    notify_step("clips", "Scarico clip video da Pexels...")
    clip_paths = {}
    keywords = content.get("video_keywords", [])

    # quante clip distinte servono per non ripeterne nessuna nel video
    try:
        from moduli.montaggio import _media_duration, SEGMENT_DURATION
        _dur = _media_duration(AUDIO_PATH)
        target_clips = int(_dur / SEGMENT_DURATION) + 1
    except Exception:
        target_clips = max(len(keywords), 20)
    # quante clip scaricare per keyword per coprire i segmenti (max 5 = limite Pexels per_page utile)
    per_kw = max(1, min(5, -(-target_clips // max(1, len(keywords)))))
    _log(f"  → Servono ~{target_clips} clip distinte → {per_kw} per keyword")

    seen = set()
    for i, kw in enumerate(keywords):
        _log(f"  → [{i+1}/{len(keywords)}] Cerco: {kw} (x{per_kw})")
        try:
            paths = scarica_clips(kw, max_n=per_kw)
            nuove = 0
            for p in paths:
                if p in seen:
                    continue
                seen.add(p)
                clip_paths[f"{kw}#{nuove}"] = p
                nuove += 1
            _log(f"     ✓ {nuove} clip distinte")
        except Exception as e:
            _log(f"     ✗ Saltata: {e}")

    _log(f"  → {len(clip_paths)} clip distinte scaricate (target {target_clips})")
    if not clip_paths:
        msg = "Nessuna clip scaricata — pipeline interrotta"
        _log(f"  ✗ ERRORE: {msg}")
        notify_error(msg)
        raise RuntimeError(msg)

    # ── MONTAGGIO ───────────────────────────────────────────────────────────
    _check_abort()
    _pipeline_step = "montaggio"
    _log("⚙️ [5/7] Montaggio — rendering video (5-15 min)...")
    notify_step("rendering", "Montaggio in corso (5-15 min)...")
    monta_video(AUDIO_PATH, list(clip_paths.keys()), clip_paths, VIDEO_PATH)
    _check_abort()
    size = os.path.getsize(VIDEO_PATH) // (1024 * 1024)
    _log(f"  → Video salvato: {VIDEO_PATH} ({size} MB)")

    # ── THUMBNAIL ───────────────────────────────────────────────────────────
    _pipeline_step = "thumbnail"
    _log("🖼️ [6/7] Thumbnail — generazione con AI...")
    notify_step("thumbnail", "Genero la thumbnail con AI...")
    genera_thumbnail(
        content["title"], THUMB_PATH,
        thumbnail_description=content.get("thumbnail_description"),
        thumbnail_phrase=content.get("thumbnail_phrase"),
    )
    _log(f"  → Thumbnail salvata: {THUMB_PATH}")

    # ── UPLOAD ──────────────────────────────────────────────────────────────
    _check_abort()
    _pipeline_step = "upload"
    if dry_run:
        _pipeline_step = "dry_run"
        _log("DRY RUN: upload saltato. Video e thumbnail sono pronti in output/.")
        return
    _log("📤 [7/7] Upload — caricamento su YouTube...")
    notify_step("upload", "Upload su YouTube in corso...")
    run_index = _runs_today(state)
    immediate = bool(state.get("publish_immediately"))
    publish_at = None if immediate else calcola_publish_slots(state, run_index)
    if immediate:
        _log("  -> Pubblicazione immediata")
    else:
        _log(f"  → Programmato per: {publish_at.strftime('%d/%m/%Y %H:%M UTC')}")
    video_id = pubblica_video(
        VIDEO_PATH,
        THUMB_PATH,
        content,
        publish_at,
        immediate=immediate,
        privacy_status=os.environ.get("YOUTUBE_IMMEDIATE_PRIVACY", "public") if immediate else "private",
    )
    _log(f"  → ✓ https://youtu.be/{video_id}")

    notify_done(
        title=content["title"],
        video_id=video_id,
        publish_time="immediata" if immediate else publish_at.strftime("%d/%m/%Y %H:%M UTC"),
        thumb_path=THUMB_PATH,
    )

    # Ricarica lo state più recente (il bot Telegram può aver scritto durante la pipeline)
    # e applica solo le modifiche prodotte dalla pipeline — evita lost-update.
    _pipeline_step = "salvataggio"
    fresh = _load_state()
    recent = fresh.get("recent_topics", [])
    recent.insert(0, topic)
    fresh["recent_topics"] = recent[:10]
    fresh["last_run_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh["video_ids"] = ([video_id] + fresh.get("video_ids", []))[:20]
    fresh.pop("force_run", None)
    fresh.pop("publish_immediately", None)
    fresh.pop("abort_pipeline", None)
    _increment_runs_today(fresh)
    _save_state(fresh)
    _log("━━━ PIPELINE COMPLETATA ━━━\n")


def _update_best_hours(state: dict, performance: list) -> None:
    """Pick best publish hours from analytics data."""
    # Use top-views hours; fallback to spread across day
    videos_per_day = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    # Smart defaults per slot count — production/morning/evening spread
    spreads = {
        1: [20],
        2: [14, 20],
        3: [10, 15, 20],
        4: [9, 13, 17, 21],
        5: [8, 11, 14, 17, 20],
    }
    scored: dict[int, list[float]] = {}
    for video in performance:
        hour = video.get("published_hour_utc")
        if hour is None:
            continue
        views = float(video.get("views") or 0)
        ctr = float(video.get("ctr_percent") or 0)
        duration = max(float(video.get("duration_seconds") or 1), 1.0)
        retention = float(video.get("avg_view_duration_seconds") or 0) / duration * 100
        score = views + (ctr * 25) + (retention * 5)
        scored.setdefault(int(hour), []).append(score)

    if scored:
        ranked = sorted(
            ((sum(scores) / len(scores), hour) for hour, scores in scored.items()),
            reverse=True,
        )
        hours = sorted(hour for _, hour in ranked[:videos_per_day])
        fallback = [h for h in spreads.get(videos_per_day, [20]) if h not in hours]
        hours = sorted((hours + fallback)[:videos_per_day])
    else:
        hours = spreads.get(videos_per_day, [20])
    state["best_hours_utc"] = hours
    print(f"  Auto-scheduling: best hours set to {hours}")


def _cleanup_stale_state() -> None:
    """Rimuove flag che non devono persistere tra riavvii."""
    state = _load_state()
    changed = False
    if state.pop("force_run", None) is not None:
        _log("  → force_run rimosso (stale da sessione precedente)")
        changed = True
    if state.pop("publish_immediately", None) is not None:
        _log("  -> publish_immediately rimosso (stale da sessione precedente)")
        changed = True
    if state.pop("abort_pipeline", None) is not None:
        _log("  -> abort_pipeline rimosso (stale da sessione precedente)")
        changed = True
    # rimuovi topic "…" o vuoti finiti in coda per errore
    queue = state.get("topic_queue", [])
    clean_queue = [t for t in queue if t.strip() and t.strip() not in ("…", "...")]
    if len(clean_queue) != len(queue):
        _log(f"  → Rimossi {len(queue) - len(clean_queue)} topic non validi dalla coda")
        state["topic_queue"] = clean_queue
        changed = True
    # resetta runs_today se è un giorno diverso
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    runs = state.get("runs_today", {})
    if runs and today not in runs:
        state["runs_today"] = {}
        changed = True
    if changed:
        _save_state(state)
    _log(f"  Topic in coda dopo pulizia: {state.get('topic_queue', [])}")


def main():
    _acquire_pid_lock()
    _log("━━━ YouTube AI Agent avviato ━━━")
    _cleanup_stale_state()

    state = _load_state()
    trigger_hours = _get_trigger_hours(state)
    vpd = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    _log(f"  Video al giorno: {vpd} | Trigger: {trigger_hours} UTC")
    _log(f"  Topic in coda: {len(state.get('topic_queue', []))}")

    start_bot()

    while True:
        state = _load_state()
        now = datetime.now(timezone.utc)

        if now.minute == 0:
            trigger_hours = _get_trigger_hours(state)
            vpd = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
            done = _runs_today(state)
            print(f"[{now.strftime('%Y-%m-%d %H:%M UTC')}] tick — {done}/{vpd} video oggi — trigger: {trigger_hours}")

        if _should_run(state, now):
            reason = "FORCED" if state.get("force_run") else "scheduled"
            _log(f"Trigger ({reason}) — avvio pipeline")
            # Pulisci force_run PRIMA di partire: se la pipeline crasha,
            # il flag è già rimosso e il daemon non entra in loop infinito.
            state.pop("force_run", None)
            state.pop("abort_pipeline", None)
            _save_state(state)
            try:
                run_pipeline(state)
                state = _load_state()
            except Exception:
                err = traceback.format_exc()
                _log(err)
                if isinstance(sys.exc_info()[1], PipelineAbort):
                    state = _load_state()
                    state.pop("abort_pipeline", None)
                    _save_state(state)
                    notify_error("Pipeline interrotta su richiesta Telegram.")
                    continue
                last_line = err.strip().split("\n")[-1][:300]
                notify_error(
                    f"Crash allo step <b>{_pipeline_step}</b>\n\n"
                    f"<code>{last_line}</code>\n\n"
                    f"Controlla i log. Usa /forza per riprovare."
                )
                state = _load_state()

        time.sleep(60)


if __name__ == "__main__":
    main()
