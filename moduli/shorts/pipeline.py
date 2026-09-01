"""Orchestrate one Short end-to-end with isolated error handling."""

from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone

from moduli.audio import genera_audio
from moduli.ffmpeg_utils import media_duration
from moduli.shorts.analytics import leggi_audience_geography, shorts_activity_signal, sync_shorts_profiles
from moduli.shorts.captions import generate_ass
from moduli.shorts.config import ShortsConfig, load_config
from moduli.shorts.content import generate_short_content
from moduli.shorts.history import record_entry
from moduli.shorts.learning import run_learning_update
from moduli.shorts.montage import extract_first_frame, monta_short
from moduli.shorts.profiles import upsert_profile
from moduli.shorts.quality import validate_short
from moduli.shorts.scheduler import compute_shorts_schedule
from moduli.shorts.state import (
    clear_pipeline_status,
    get_pending_upload,
    increment_runs_today,
    load_state,
    record_failure,
    record_today_short,
    save_pending_upload,
    save_state,
    set_pipeline_status,
)
from moduli.shorts.topics import plan_daily_batch
from moduli.shorts.visuals import acquire_segment_clips


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] [shorts] {msg}", flush=True)


def _paths(cfg: ShortsConfig, slot: int, date_str: str) -> dict:
    base = cfg.output_dir
    os.makedirs(base, exist_ok=True)
    stem = f"short_{slot}_{date_str}"
    return {
        "audio": os.path.join(base, f"{stem}.mp3"),
        "ass": os.path.join(base, f"{stem}.ass"),
        "video": os.path.join(base, f"{stem}.mp4"),
        "thumb": os.path.join(base, f"{stem}_thumb.jpg"),
        "srt": os.path.join(base, f"{stem}.srt"),
    }


def _generate_audio(script: str, path: str, cfg: ShortsConfig) -> None:
    from moduli.audio import _load_voice, _normalize_voice, genera_audio

    voice = _normalize_voice(cfg.tts_voice) if cfg.tts_voice else _load_voice()
    genera_audio(script, path, voice=voice)


def _do_short_upload(
    slot_index: int,
    paths: dict,
    content: dict,
    concept: dict,
    *,
    config: ShortsConfig,
    activity: dict | None,
    geography: dict | None,
    profiles_count: int,
) -> dict:
    """Upload a rendered Short and record success metadata."""
    from moduli.pubblica import pubblica_short
    from moduli.notifiche import notify_shorts_done

    cfg = config
    decision = compute_shorts_schedule(
        slot_index,
        activity=activity,
        geography=geography,
        profiles_count=profiles_count,
        config=cfg,
        producing_now=True,
    )

    set_pipeline_status("upload", slot_index)
    if not os.path.exists(paths.get("thumb", "")):
        extract_first_frame(paths["video"], paths["thumb"], cfg.width, cfg.height)

    metadati = {
        "title": content["title"],
        "description": content.get("description", ""),
        "tags": content.get("tags") or [],
        "hashtags": content.get("hashtags") or ["#Shorts"],
    }
    save_pending_upload(slot_index, paths, content, concept, decision.to_dict())
    video_id = pubblica_short(
        paths["video"],
        paths["thumb"],
        metadati,
        publish_at=decision.publish_at_utc,
    )

    duration = media_duration(paths["video"])
    record_entry(
        topic=concept.get("topic", ""),
        angle=content.get("angle", concept.get("angle", "")),
        hook=content.get("hook", ""),
        title=content["title"],
        script=content.get("script", ""),
        key_claims=content.get("key_claims"),
        source_type=content.get("source_type", concept.get("source_type", "")),
        source_topic=concept.get("source_topic", ""),
        source_longform_video_id=concept.get("source_longform_video_id", ""),
        video_id=video_id,
        duration_seconds=duration,
    )
    upsert_profile({
        "video_id": video_id,
        "title": content["title"],
        "published_at": decision.youtube_publish_at,
        "content_type": "short",
        "content_metadata": {
            "topic": concept.get("topic"),
            "angle": content.get("angle"),
            "hook": content.get("hook"),
            "hook_type": (content.get("hook") or "")[:40],
            "source_type": concept.get("source_type"),
        },
        "metrics": {"views": 0, "duration_seconds": duration},
    })

    result = {
        "video_id": video_id,
        "title": content["title"],
        "slot": slot_index,
        "schedule": decision.to_dict(),
        "duration": duration,
    }
    record_today_short(result)
    notify_shorts_done(content["title"], video_id, decision.to_dict())
    _log(f"Slot {slot_index}: published {video_id}")
    return result


