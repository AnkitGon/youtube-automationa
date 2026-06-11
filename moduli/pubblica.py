import os
from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moduli.google_auth import get_credentials

DEFAULT_PUBLISH_HOURS = [20]

# smart publish spreads per number of videos/day
_PUBLISH_SPREADS = {
    1: [20],
    2: [14, 20],
    3: [10, 15, 20],
    4: [9, 13, 17, 21],
    5: [8, 11, 14, 17, 20],
}


def calcola_publish_slots(state: dict, run_index: int = 0) -> datetime:
    """Return the publish datetime for the run_index-th video of today."""
    now = datetime.now(timezone.utc)

    # explicit publish_hours_utc overrides everything
    hours = state.get("publish_hours_utc")
    if not hours and state.get("auto_scheduling"):
        hours = state.get("best_hours_utc")
    if not hours:
        vpd = state.get("videos_per_day", 1)
        hours = _PUBLISH_SPREADS.get(vpd, DEFAULT_PUBLISH_HOURS)

    hour = hours[run_index % len(hours)]
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _next_best_slot() -> datetime:
    from moduli.state_io import load_state
    return calcola_publish_slots(load_state(), 0)


def _get_youtube():
    return build("youtube", "v3", credentials=get_credentials())


def pubblica_video(
    video_path: str,
    thumbnail_path: str,
    metadati: dict,
    publish_at: datetime = None,
    immediate: bool = False,
    privacy_status: str = "private",
) -> str:
    youtube = _get_youtube()
    if publish_at is None and not immediate:
        publish_at = _next_best_slot()

    status_body = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": False,
    }
    if not immediate:
        status_body["publishAt"] = publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")

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

    media = MediaFileUpload(video_path, chunksize=10 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    if immediate:
        print(f"Uploading video... publishing immediately as {privacy_status}")
    else:
        print(f"Uploading video... scheduled for {publish_at.strftime('%Y-%m-%d %H:%M UTC')}")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"Upload complete: https://youtu.be/{video_id}")

    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path)
        ).execute()
    except Exception as e:
        print(f"  Thumbnail skip (account non verificato su YouTube): {e}")

    return video_id


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
