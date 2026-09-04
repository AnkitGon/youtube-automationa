
"""
Autonomous YouTube AI Agent — runs 24/7 as a daemon.

Supports:
- N videos per day (videos_per_day in state.json)
- Custom trigger hours (trigger_hours_utc list in state.json)
- Auto-scheduling based on analytics (auto_scheduling in state.json)
- Force run and skip via Telegram
"""

import html
import os
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv


def _h(value) -> str:
    """Escape per i messaggi Telegram con parse_mode=HTML."""
    return html.escape(str(value), quote=True)

# Load .env from CONFIG_DIR if set, else project root
_config_env = os.environ.get("CONFIG_DIR", "").strip()
if _config_env:
    load_dotenv(os.path.join(os.path.abspath(_config_env), ".env"))
else:
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
        "azure_openai": "AZURE_OPENAI_API_KEY",
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
from moduli.pubblica import pubblica_video, calcola_publish_slots, resolve_publish_schedule
from moduli.publish_scheduler import log_schedule_decision
from moduli.analytics_cache import get_channel_performance
from moduli.strategia import calcola_strategia, ANALYTICS_UNAVAILABLE_NOTE
from moduli.manutenzione import (
    assicura_spazio, pulisci_cache, pulisci_temp_render, spazio_libero_gb,
)
from moduli.notifiche import (
notify_start, notify_step, notify_done, notify_error, notify_analytics
)
from moduli.telegram_handler import start_bot
from moduli.pipeline_flags import long_form_enabled
from moduli.state_io import load_state as _load_state, save_state as _save_state

AUDIO_PATH = "output/narration.mp3"
VIDEO_PATH = "output/output_finale.mp4"
THUMB_PATH = "output/thumbnail.jpg"
CHECKPOINT_PATH = "output/pipeline_checkpoint.json"
PID_FILE   = ".agent.pid"

DEFAULT_VIDEOS_PER_DAY = 1
DEFAULT_TRIGGER_HOURS = [14]
# la produzione parte 3 ore prima dell'orario di pubblicazione
TRIGGER_LEAD_HOURS = 3

_pipeline_step = "init"


def _segna_step(nome: str, pct: int | None = None) -> None:
    """Aggiorna lo step corrente sia in memoria (per i crash report) sia in
    state.json (pipeline_status), così /status mostra cosa sta succedendo."""
    global _pipeline_step
    _pipeline_step = nome
    try:
        fresh = _load_state()
        status = {
            "step": nome,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        if pct is not None:
            status["pct"] = pct
        fresh["pipeline_status"] = status
        _save_state(fresh)
    except Exception:
        pass


def _pulisci_status_pipeline() -> None:
    try:
        fresh = _load_state()
        if fresh.pop("pipeline_status", None) is not None:
            _save_state(fresh)
    except Exception:
        pass


def _spiega_errore(err: str) -> str:
    """Traduce gli errori comuni in un messaggio umano con l'azione da fare."""
    e = err.lower()
    if "uploadlimitexceeded" in e or "quotaexceeded" in e or "dailylimitexceeded" in e:
        return ("Quota YouTube esaurita per oggi: si resetta a mezzanotte ora del "
                "Pacifico (~09:00 in Italia). Riprova più tardi con /forza.")
    if "invalid_grant" in e or "refresherror" in e or ("token" in e and ("expired" in e or "revoked" in e)):
        return "Login Google scaduto o revocato: cancella token.json e riavvia l'agente per rifare il login."
    if "no space left" in e or "errno 28" in e or "spazio disco insufficiente" in e:
        return "Disco pieno: libera spazio e riprova con /forza."
    if "ffmpeg not found" in e:
        return "ffmpeg non trovato: installalo e aggiungilo al PATH, oppure imposta FFMPEG_PATH nel .env."
    if "pexels" in e and ("401" in e or "403" in e or "unauthorized" in e):
        return "Chiave Pexels rifiutata: controlla PEXELS_API_KEY nel .env."
    if "no pexels results" in e or "nessuna clip" in e:
        return "Nessuna clip trovata per le keyword generate: riprova con /forza (verranno generate keyword nuove)."
    if "429" in e or "ratelimit" in e or "rate limit" in e or "too many requests" in e:
        return "Servizio esterno in rate limit (troppe richieste): aspetta qualche minuto e usa /forza."
    if ("connection" in e or "timed out" in e or "timeout" in e
            or "getaddrinfo" in e or "name resolution" in e or "unreachable" in e):
        return "Problema di rete: controlla la connessione. Riproverò al prossimo orario, oppure usa /forza."
    if "script troppo corto" in e:
        return "L'AI ha generato uno script troppo corto due volte: riprova con /forza o cambia topic."
    return ""


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
        except PermissionError:
            # il processo esiste ma non abbiamo i permessi per segnalarlo:
            # è comunque in esecuzione → non avviare una seconda istanza
            print(f"\n[ERRORE] Agent già in esecuzione (PID {old_pid}).")
            sys.exit(1)
        except (ValueError, ProcessLookupError, OSError):
            # PID non esiste più oppure file corrotto → rimuovi il file stale
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
    """Return sorted UTC hours when the pipeline should run (not publish time)."""
    from moduli.publish_scheduler import resolve_pipeline_trigger_hours
    return resolve_pipeline_trigger_hours(state)


def _should_run(state: dict, now: datetime, last_attempt: tuple | None = None) -> bool:
    if not long_form_enabled():
        return False
    if state.get("force_run"):
        return True
    videos_per_day = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    if _runs_today(state) >= videos_per_day:
        return False
    trigger_hours = _get_trigger_hours(state)
    if not trigger_hours:
        return False
    day = now.strftime("%Y-%m-%d")
    hour_key = (day, now.hour)
    # finestra = tutta l'ora (non solo minute==0): un tick saltato per drift
    # del loop non fa perdere il video. last_attempt evita doppi trigger.
    if now.hour in trigger_hours and hour_key != last_attempt:
        return True
    # Catch-up: quota non raggiunta e trigger passato — una volta al giorno
    catch_key = (day, "catchup")
    if now.hour > max(trigger_hours) and last_attempt != catch_key:
        return True
    return False


def _long_form_catchup_pending(state: dict, now: datetime) -> bool:
    """True if today's long video is still due after the scheduled trigger hour."""
    if not long_form_enabled():
        return False
    if state.get("force_run"):
        return False
    vpd = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    if _runs_today(state) >= vpd:
        return False
    trigger_hours = _get_trigger_hours(state)
    return bool(trigger_hours) and now.hour > max(trigger_hours)


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding), flush=True)