def run_single_short(
    concept: dict,
    slot_index: int,
    *,
    config: ShortsConfig | None = None,
    activity: dict | None = None,
    geography: dict | None = None,
    profiles_count: int = 0,
    retry: bool = True,
) -> dict | None:
    """Produce and upload one Short. Returns result dict or None on failure."""
    cfg = config or load_config()
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    paths = _paths(cfg, slot_index, date_str)

    try:
        pending = get_pending_upload(slot_index)
        if pending:
            _log(f"Slot {slot_index}: resuming upload (video already rendered)")
            return _do_short_upload(
                slot_index,
                pending["paths"],
                pending["content"],
                pending["concept"],
                config=cfg,
                activity=activity,
                geography=geography,
                profiles_count=profiles_count,
            )

        set_pipeline_status("content", slot_index)
        _log(f"Slot {slot_index}: generating content for '{concept.get('topic', '')[:50]}'")
        content = generate_short_content(concept, config=cfg)

        set_pipeline_status("audio", slot_index)
        _log(f"Slot {slot_index}: TTS")
        _generate_audio(content["script"], paths["audio"], cfg)
        audio_dur = media_duration(paths["audio"])

        set_pipeline_status("visuals", slot_index)
        segments = acquire_segment_clips(content.get("visual_segments") or [], config=cfg)

        set_pipeline_status("captions", slot_index)
        generate_ass(
            content["script"],
            audio_dur,
            paths["ass"],
            width=cfg.width,
            height=cfg.height,
            font_size=cfg.caption_font_size,
            hook_words=content.get("hook", ""),
        )

        set_pipeline_status("render", slot_index)
        _log(f"Slot {slot_index}: rendering 9:16")
        monta_short(paths["audio"], segments, paths["ass"], paths["video"], config=cfg)

        ok, errors = validate_short(
            content=content,
            concept=concept,
            audio_path=paths["audio"],
            video_path=paths["video"],
            ass_path=paths["ass"],
            segments=segments,
            config=cfg,
        )
        if not ok:
            if retry:
                _log(f"Slot {slot_index}: quality gate failed, retrying once: {errors}")
                return run_single_short(
                    concept, slot_index,
                    config=cfg, activity=activity, geography=geography,
                    profiles_count=profiles_count, retry=False,
                )
            raise ValueError(f"Quality gate: {'; '.join(errors)}")

        return _do_short_upload(
            slot_index,
            paths,
            content,
            concept,
            config=cfg,
            activity=activity,
            geography=geography,
            profiles_count=profiles_count,
        )

    except Exception as e:
        record_failure(slot_index, str(e), concept)
        _log(f"Slot {slot_index} FAILED: {e}\n{traceback.format_exc()[-500:]}")
        return None


def run_shorts_slot(slot_index: int | None = None, *, dry_run: bool = False) -> dict:
    """
    Produce and upload ONE Short for the current daily slot.
    Never raises to caller.
    """
    cfg = load_config()
    state = load_state()

    if not cfg.enabled or not state.get("enabled", True):
        _log("Shorts disabled — skipping")
        return {"skipped": True, "reason": "disabled"}

    from moduli.shorts.state import runs_today
    from moduli.shorts.scheduler import should_produce_short_now, slot_label

    done = runs_today(state)
    if done >= cfg.per_day:
        _log("Daily Shorts quota already met")
        return {"skipped": True, "reason": "quota_met"}

    if slot_index is None:
        slot_index = done
    label = slot_label(slot_index)
    _log(f"=== SHORTS {label.upper()} SLOT ({slot_index + 1}/{cfg.per_day}) ===")

    try:
        profiles = sync_shorts_profiles()
        activity = shorts_activity_signal(profiles)
        geography = leggi_audience_geography()
        state["_scheduler_cache"] = {"activity": activity, "geography": geography}
        save_state(state)
    except Exception as e:
        _log(f"Analytics prefetch failed (using fallback): {e}")
        profiles = []
        activity = None
        geography = None

    concepts = plan_daily_batch(count=1, config=cfg)
    if not concepts:
        _log("No concept planned — aborting slot")
        record_failure(slot_index, "no concept planned", None)
        return {"success": None, "failure": {"slot": slot_index, "reason": "no_concepts"}}

    if dry_run:
        return {"dry_run": True, "slot": slot_index, "concepts": concepts}

    result = run_single_short(
        concepts[0],
        slot_index,
        config=cfg,
        activity=activity,
        geography=geography,
        profiles_count=len(profiles),
    )

    if result:
        increment_runs_today()
        try:
            run_learning_update()
        except Exception as e:
            _log(f"Learning update failed: {e}")
        state = load_state()
        state["last_batch_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        decisions = list(state.get("last_schedule_decisions") or [])
        if result.get("schedule"):
            decisions.append(result["schedule"])
        state["last_schedule_decisions"] = decisions[-10:]
        save_state(state)
        clear_pipeline_status()
        _log(f"=== SHORTS {label.upper()} DONE: {result.get('video_id')} ===")
        return {"success": result, "failure": None}

    clear_pipeline_status()
    _log(f"=== SHORTS {label.upper()} FAILED ===")
    return {"success": None, "failure": {"slot": slot_index, "concept": concepts[0].get("topic", "")}}


def run_shorts_batch(*, dry_run: bool = False) -> dict:
    """
    Legacy batch entry — runs only the next pending slot (not all 3 at once).
    Prefer run_shorts_slot() from the daemon.
    """
    from moduli.shorts.scheduler import should_produce_short_now

    slot = should_produce_short_now()
    if slot is None:
        from moduli.shorts.state import runs_today
        slot = runs_today(load_state())
    return run_shorts_slot(slot, dry_run=dry_run)
