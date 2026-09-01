import os
import ssl
import time
from datetime import datetime, timezone
from http.client import RemoteDisconnected

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moduli.google_auth import get_credentials
from moduli.publish_scheduler import (
    compute_publish_schedule,
    format_youtube_publish_at,
    validate_publish_timestamp,
    ScheduleDecision,
)

DEFAULT_PUBLISH_HOURS = [20]

# smart publish spreads per number of videos/day (legacy fallback hours in audience TZ)
_PUBLISH_SPREADS = {
    1: [20],
    2: [14, 20],
    3: [10, 15, 20],
    4: [9, 13, 17, 21],
    5: [8, 11, 14, 17, 20],
}


def calcola_publish_slots(
    state: dict,
    run_index: int = 0,
    *,
    activity: dict | None = None,
    geography: dict | None = None,
    video_count: int | None = None,
) -> datetime:
    """Return the publish datetime (UTC, timezone-aware) for this run."""
    decision = resolve_publish_schedule(
        state,
        run_index=run_index,
        activity=activity,
        geography=geography,
        video_count=video_count,
    )
    return decision.publish_at_utc


def resolve_publish_schedule(
    state: dict,
    run_index: int = 0,
    *,
    activity: dict | None = None,
    geography: dict | None = None,
    video_count: int | None = None,
) -> ScheduleDecision:
    """Full scheduling decision — stored in state and used for Telegram/logging."""
    cached = state.get("_scheduler_cache") or {}
    if activity is None:
        activity = cached.get("activity")
    if geography is None:
        geography = cached.get("geography")

    decision = compute_publish_schedule(
        state,
        run_index=run_index,
        activity=activity,
        geography=geography,
        video_count=video_count,
    )
    return decision


def _next_best_slot() -> datetime:
    from moduli.state_io import load_state
    return calcola_publish_slots(load_state(), 0)


def _get_youtube():
    return build("youtube", "v3", credentials=get_credentials())


_RETRYABLE_UPLOAD = (
    ssl.SSLEOFError,
    ssl.SSLError,
    ConnectionError,
    BrokenPipeError,
    RemoteDisconnected,
    OSError,
)


def _is_retryable_upload_error(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE_UPLOAD):
        return True
    try:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError):
            return exc.resp.status in (500, 502, 503, 504)
    except Exception:
        pass
    return False


def _resumable_video_upload(youtube, body: dict, video_path: str) -> dict:
    """Upload with retries — handles transient SSL/network drops mid-chunk."""
    max_attempts = max(1, int(os.environ.get("YOUTUBE_UPLOAD_RETRIES", "4")))
    chunk_mb = max(1, int(os.environ.get("YOUTUBE_UPLOAD_CHUNK_MB", "8")))
    chunksize = chunk_mb * 1024 * 1024
    last_err: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            media = MediaFileUpload(video_path, chunksize=chunksize, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"  Upload {int(status.progress() * 100)}%")
            return response
        except Exception as e:
            last_err = e
            if not _is_retryable_upload_error(e) or attempt >= max_attempts:
                raise
            wait = min(30, 5 * attempt)
            print(
                f"  Upload error ({type(e).__name__}) — retry {attempt}/{max_attempts} "
                f"in {wait}s...",
                flush=True,
            )
            time.sleep(wait)
    raise last_err or RuntimeError("upload failed")


def pubblica_video(
    video_path: str,
    thumbnail_path: str,
    metadati: dict,
    publish_at: datetime = None,
    immediate: bool = False,
    privacy_status: str = "private",
    *,
    content_label: str = "video",
) -> str:
    youtube = _get_youtube()
    if publish_at is None and not immediate:
        publish_at = _next_best_slot()

    status_body = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": False,
    }
    if not immediate:
        publish_at = validate_publish_timestamp(publish_at)
        status_body["publishAt"] = format_youtube_publish_at(publish_at)

    body = {
        "snippet": {
            "title": metadati["title"],
            "description": metadati["description"],
            "tags": metadati["tags"],
            "categoryId": "28",  # Science & Technology
            "defaultLanguage": "en",
        },
        "status": status_body,
    }

    if immediate:
        print(f"Uploading {content_label}... publishing immediately as {privacy_status}")
    else:
        print(
            f"Uploading {content_label}... scheduled for {format_youtube_publish_at(publish_at)} "
            f"({publish_at.strftime('%Y-%m-%d %H:%M UTC')})"
        )
    response = _resumable_video_upload(youtube, body, video_path)

    video_id = response["id"]
    returned_publish = (response.get("status") or {}).get("publishAt")
    if not immediate:
        if returned_publish:
            print(f"  YouTube confirmed publishAt: {returned_publish}")
        else:
            print("  WARNING: YouTube did not return publishAt — verify schedule in Studio")
    if content_label == "Short":
        print(f"Short upload complete: https://youtube.com/shorts/{video_id}")
    else:
        print(f"Upload complete: https://youtu.be/{video_id}")

    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path)
        ).execute()
    except Exception as e:
        print(f"  Thumbnail skip (account non verificato su YouTube): {e}")

    return video_id


def pubblica_short(
    video_path: str,
    thumbnail_path: str,
    metadati: dict,
    publish_at: datetime = None,
    immediate: bool = False,
    privacy_status: str = "private",
) -> str:
    """Upload a YouTube Short — thin wrapper around pubblica_video."""
    desc = (metadati.get("description") or "").strip()
    hashtags = metadati.get("hashtags") or ["#Shorts"]
    if "#Shorts" not in desc and "#shorts" not in desc.lower():
        tag_line = " ".join(hashtags[:5])
        desc = f"{desc}\n\n{tag_line}".strip() if desc else tag_line

    # Ensure thumbnail exists (required by pubblica_video)
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        from moduli.shorts.montage import extract_first_frame
        thumbnail_path = video_path.replace(".mp4", "_thumb.jpg")
        extract_first_frame(video_path, thumbnail_path)

    meta = {
        "title": metadati["title"],
        "description": desc,
        "tags": metadati.get("tags") or [],
    }
    return pubblica_video(
        video_path,
        thumbnail_path,
        meta,
        publish_at=publish_at,
        immediate=immediate,
        privacy_status=privacy_status,
        content_label="Short",
    )


def carica_sottotitoli(video_id: str, srt_path: str, language: str = "en",
                       name: str = "") -> None:
    """Carica una traccia sottotitoli SRT sul video.

    Richiede lo scope youtube.force-ssl: i token creati prima dell'aggiunta
    dello scope falliscono qui — basta cancellare token.json e rifare login."""
    youtube = _get_youtube()
    youtube.captions().insert(
        part="snippet",
        body={"snippet": {"videoId": video_id, "language": language,
                          "name": name, "isDraft": False}},
        media_body=MediaFileUpload(srt_path, mimetype="application/octet-stream"),
    ).execute()


def aggiorna_video(video_id: str, title: str = None, description: str = None,
                   tags: list = None, thumbnail_path: str = None) -> dict:
    youtube = _get_youtube()
    results = {}

    if title or description or tags is not None:
        resp = youtube.videos().list(part="snippet", id=video_id).execute()
        if not resp.get("items"):
            raise ValueError(f"Video {video_id} non trovato")
        snippet = resp["items"][0]["snippet"]
        if title:
            snippet["title"] = title
        if description:
            snippet["description"] = description
        if tags is not None:
            snippet["tags"] = tags
        youtube.videos().update(
            part="snippet",
            body={"id": video_id, "snippet": snippet}
        ).execute()
        results["updated"] = True

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            results["thumbnail"] = True
        except Exception as e:
            results["thumbnail_error"] = str(e)

    return results
