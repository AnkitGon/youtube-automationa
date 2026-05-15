from googleapiclient.discovery import build
from moduli.google_auth import get_credentials
from datetime import datetime, timezone, date


def leggi_performance(n_video: int = 5) -> list[dict]:
    """Return performance data for the last n_video uploads."""
    creds = get_credentials()
    yt = build("youtube", "v3", credentials=creds)
    yta = build("youtubeAnalytics", "v2", credentials=creds)

    ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
    items_ch = ch_resp.get("items", [])
    if not items_ch:
        return []
    uploads = items_ch[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    items = (
        yt.playlistItems()
        .list(part="contentDetails", playlistId=uploads, maxResults=n_video)
        .execute()
        .get("items", [])
    )

    if not items:
        return []

    video_ids = [i["contentDetails"]["videoId"] for i in items]

    videos_resp = (
        yt.videos()
        .list(part="snippet,statistics,contentDetails", id=",".join(video_ids))
        .execute()
        .get("items", [])
    )

    results = []
    for v in videos_resp:
        vid = v["id"]
        stats = v.get("statistics", {})

        try:
            analytics = (
                yta.reports()
                .query(
                    ids="channel==MINE",
                    startDate="2020-01-01",
                    endDate=date.today().isoformat(),
                    metrics="views,averageViewDuration,averageViewPercentage,estimatedMinutesWatched,impressions,impressionClickThroughRate",
                    filters=f"video=={vid}",
                )
                .execute()
            )
            row = analytics.get("rows", [[0, 0, 0, 0, 0, 0]])[0]
            views_ana, avg_duration, avg_view_pct, minutes_watched, impressions, ctr = row
        except Exception as e:
            print(f"[analytics] errore query video {vid}: {e}")
            views_ana, avg_duration, avg_view_pct, minutes_watched, impressions, ctr = 0, 0, 0, 0, 0, 0
        # CTR reale: API lo ritorna come frazione (0.05 = 5%) → moltiplica
        if ctr:
            ctr_real = ctr * 100
        elif impressions and views_ana:
            ctr_real = (views_ana / impressions) * 100
        else:
            ctr_real = 0

        # parsing duration ISO8601 (PT8M30S -> 510 sec)
        import re as _re
        dur_str = v.get("contentDetails", {}).get("duration", "PT0S")
        m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur_str)
        if m:
            h, mi, s = (int(g) if g else 0 for g in (m.group(1), m.group(2), m.group(3)))
            duration_seconds = h * 3600 + mi * 60 + s
        else:
            duration_seconds = 0

        results.append({
            "video_id": vid,
            "title": v["snippet"]["title"],
            "published_at": v["snippet"].get("publishedAt", ""),
            "published_hour_utc": _published_hour(v["snippet"].get("publishedAt", "")),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "duration_seconds": duration_seconds,
            "avg_view_duration_seconds": avg_duration,
            "avg_view_percentage": round(avg_view_pct, 2) if avg_view_pct else 0,
            "estimated_minutes_watched": minutes_watched,
            "impressions": impressions,
            "ctr_percent": round(ctr_real, 2),
            "ctr": ctr,
        })

    return results


def _published_hour(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).hour
    except Exception:
        return None
