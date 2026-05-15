
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

from moduli.cervello import genera_topic, genera_contenuto
from moduli.audio import genera_audio
from moduli.asset import scarica_clip
from moduli.montaggio import monta_video
from moduli.thumbnail import genera_thumbnail
from moduli.pubblica import pubblica_video, calcola_publish_slots
from moduli.analytics import leggi_performance
from moduli.strategia import calcola_strategia
from moduli.notifiche import (
notify_start, notify_step, notify_done, notify_error, notify_analytics
)
from moduli.telegram_handler import start_bot

STATE_FILE = "state.json"
AUDIO_PATH = "output/narration.mp3"
VIDEO_PATH = "output/output_finale.mp4"
THUMB_PATH = "output/thumbnail.jpg"

DEFAULT_VIDEOS_PER_DAY = 1
DEFAULT_TRIGGER_HOURS = [14]


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_run_date": None, "recent_topics": [], "video_ids": [], "topic_queue": []}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


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
    print(f"[{ts}] {msg}", flush=True)


def run_pipeline(state: dict) -> None:
    os.makedirs("output", exist_ok=True)
    _log("━━━ PIPELINE AVVIATA ━━━")

    # ── ANALYTICS ──────────────────────────────────────────────────────────
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
    _log(f"  → Strategia: {strategy.get('notes', '')}")

    # ── TOPIC & CONTENUTO ───────────────────────────────────────────────────
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
    _log(f"  → Script: ~{script_words} parole")

    # ── AUDIO ───────────────────────────────────────────────────────────────
    _log("🎙️ [3/7] Audio — sintesi vocale con Edge TTS...")
    notify_step("audio", f"Sintetizzo audio: <i>{content['title']}</i>")
    genera_audio(content["script"], AUDIO_PATH)
    size = os.path.getsize(AUDIO_PATH) // 1024
    _log(f"  → Audio salvato: {AUDIO_PATH} ({size} KB)")

    # ── CLIP ────────────────────────────────────────────────────────────────
    _log("🎞️ [4/7] Clip — scarico video da Pexels...")
    notify_step("clips", "Scarico clip video da Pexels...")
    clip_paths = {}
    keywords = content.get("video_keywords", [])
    for i, kw in enumerate(keywords):
        _log(f"  → [{i+1}/{len(keywords)}] Cerco: {kw}")
        try:
            path = scarica_clip(kw)
            clip_paths[kw] = path
            _log(f"     ✓ Scaricata")
        except Exception as e:
            _log(f"     ✗ Saltata: {e}")

    _log(f"  → {len(clip_paths)}/{len(keywords)} clip scaricate")
    if not clip_paths:
        msg = "Nessuna clip scaricata — pipeline interrotta"
        _log(f"  ✗ ERRORE: {msg}")
        notify_error(msg)
        raise RuntimeError(msg)

    # ── MONTAGGIO ───────────────────────────────────────────────────────────
    _log("⚙️ [5/7] Montaggio — rendering video (5-15 min)...")
    notify_step("rendering", "Montaggio in corso (5-15 min)...")
    monta_video(AUDIO_PATH, list(clip_paths.keys()), clip_paths, VIDEO_PATH)
    size = os.path.getsize(VIDEO_PATH) // (1024 * 1024)
    _log(f"  → Video salvato: {VIDEO_PATH} ({size} MB)")

    # ── THUMBNAIL ───────────────────────────────────────────────────────────
    _log("🖼️ [6/7] Thumbnail — generazione con AI...")
    notify_step("thumbnail", "Genero la thumbnail con AI...")
    genera_thumbnail(content["title"], THUMB_PATH)
    _log(f"  → Thumbnail salvata: {THUMB_PATH}")

    # ── UPLOAD ──────────────────────────────────────────────────────────────
    _log("📤 [7/7] Upload — caricamento su YouTube...")
    notify_step("upload", "Upload su YouTube in corso...")
    run_index = _runs_today(state)
    publish_at = calcola_publish_slots(state, run_index)
    _log(f"  → Programmato per: {publish_at.strftime('%d/%m/%Y %H:%M UTC')}")
    video_id = pubblica_video(VIDEO_PATH, THUMB_PATH, content, publish_at)
    _log(f"  → ✓ https://youtu.be/{video_id}")

    notify_done(
        title=content["title"],
        video_id=video_id,
        publish_time=publish_at.strftime("%d/%m/%Y %H:%M UTC"),
        thumb_path=THUMB_PATH,
    )

    recent = state.get("recent_topics", [])
    recent.insert(0, topic)
    state["recent_topics"] = recent[:10]
    state["last_run_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state["video_ids"] = ([video_id] + state.get("video_ids", []))[:20]
    state.pop("force_run", None)
    _increment_runs_today(state)
    _save_state(state)
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
            print(f"\n[{now.strftime('%Y-%m-%d %H:%M UTC')}] Trigger ({reason}) — starting pipeline")
            try:
                run_pipeline(state)
                state = _load_state()
            except Exception:
                err = traceback.format_exc()
                print(err)
                notify_error(err)

        time.sleep(60)


if __name__ == "__main__":
    main()
