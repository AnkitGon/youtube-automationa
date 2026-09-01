"""Shorts-specific analytics sync."""

from __future__ import annotations

from datetime import date, timedelta

from moduli.shorts.profiles import load_profiles, upsert_profile


def sync_shorts_profiles(*, max_videos: int = 30) -> list[dict]:
    """
    Refresh metrics for known Shorts profiles and discover new Short uploads <=60s.
    Never raises.
    """
    try:
        return _sync_impl(max_videos=max_videos)
    except Exception as e:
        print(f"[shorts/analytics] sync failed: {e}", flush=True)
        return load_profiles()


def _sync_impl(*, max_videos: int = 30) -> list[dict]:
    from moduli.google_auth import get_credentials
    from googleapiclient.discovery import build
    from moduli.analytics import _parse_duration_iso, _query_video_analytics

    creds = get_credentials()
    yt = build("youtube", "v3", credentials=creds)
    yta = build("youtubeAnalytics", "v2", credentials=creds)

    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = (
        yt.playlistItems()
        .list(part="contentDetails,snippet", playlistId=uploads, maxResults=max_videos)
        .execute()
        .get("items", [])
    )
    if not items:
        return load_profiles()

    video_ids = [i["contentDetails"]["videoId"] for i in items]
    videos = (
        yt.videos()
        .list(part="snippet,statistics,contentDetails", id=",".join(video_ids))
        .execute()
        .get("items", [])
    )

    known = {p["video_id"]: p for p in load_profiles()}
    updated = []

    for v in videos:
        vid = v["id"]
        dur = _parse_duration_iso(v.get("contentDetails", {}).get("duration", "PT0S"))
        # Treat <=60s as Short candidate
        if dur > 60:
            continue

        stats = v.get("statistics", {})
        ana = _query_video_analytics(yta, vid)
        profile = known.get(vid) or {
            "video_id": vid,
            "content_type": "short",
            "title": v["snippet"].get("title", ""),
            "published_at": v["snippet"].get("publishedAt", ""),
        }
        profile["metrics"] = {
            "views": int(stats.get("viewCount") or ana.get("views") or 0),
            "likes": int(stats.get("likeCount") or 0),
            "comments": int(stats.get("commentCount") or 0),
            "avg_view_duration_seconds": float(ana.get("avg_view_duration_seconds") or 0),
            "avg_view_percentage": float(ana.get("avg_view_percentage") or 0),
            "subscribers_gained": ana.get("subscribers_gained"),
            "duration_seconds": dur,
        }
        if dur > 0 and profile["metrics"]["avg_view_duration_seconds"]:
            profile["metrics"]["pct_viewed"] = round(
                profile["metrics"]["avg_view_duration_seconds"] / dur * 100, 1
            )
        profile["content_metadata"] = profile.get("content_metadata") or {}
        upsert_profile(profile)
        updated.append(profile)

    return load_profiles()


def shorts_activity_signal(profiles: list[dict] | None = None) -> dict:
    """Build scheduling activity buckets from Shorts publish performance."""
    profiles = profiles or load_profiles()
    if not profiles:
        return {"has_data": False, "buckets": [], "total_views": 0}

    hour_views: dict[int, int] = {}
    day_views: dict[int, int] = {}
    total = 0
    _py_to_yt = {6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7}

    for p in profiles:
        views = int((p.get("metrics") or {}).get("views") or 0)
        if views <= 0:
            continue
        total += views
        pub = p.get("published_at") or ""
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            hour_views[dt.hour] = hour_views.get(dt.hour, 0) + views
            yt_dow = _py_to_yt[dt.weekday()]
            day_views[yt_dow] = day_views.get(yt_dow, 0) + views
        except Exception:
            continue

    if not hour_views:
        return {"has_data": False, "buckets": [], "total_views": 0}

    best_hour = max(hour_views, key=hour_views.get)
    buckets = []
    for yt_dow, views in sorted(day_views.items(), key=lambda x: -x[1]):
        buckets.append({
            "day_of_week": yt_dow,
            "hour": best_hour,
            "views": views,
            "source": "shorts_profiles",
        })

    return {
        "has_data": True,
        "buckets": buckets,
        "total_views": total,
        "signal": "shorts_publish_performance",
    }


def leggi_audience_geography(*, days: int = 28) -> dict:
    """Reuse channel geography for Shorts scheduling timezone."""
    from moduli.analytics import leggi_audience_geography as _geo
    return _geo(days=days)