# ── checkpoint: riprende la pipeline dal punto del crash invece di rifare tutto ─

def _load_checkpoint() -> dict:
    """Checkpoint valido solo se creato oggi — altrimenti si riparte da zero."""
    try:
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("date") != today or not isinstance(data.get("steps"), list):
        return {}
    return data


def _save_checkpoint(cp: dict) -> None:
    cp["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        tmp = CHECKPOINT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cp, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CHECKPOINT_PATH)
    except OSError as e:
        _log(f"  ! Checkpoint not saved: {e}")


def _clear_checkpoint() -> None:
    try:
        os.remove(CHECKPOINT_PATH)
    except OSError:
        pass


def _scarica_tutte_le_clips(keywords: list) -> dict:
    """Scarica abbastanza clip distinte da coprire tutti i segmenti del video."""
    clip_paths = {}
    # quante clip distinte servono per non ripeterne nessuna nel video
    try:
        from moduli.montaggio import _media_duration, SEGMENT_DURATION
        _dur = _media_duration(AUDIO_PATH)
        target_clips = int(_dur / SEGMENT_DURATION) + 1
    except Exception:
        target_clips = max(len(keywords), 20)
    # quante clip scaricare per keyword per coprire i segmenti (max 5 = limite Pexels per_page utile)
    per_kw = max(1, min(5, -(-target_clips // max(1, len(keywords)))))
    _log(f"  -> Need ~{target_clips} unique clips -> {per_kw} per keyword")

    seen = set()
    for i, kw in enumerate(keywords):
        _log(f"  -> [{i+1}/{len(keywords)}] Searching: {kw} (x{per_kw})")
        try:
            paths = scarica_clips(kw, max_n=per_kw)
            nuove = 0
            for p in paths:
                if p in seen:
                    continue
                seen.add(p)
                clip_paths[f"{kw}#{nuove}"] = p
                nuove += 1
            _log(f"     OK {nuove} unique clips")
        except Exception as e:
            _log(f"     SKIP: {e}")

    _log(f"  -> {len(clip_paths)} unique clips downloaded (target {target_clips})")
    return clip_paths


def run_pipeline(state: dict, dry_run: bool = False) -> None:
    if not long_form_enabled():
        _log("Long-form pipeline disabled (LONG_FORM_ENABLED=false) — skipping")
        return
    os.makedirs("output", exist_ok=True)
    _log("=== PIPELINE STARTED ===")

    # ── ANALYTICS ──────────────────────────────────────────────────────────
    _segna_step("analytics")
    _log("[1/7] Analytics — reading channel performance...")
    notify_step("strategy", "Analyzing channel performance...")
    analytics_status = "ok"
    performance: list[dict] = []
    analytics_source = "none"
    try:
        performance, analytics_source = get_channel_performance(n_video=10, force=False)
        _log(f"  -> {len(performance)} videos analyzed (source: {analytics_source})")
        # Audience activity for deterministic publish scheduler (separate from strategy LLM)
        audience_activity = {}
        audience_geography = {}
        audience_bundle = {}
        try:
            from moduli.analytics import leggi_channel_audience_bundle, leggi_audience_activity, leggi_audience_geography
            audience_activity = leggi_audience_activity()
            audience_geography = leggi_audience_geography()
            audience_bundle = leggi_channel_audience_bundle()
            if audience_activity.get("has_data"):
                _log(
                    f"  -> Viewer activity: {audience_activity.get('total_views', 0)} views "
                    f"across {len(audience_activity.get('buckets') or [])} hour buckets"
                )
            if audience_geography.get("has_data"):
                top = (audience_geography.get("countries") or [{}])[0]
                _log(f"  -> Top audience country: {top.get('country', '?')} ({top.get('views', 0)} views)")
        except Exception as e:
            _log(f"  -> Audience scheduling data skipped: {e}")
        fresh_sched = _load_state()
        fresh_sched["_scheduler_cache"] = {
            "activity": audience_activity,
            "geography": audience_geography,
            "audience_bundle": audience_bundle,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        _save_state(fresh_sched)
        if performance:
            for v in performance:
                _log(f"     · {v['title'][:50]} — {v['views']} views, {v['likes']} likes")
            try:
                notify_analytics(performance)
            except Exception as e:
                _log(f"  -> Analytics notification skipped: {e}")
            if state.get("auto_scheduling"):
                try:
                    _update_best_hours(state, performance)
                except Exception as e:
                    _log(f"  -> Auto-scheduling skipped: {e}")
        else:
            analytics_status = "empty"
            _log(f"  → {ANALYTICS_UNAVAILABLE_NOTE}")
    except Exception as e:
        analytics_status = "error"
        _log(f"  -> Analytics unavailable: {e}")
        _log(f"  → {ANALYTICS_UNAVAILABLE_NOTE}")
        performance = []

    state = _load_state()
    strategy = calcola_strategia(performance, state=state)
    try:
        from moduli.channel_learning import describe_learning_stage, run_daily_learning_update
        from moduli.publish_optimization import build_publish_strategy
        from moduli.performance import carica_profili, sync_profiles

        profiles = carica_profili()
        if performance and not profiles:
            profiles = sync_profiles(performance)
        insights = strategy.get("_insights") or {}
        learning = run_daily_learning_update(profiles, insights, strategy, state)
        pub_strategy = build_publish_strategy(profiles, state=state)
        fresh_timing = _load_state()
        fresh_timing["publish_timing"] = pub_strategy
        if pub_strategy.get("best_hours_utc"):
            fresh_timing["best_hours_utc"] = pub_strategy["best_hours_utc"]
        _save_state(fresh_timing)
        vc = len(performance) if performance else int(insights.get("video_count") or 0)
        _log(f"  -> Learning stage: {describe_learning_stage(vc)}")
        if pub_strategy.get("reason"):
            _log(f"  -> Publish timing: {pub_strategy.get('reason')[:120]}")
    except Exception as e:
        _log(f"  -> Learning update skipped: {e}")
        try:
            from moduli.channel_learning import describe_learning_stage
            vc = len(performance) if performance else 0
            _log(f"  -> Learning stage: {describe_learning_stage(vc)}")
        except Exception:
            pass
    # titoli sotto-performanti → evitati in topic/content
    if performance:
        from moduli.performance import score_video
        scored = sorted(performance, key=score_video)
        strategy["_recent_underperformers"] = [
            v.get("title", "")[:60]
            for v in scored[:2]
            if v.get("title") and int(v.get("views") or 0) > 0
        ]
    fresh = _load_state()
    fresh["last_strategy"] = strategy
    if strategy.get("structured"):
        fresh["strategy_structured"] = strategy["structured"]
    fresh["last_analytics_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fresh["last_analytics_status"] = analytics_status
    fresh["last_analytics_source"] = analytics_source
    _save_state(fresh)
    _check_abort()
    notes = strategy.get("notes", "")
    if isinstance(notes, list):
        notes = "; ".join(str(n) for n in notes)
    _log(f"  -> Strategy: {str(notes)[:200]}")
    structured = strategy.get("structured") or {}
    if structured:
        from moduli.strategy_output import structured_summary_text
        for line in structured_summary_text(structured).split("\n")[:4]:
            if line.strip():
                _log(f"  → {line.strip()}")

    # ── TOPIC & CONTENUTO ───────────────────────────────────────────────────
    _segna_step("contenuto")
    _log("[2/7] Topic & script — generating content...")
    cp = _load_checkpoint()
    if "content" in cp.get("steps", []) and cp.get("content"):
        topic = cp.get("topic", "")
        content = cp["content"]
        _log(f"  -> Resumed from checkpoint: {topic}")
    else:
        cp = {"steps": []}
        queue = state.get("topic_queue", [])
        if queue:
            topic = queue.pop(0)
            state["topic_queue"] = queue
            # persisti subito la rimozione dalla coda (ricaricando lo state più
            # recente: il bot può aver scritto nel frattempo) — altrimenti lo
            # stesso topic verrebbe riprodotto a ogni run.
            fresh = _load_state()
            fresh_queue = fresh.get("topic_queue", [])
            if topic in fresh_queue:
                fresh_queue.remove(topic)
                fresh["topic_queue"] = fresh_queue
                _save_state(fresh)
            from moduli.topic_history import assert_unique_topic, TopicDuplicateError
            try:
                topic = assert_unique_topic(topic)
                from moduli.topic_diversity import decide_mode, record_mode
                strategy["_topic_diversity_mode"] = decide_mode(strategy)
                record_mode(strategy["_topic_diversity_mode"], topic)
                _log(f"  -> Topic from queue: {topic}")
            except TopicDuplicateError as e:
                _log(f"  -> Queue topic is a duplicate ({e.matched}), generating a new one...")
                topic = genera_topic(
                    strategy=strategy,
                    recent_topics=state.get("recent_topics", []),
                    extra_banned=[topic],
                )
                _log(f"  -> Topic generated: {topic}")
        else:
            _log("  -> Queue empty, generating topic with AI...")
            topic = genera_topic(strategy=strategy, recent_topics=state.get("recent_topics", []))
            _log(f"  -> Topic generated: {topic}")

        notify_start(topic)
        _log("  -> Generating script (may take 30-60s)...")
        content = genera_contenuto(topic, strategy=strategy)
        exp = (content.get("_strategy_meta") or {}).get("experimentation") or {}
        if exp.get("label"):
            from moduli.experimentation import format_classification
            preview = format_classification({
                "video_number": "?",
                "mode": exp.get("mode"),
                "label": exp.get("label"),
            })
            _log(f"  -> Video strategy: {preview}")
        cp.update({"topic": topic, "content": content, "steps": ["content"]})
        _save_checkpoint(cp)
    _log(f"  -> Title: {content['title']}")
    _log(f"  -> Tags: {', '.join(content.get('tags', [])[:5])}...")
    _log(f"  -> Clip keywords: {', '.join(content.get('video_keywords', [])[:4])}...")
    script_words = len(content.get('script', '').split())
    _check_abort()
    _log(f"  -> Script: ~{script_words} words")

    # ── AUDIO ───────────────────────────────────────────────────────────────
    _segna_step("audio")
    _log("[3/7] Audio — Edge TTS synthesis...")
    if "audio" in cp["steps"] and os.path.exists(AUDIO_PATH):
        _log(f"  -> Resumed from checkpoint: {AUDIO_PATH}")
    else:
        notify_step("audio", f"Synthesizing audio: <i>{_h(content['title'])}</i>")
        genera_audio(content["script"], AUDIO_PATH)
        cp["steps"].append("audio")
        _save_checkpoint(cp)
    size = os.path.getsize(AUDIO_PATH) // 1024
    _check_abort()
    _log(f"  -> Audio saved: {AUDIO_PATH} ({size} KB)")

    # ── CLIP ────────────────────────────────────────────────────────────────
    _segna_step("clips")
    _log("[4/7] Clips — downloading stock video from Pexels...")
    keywords = content.get("video_keywords", [])
    clip_paths = {}
    if "clips" in cp["steps"] and cp.get("clip_paths"):
        cached = {k: p for k, p in cp["clip_paths"].items() if os.path.exists(p)}
        if cached:
            clip_paths = cached
            _log(f"  -> Resumed from checkpoint: {len(clip_paths)} clips")
    if not clip_paths:
        notify_step("clips", "Downloading stock clips from Pexels...")
        clip_paths = _scarica_tutte_le_clips(keywords)
        cp["clip_paths"] = clip_paths
        if "clips" not in cp["steps"]:
            cp["steps"].append("clips")
        _save_checkpoint(cp)

    # le clip appena scaricate servono al montaggio: mai potarle (LRU per mtime
    # le cancellerebbe perche' scaricate per prime → ffprobe crash al render)
    liberati = pulisci_cache(protetti=set(clip_paths.values()))
    if liberati:
        _log(f"  -> Cache pruned: {liberati:.0f} MB freed (cap {os.environ.get('MAX_CACHE_MB', '2000')} MB)")
    if not clip_paths:
        msg = "No clips downloaded — pipeline aborted"
        _log(f"  ERROR: {msg}")
        notify_error(msg)
        raise RuntimeError(msg)

    # ── MONTAGGIO ───────────────────────────────────────────────────────────
    _check_abort()
    _segna_step("montaggio")
    _log("[5/7] Montage — rendering video (5-15 min)...")
    # guardia disco: il render riempie output/ di file temporanei. Se lo spazio
    # e' poco, prova a liberare la cache, altrimenti aborta con messaggio chiaro
    # invece di crashare a meta' rendering (OSError 28: No space left on device).
    pulisci_temp_render("output")
    try:
        assicura_spazio(work_dir="output", protetti=set(clip_paths.values()))
    except RuntimeError as e:
        _log(f"  ✗ {e}")
        notify_error(str(e))
        raise
    _log(f"  -> Disk space: {spazio_libero_gb('output'):.1f} GB free")
    if "montage" in cp["steps"] and os.path.exists(VIDEO_PATH):
        _log(f"  -> Resumed from checkpoint: {VIDEO_PATH}")
    else:
        notify_step("rendering", "Rendering video (5-15 min)...")

        # progresso su Telegram a 25/50/75% e in state.json (per /status):
        # senza, durante il render l'utente resta 15 minuti al buio
        _soglie_notifica = [25, 50, 75]

        def _avanzamento(pct, eta):
            _segna_step("montaggio", pct)
            if _soglie_notifica and pct >= _soglie_notifica[0]:
                while _soglie_notifica and pct >= _soglie_notifica[0]:
                    _soglie_notifica.pop(0)
                notify_step("rendering", f"Rendering {pct}% — ETA {eta}")

        monta_video(
            AUDIO_PATH, list(clip_paths.keys()), clip_paths, VIDEO_PATH,
            mood=content.get("mood"),
            on_progress=_avanzamento,
            captions_text=content.get("script"),
            strategy=strategy,
            visual_segments=content.get("visual_segments"),
        )
        cp["steps"].append("montage")
        _save_checkpoint(cp)
    _check_abort()
    size = os.path.getsize(VIDEO_PATH) // (1024 * 1024)
    _log(f"  -> Video saved: {VIDEO_PATH} ({size} MB)")

    # ── THUMBNAIL ───────────────────────────────────────────────────────────
    _segna_step("thumbnail")
    _log("[6/7] Thumbnail — generating with AI...")
    if "thumbnail" in cp["steps"] and os.path.exists(THUMB_PATH):
        _log(f"  -> Resumed from checkpoint: {THUMB_PATH}")
    else:
        notify_step("thumbnail", "Generating thumbnail with AI...")
        meta = content.get("_strategy_meta") or {}
        thumb_style = meta.get("thumbnail_style") or strategy.get("thumbnail_style")
        genera_thumbnail(
            content["title"], THUMB_PATH,
            mood=content.get("mood"),
            style=thumb_style,
            thumbnail_description=content.get("thumbnail_description"),
            thumbnail_phrase=content.get("thumbnail_phrase"),
            thumbnail_font_size=content.get("thumbnail_font_size"),
            strategy=strategy,
        )
        cp["steps"].append("thumbnail")
        _save_checkpoint(cp)
    _log(f"  -> Thumbnail saved: {THUMB_PATH}")

    # ── UPLOAD ──────────────────────────────────────────────────────────────
    _check_abort()
    _segna_step("upload")
    if dry_run:
        _segna_step("dry_run")
        _log("DRY RUN: upload skipped. Video and thumbnail are ready in output/.")
        _pulisci_status_pipeline()
        return
    _log("[7/7] Upload — publishing to YouTube...")

    # Generate subtitles from final narration before upload (quality gate requires them)
    srt_path = "output/sottotitoli.srt"
    try:
        from moduli.sottotitoli import prepare_srt
        prepare_srt(
            content.get("script", ""),
            srt_path,
            audio_path=AUDIO_PATH,
            video_path=VIDEO_PATH,
        )
        _log(f"  -> Subtitles ready: {srt_path}")
    except Exception as e:
        _log(f"  -> Caption generation failed: {e}")
        require_caps = os.environ.get("REQUIRE_CAPTIONS", "1").lower() not in {"0", "false", "no"}
        if require_caps:
            raise RuntimeError(f"Subtitles required but generation failed: {e}") from e

    from moduli.publish_gate import run_pre_publish_gate
    skip_gate = os.environ.get("SKIP_PUBLISH_GATE", "").lower() in {"1", "true", "yes"}
    if not skip_gate:
        gate_ok, gate_errors, gate_warnings = run_pre_publish_gate(
        content, topic,
        video_path=VIDEO_PATH,
        audio_path=AUDIO_PATH,
        thumb_path=THUMB_PATH,
        strategy=strategy,
        srt_path=srt_path,
        )
        for w in gate_warnings:
            _log(f"  -> Quality warning: {w}")
        if not gate_ok:
            msg = "Pre-publish quality gate failed: " + "; ".join(gate_errors[:5])
            _log(f"  ERROR: {msg}")
            notify_error(msg)
            raise RuntimeError(msg)

    publish_at = None
    schedule_decision = None
    if cp.get("video_id"):
        video_id = cp["video_id"]
        publish_label = cp.get("publish_time", "already scheduled")
        _log(f"  -> Upload already done (checkpoint): https://youtu.be/{video_id}")
    else:
        notify_step("upload", "Uploading to YouTube...")
        run_index = _runs_today(state)
        immediate = bool(state.get("publish_immediately"))
        schedule_decision = None
        publish_at = None
        if not immediate:
            sched_cache = (_load_state().get("_scheduler_cache") or {})
            schedule_decision = resolve_publish_schedule(
                _load_state(),
                run_index=run_index,
                activity=sched_cache.get("activity"),
                geography=sched_cache.get("geography"),
                video_count=len(performance) if performance else None,
            )
            publish_at = schedule_decision.publish_at_utc
            log_schedule_decision(schedule_decision, log_fn=_log)
            fresh_sched = _load_state()
            fresh_sched["last_schedule_decision"] = schedule_decision.to_dict()
            fresh_sched["publish_timing"] = {
                **(fresh_sched.get("publish_timing") or {}),
                **schedule_decision.to_dict(),
            }
            _save_state(fresh_sched)
        publish_label = (
            "immediate"
            if immediate
            else schedule_decision.local_publish_label
            if schedule_decision
            else publish_at.strftime("%d/%m/%Y %H:%M UTC")
        )
        if immediate:
            _log("  -> Publishing immediately")
        else:
            _log(f"  -> Scheduled for: {publish_label}")
        video_id = pubblica_video(
            VIDEO_PATH,
            THUMB_PATH,
            content,
            publish_at,
            immediate=immediate,
            privacy_status=os.environ.get("YOUTUBE_IMMEDIATE_PRIVACY", "public") if immediate else "private",
        )
        cp["video_id"] = video_id
        cp["publish_time"] = publish_label
        _save_checkpoint(cp)
    _log(f"  -> OK https://youtu.be/{video_id}")

    # Upload captions (already generated for quality gate)
    if "captions" not in cp["steps"]:
        from moduli.pubblica import carica_sottotitoli
        from moduli.preferenze import carica as _carica_pref
        require_caps = os.environ.get("REQUIRE_CAPTIONS", "1").lower() not in {"0", "false", "no"}
        if srt_path and os.path.exists(srt_path):
            lingua = "it" if _carica_pref().get("lingua") == "italian" else "en"
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    carica_sottotitoli(video_id, srt_path, language=lingua)
                    cp["steps"].append("captions")
                    _save_checkpoint(cp)
                    _log("  -> Captions uploaded")
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    wait = 5 * (attempt + 1)
                    _log(f"  -> Captions upload failed (attempt {attempt + 1}/3): {e}")
                    if attempt < 2:
                        time.sleep(wait)
            if last_err:
                msg = f"Captions upload failed after retries: {last_err}"
                if require_caps:
                    raise RuntimeError(msg) from last_err
                _log(f"  -> Captions skipped: {last_err}")
        elif require_caps:
            raise RuntimeError("Subtitles required but SRT file is missing before upload")

    try:
        from moduli.channel_learning import record_scheduling_decision
        state_now = _load_state()
        timing = state_now.get("publish_timing") or {}
        pub_dt = publish_label
        record_scheduling_decision(
            video_id=video_id,
            scheduled_hour_utc=publish_at.hour if publish_at else datetime.now(timezone.utc).hour,
            scheduled_day=(publish_at.strftime("%A") if publish_at else datetime.now(timezone.utc).strftime("%A")),
            predicted_window=timing.get("best_time_window_utc"),
            topic_source=(content.get("_strategy_meta") or {}).get("topic_source", ""),
        )
    except Exception:
        pass

    notify_done(
        title=content["title"],
        video_id=video_id,
        publish_time=publish_label,
        thumb_path=THUMB_PATH,
        schedule_decision=schedule_decision.to_dict() if schedule_decision else None,
    )

    from moduli.strategia import registra_esito
    from moduli.topic_history import record_topic
    registra_esito(video_id, topic, content["title"], strategy, content=content, publish_time=publish_label)
    record_topic(topic, title=content["title"], video_id=video_id, source="pipeline")

    # Ricarica lo state più recente (il bot Telegram può aver scritto durante la pipeline)
    # e applica solo le modifiche prodotte dalla pipeline — evita lost-update.
    _segna_step("salvataggio")
    fresh = _load_state()
    recent = fresh.get("recent_topics", [])
    if topic:
        recent.insert(0, topic)
    fresh["recent_topics"] = recent[:10]
    fresh["last_run_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh["video_ids"] = ([video_id] + [v for v in fresh.get("video_ids", []) if v != video_id])[:20]
    fresh.pop("force_run", None)
    fresh.pop("publish_immediately", None)
    fresh.pop("abort_pipeline", None)
    _increment_runs_today(fresh)
    fresh.pop("pipeline_status", None)
    _save_state(fresh)
    _clear_checkpoint()
    _log("=== PIPELINE COMPLETE ===\n")


def _update_best_hours(state: dict, performance: list) -> None:
    """Pick best publish hours from analytics — con evidenza e confidenza campione."""
    from moduli.publish_optimization import recommend_publish_hours
    from moduli.performance import carica_profili

    videos_per_day = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    profiles = carica_profili()
    rec = recommend_publish_hours(
        profiles,
        videos_per_day=videos_per_day,
        current_hours=state.get("best_hours_utc"),
        performance_rows=performance,
    )
    hours = rec["hours"]
    state["best_hours_utc"] = hours
    state["publish_optimization"] = {
        "confidence": rec.get("confidence"),
        "video_count": rec.get("video_count"),
        "changed": rec.get("changed"),
        "reason": rec.get("reason"),
    }
    try:
        from moduli.publish_optimization import build_publish_strategy
        state["publish_timing"] = build_publish_strategy(profiles, state=state)
    except Exception:
        pass
    fresh = _load_state()
    if fresh.get("best_hours_utc") != hours:
        fresh["best_hours_utc"] = hours
        fresh["publish_optimization"] = state["publish_optimization"]
        _save_state(fresh)
    note = rec.get("reason", "")
    print(f"  Auto-scheduling: best hours set to {hours} ({note})", flush=True)


def _cleanup_stale_state() -> None:
    """Rimuove flag che non devono persistere tra riavvii."""
    state = _load_state()
    changed = False
    if state.pop("publish_immediately", None) is not None:
        _log("  -> Cleared stale publish_immediately from previous session")
        changed = True
    if state.pop("abort_pipeline", None) is not None:
        _log("  -> Cleared stale abort_pipeline from previous session")
        changed = True
    if state.pop("pipeline_status", None) is not None:
        _log("  -> Cleared stale pipeline_status from previous session")
        changed = True
    # rimuovi topic "…" o vuoti finiti in coda per errore
    queue = state.get("topic_queue", [])
    clean_queue = [t for t in queue if t.strip() and t.strip() not in ("…", "...")]
    if len(clean_queue) != len(queue):
        _log(f"  -> Removed {len(queue) - len(clean_queue)} invalid topics from queue")
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
    try:
        from moduli.topic_history import ensure_topic_history_seeded
        ensure_topic_history_seeded(state)
    except Exception as e:
        _log(f"  -> Topic history seed skipped: {e}")
    _log(f"  Topic queue after cleanup: {state.get('topic_queue', [])}")
    # manutenzione disco al boot: temp orfani + cache sotto soglia
    n_temp = pulisci_temp_render("output")
    if n_temp:
        _log(f"  -> Removed {n_temp} orphan temp render files")
    # proteggi le clip del checkpoint: servono se la run interrotta riprende
    _cp_boot = _load_checkpoint()
    liberati = pulisci_cache(protetti=set((_cp_boot.get("clip_paths") or {}).values()))
    if liberati:
        _log(f"  -> Cache pruned: {liberati:.0f} MB freed")
    _log(f"  Free disk space: {spazio_libero_gb('.'):.1f} GB")


def _shorts_slot_to_run(now: datetime) -> tuple[int, str] | None:
    """Return (slot_index, reason) to produce now, or None."""
    try:
        from moduli.shorts.state import load_state as load_shorts_state
        from moduli.shorts.scheduler import next_slot_to_produce

        ss = load_shorts_state()
        if ss.get("pipeline_status"):
            return None
        return next_slot_to_produce(now, state=ss)
    except Exception:
        return None


def main():
    from moduli.logsetup import setup as _log_su_file
    _log_su_file()
    _acquire_pid_lock()
    _log("=== YouTube AI Agent started ===")
    _cleanup_stale_state()

    state = _load_state()
    trigger_hours = _get_trigger_hours(state)
    vpd = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
    lf_on = long_form_enabled()
    _log(
        f"  Long-form: {'ON' if lf_on else 'OFF (LONG_FORM_ENABLED=false)'} | "
        f"Videos per day: {vpd} | Trigger hours: {trigger_hours} UTC"
    )
    _log(f"  Topics in queue: {len(state.get('topic_queue', []))}")
    now_boot = datetime.now(timezone.utc)
    if not lf_on:
        if state.get("force_run"):
            _log("  Long-form: ignoring pending force_run (pipeline disabled)")
            state.pop("force_run", None)
            state.pop("publish_immediately", None)
            _save_state(state)
    elif _long_form_catchup_pending(state, now_boot):
        _log("  Long-form: catching up missed window — will start on next tick")
    elif state.get("force_run"):
        _log("  Long-form: force_run pending — will start on next tick")
    try:
        from moduli.shorts.config import load_config
        from moduli.shorts.state import load_state as _shorts_state, runs_today as _shorts_done
        from moduli.shorts.scheduler import (
            production_hours_local,
            refresh_shorts_scheduler_cache,
            skipped_slots_today,
            slot_label,
        )

        scfg = load_config()
        ss = _shorts_state()
        if scfg.enabled and ss.get("enabled", True):
            try:
                ss = refresh_shorts_scheduler_cache(ss)
            except Exception:
                pass
            plan = ss.get("daily_slot_plan") or {}
            plan_src = plan.get("source", "fallback")
            hours = production_hours_local(scfg, state=ss)
            slots = ", ".join(
                f"{slot_label(i)} {h:02d}:00" for i, h in enumerate(hours[: scfg.per_day])
            )
            _log(
                f"  Shorts: {_shorts_done(ss)}/{scfg.per_day} today | "
                f"Production ({scfg.timezone}, {plan_src}): {slots}"
            )
            skipped = skipped_slots_today(config=scfg, state=ss)
            if skipped:
                labels = ", ".join(slot_label(s) for s in skipped)
                _log(f"  Shorts: skipped for today (no catch-up): {labels}")
    except Exception:
        pass

    bot_thread = start_bot()
    bot_restarts = 0

    last_attempt = None  # (data, ora) dell'ultimo trigger schedulato

    while True:
        state = _load_state()
        now = datetime.now(timezone.utc)

        # watchdog: senza bot l'agente resta vivo ma non più controllabile
        # da Telegram — riavvialo (max 3 volte, poi avvisa e arrenditi)
        if bot_thread is not None and not bot_thread.is_alive():
            if bot_restarts < 3:
                bot_restarts += 1
                _log(f"Telegram bot stopped — restarting ({bot_restarts}/3)...")
                notify_error(f"Telegram bot crashed — auto-restart ({bot_restarts}/3).")
                bot_thread = start_bot()
            else:
                _log("Telegram bot crashed too many times — stopping auto-restarts.")
                notify_error(
                    "Telegram bot crashed repeatedly: remote control disabled. "
                    "The pipeline keeps running; restart the agent to restore the bot."
                )
                bot_thread = None

        if now.minute == 0:
            trigger_hours = _get_trigger_hours(state)
            vpd = state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
            done = _runs_today(state)
            print(f"[{now.strftime('%Y-%m-%d %H:%M UTC')}] tick — {done}/{vpd} videos today — trigger: {trigger_hours}")

        if _should_run(state, now, last_attempt):
            forced = bool(state.get("force_run"))
            trigger_hours = _get_trigger_hours(state)
            catchup = (
                not forced
                and _runs_today(state) < state.get("videos_per_day", DEFAULT_VIDEOS_PER_DAY)
                and trigger_hours
                and now.hour > max(trigger_hours)
            )
            if not forced:
                if now.hour in trigger_hours:
                    last_attempt = (now.strftime("%Y-%m-%d"), now.hour)
                elif catchup:
                    last_attempt = (now.strftime("%Y-%m-%d"), "catchup")
            label = "FORCED" if forced else ("catch-up" if catchup else "scheduled")
            _log(f"Trigger ({label}) — starting pipeline")
            # Pulisci force_run PRIMA di partire: se la pipeline crasha,
            # il flag è già rimosso e il daemon non entra in loop infinito.
            state.pop("force_run", None)
            state.pop("abort_pipeline", None)
            _save_state(state)
            try:
                run_pipeline(state)
            except PipelineAbort:
                state = _load_state()
                state.pop("abort_pipeline", None)
                _save_state(state)
                notify_error("Pipeline aborted on Telegram request.")
            except Exception:
                err = traceback.format_exc()
                _log(err)
                last_line = err.strip().split("\n")[-1][:300]
                spiegazione = _spiega_errore(err)
                notify_error(
                    f"Crash allo step {_pipeline_step}\n\n"
                    f"{last_line}\n\n"
                    + (spiegazione or "Controlla i log. Usa /forza per riprovare.")
                )
            finally:
                _pulisci_status_pipeline()
            state = _load_state()

        if pick := _shorts_slot_to_run(now):
            slot, reason = pick
            from moduli.shorts.config import load_config as _scfg
            from moduli.shorts.scheduler import slot_label
            from zoneinfo import ZoneInfo

            scfg = _scfg()
            local = now.astimezone(ZoneInfo(scfg.timezone))
            _log(
                f"Shorts trigger — {slot_label(slot)} slot "
                f"({local.strftime('%H:%M')} {scfg.timezone}, {reason})"
            )
            try:
                from moduli.shorts.pipeline import run_shorts_slot
                run_shorts_slot(slot)
            except Exception:
                err = traceback.format_exc()
                _log(err)
                notify_error(f"Shorts batch crash:\n{err.strip().split(chr(10))[-1][:300]}")

        time.sleep(60)


if __name__ == "__main__":
    main()
