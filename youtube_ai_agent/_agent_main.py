"""
Agent daemon — imported by _launcher after os.chdir(workspace).
Do NOT add load_dotenv() here; the launcher handles it.
"""

import os
import json
import time
import traceback
from datetime import datetime, timezone

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
DEFAULT_TRIGGER_HOURS  = [14]


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
    runs = {today: runs.get(today, 0) + 1}
    state["runs_today"] = runs


def _get_trigger_hours(state: dict) -> list[int]:
    if state.get("auto_scheduling") and state.get("best_hours_utc"):
        hours = state["best_hours_utc"]
    else:
        hours = state.get("trigger_hours_utc", DEFAULT_TRIGGER_HOURS)
    n = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    return sorted(hours)[:n]


def _should_run(state: dict, now: datetime) -> bool:
    if state.get("force_run"):
        return True
    if _runs_today(state) >= state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY):
        return False
    return now.hour in _get_trigger_hours(state) and now.minute == 0


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run_pipeline(state: dict) -> None:
    os.makedirs("output", exist_ok=True)
    _log("━━━ PIPELINE AVVIATA ━━━")

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

    _log("🎙️ [3/7] Audio — sintesi vocale con Edge TTS...")
    notify_step("audio", f"Sintetizzo audio: <i>{content['title']}</i>")
    genera_audio(content["script"], AUDIO_PATH)
    _log(f"  → Audio salvato: {AUDIO_PATH}")

    _log("🎞️ [4/7] Clip — scarico video da Pexels...")
    notify_step("clips", "Scarico clip video da Pexels...")
    clip_paths = {}
    for i, kw in enumerate(content.get("video_keywords", [])):
        _log(f"  → [{i+1}] Cerco: {kw}")
        try:
            clip_paths[kw] = scarica_clip(kw)
            _log(f"     ✓ Scaricata")
        except Exception as e:
            _log(f"     ✗ Saltata: {e}")

    if not clip_paths:
        msg = "Nessuna clip scaricata — pipeline interrotta"
        notify_error(msg)
        raise RuntimeError(msg)

    _log("⚙️ [5/7] Montaggio — rendering video (5-15 min)...")
    notify_step("rendering", "Montaggio in corso (5-15 min)...")
    monta_video(AUDIO_PATH, list(clip_paths.keys()), clip_paths, VIDEO_PATH)

    _log("🖼️ [6/7] Thumbnail — generazione con AI...")
    notify_step("thumbnail", "Genero la thumbnail con AI...")
    genera_thumbnail(content["title"], THUMB_PATH)

    _log("📤 [7/7] Upload — caricamento su YouTube...")
    notify_step("upload", "Upload su YouTube in corso...")
    run_index = _runs_today(state)
    publish_at = calcola_publish_slots(state, run_index)
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
    vpd = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    spreads = {1: [20], 2: [14, 20], 3: [10, 15, 20], 4: [9, 13, 17, 21], 5: [8, 11, 14, 17, 20]}
    state["best_hours_utc"] = spreads.get(vpd, [20])


def _cleanup_stale_state() -> None:
    state = _load_state()
    changed = False
    if state.pop("force_run", None) is not None:
        changed = True
    queue = state.get("topic_queue", [])
    clean = [t for t in queue if t.strip() and t.strip() not in ("…", "...")]
    if len(clean) != len(queue):
        state["topic_queue"] = clean
        changed = True
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("runs_today") and today not in state["runs_today"]:
        state["runs_today"] = {}
        changed = True
    if changed:
        _save_state(state)


def main():
    _log("━━━ YouTube AI Agent avviato ━━━")
    _cleanup_stale_state()

    state = _load_state()
    _log(f"  Video al giorno: {state.get('videos_per_day', DEFAULT_VIDEOS_PER_DAY)}")
    _log(f"  Topic in coda: {len(state.get('topic_queue', []))}")

    start_bot()

    while True:
        state = _load_state()
        now = datetime.now(timezone.utc)

        if now.minute == 0:
            done = _runs_today(state)
            vpd  = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
            print(f"[{now.strftime('%Y-%m-%d %H:%M UTC')}] tick — {done}/{vpd} video oggi")

        if _should_run(state, now):
            reason = "FORCED" if state.get("force_run") else "scheduled"
            print(f"\n[{now.strftime('%Y-%m-%d %H:%M UTC')}] Trigger ({reason})")
            try:
                run_pipeline(state)
                state = _load_state()
            except Exception:
                err = traceback.format_exc()
                print(err)
                notify_error(err)

        time.sleep(60)
