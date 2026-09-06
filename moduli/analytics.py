from googleapiclient.discovery import build
from moduli.google_auth import get_credentials
from datetime import datetime, timezone, date, timedelta
import re


_ANALYTICS_METRICS_PRIMARY = (
    "views,averageViewDuration,averageViewPercentage,estimatedMinutesWatched,"
    "impressions,impressionClickThroughRate"
)
_ANALYTICS_METRICS_EXTENDED = (
    "views,averageViewDuration,averageViewPercentage,estimatedMinutesWatched,"
    "impressions,impressionClickThroughRate,shares,subscribersGained"
)
_ANALYTICS_METRICS_BASIC = (
    "views,averageViewDuration,averageViewPercentage,estimatedMinutesWatched"
)


def _parse_duration_iso(dur_str: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur_str or "PT0S")
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in (m.group(1), m.group(2), m.group(3)))
    return h * 3600 + mi * 60 + s


def _published_hour(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).hour
    except Exception:
        return None


def _published_day(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%A")
    except Exception:
        return None


def _query_video_analytics(yta, video_id: str) -> dict:
    """Query analytics con fallback se metriche estese non disponibili."""
    base = {
        "views": 0,
        "avg_view_duration_seconds": 0,
        "avg_view_percentage": 0,
        "estimated_minutes_watched": 0,
        "impressions": 0,
        "ctr": 0,
        "shares": None,
        "subscribers_gained": None,
    }
    for metrics in (_ANALYTICS_METRICS_EXTENDED, _ANALYTICS_METRICS_PRIMARY, _ANALYTICS_METRICS_BASIC):
        try:
            analytics = (
                yta.reports()
                .query(
                    ids="channel==MINE",
                    startDate="2020-01-01",
                    endDate=date.today().isoformat(),
                    metrics=metrics,
                    filters=f"video=={video_id}",
                )
                .execute()
            )
            headers = [h["name"] for h in analytics.get("columnHeaders", [])]
            row = analytics.get("rows", [[0] * len(headers)])[0]
            data = dict(zip(headers, row))
            base["views"] = int(data.get("views") or 0)
            base["avg_view_duration_seconds"] = float(data.get("averageViewDuration") or 0)
            base["avg_view_percentage"] = float(data.get("averageViewPercentage") or 0)
            base["estimated_minutes_watched"] = float(data.get("estimatedMinutesWatched") or 0)
            base["impressions"] = int(data.get("impressions") or 0)
            base["ctr"] = float(data.get("impressionClickThroughRate") or 0)
            if "shares" in data:
                base["shares"] = int(data["shares"]) if data["shares"] is not None else None
            if "subscribersGained" in data:
                sg = data["subscribersGained"]
                base["subscribers_gained"] = int(sg) if sg is not None else None
            return base
        except Exception as e:
            if metrics == _ANALYTICS_METRICS_BASIC:
                print(f"[analytics] video {video_id} query failed: {e}", flush=True)
    return base


def _query_retention_at_seconds(
    yta, video_id: str, duration_seconds: int, at_seconds: int = 30
) -> float | None:
    """
    Retention stimata ai primi N secondi via audienceWatchRatio (se API disponibile).
  Ritorna percentuale 0-100 o None.
    """
    if not duration_seconds or duration_seconds < at_seconds:
        return None
    target_ratio = min(0.99, at_seconds / float(duration_seconds))
    try:
        resp = (
            yta.reports()
            .query(
                ids="channel==MINE",
                startDate="2020-01-01",
                endDate=date.today().isoformat(),
                metrics="audienceWatchRatio",
                dimensions="elapsedVideoTimeRatio",
                filters=f"video=={video_id}",
                sort="elapsedVideoTimeRatio",
            )
            .execute()
        )
        rows = resp.get("rows") or []
        if not rows:
            return None
        best_ratio, best_watch = None, None
        for row in rows:
            ratio = float(row[0])
            watch = float(row[1])
            if best_watch is None or abs(ratio - target_ratio) < abs((best_ratio or 0) - target_ratio):
                best_ratio, best_watch = ratio, watch
        if best_watch is None:
            return None
        return round(best_watch * 100, 2)
    except Exception:
        return None


def leggi_performance(
    n_video: int = 5,
    *,
    profiles_hint: list[dict] | None = None,
) -> list[dict]:
    """
    Return performance data for the last n_video uploads.
    Non solleva mai — ritorna [] se API/token/quota non disponibili.
    Con profiles_hint salta query Analytics per video con metriche fresche in cache.
    """
    try:
        return _leggi_performance_impl(n_video, profiles_hint=profiles_hint)
    except Exception as e:
        print(f"[analytics] unavailable ({type(e).__name__}: {e})", flush=True)
        return []


def _profiles_map(profiles_hint: list[dict] | None) -> dict[str, dict]:
    if profiles_hint:
        return {p["video_id"]: p for p in profiles_hint if p.get("video_id")}
    try:
        from moduli.performance import carica_profili
        return {p["video_id"]: p for p in carica_profili() if p.get("video_id")}
    except Exception:
        return {}


def _metrics_from_profile(profile: dict, stats: dict, duration_seconds: int) -> dict:
    m = profile.get("metrics") or {}
    views = int(stats.get("viewCount") or m.get("views") or 0)
    return {
        "views": views,
        "avg_view_duration_seconds": float(m.get("avg_view_duration_seconds") or 0),
        "avg_view_percentage": float(m.get("avg_view_percentage") or 0),
        "estimated_minutes_watched": float(m.get("estimated_minutes_watched") or 0),
        "impressions": int(m.get("impressions") or 0),
        "ctr": float(m.get("ctr_percent") or 0) / 100.0 if m.get("ctr_percent") else 0,
        "shares": m.get("shares"),
        "subscribers_gained": m.get("subscribers_gained"),
        "retention_at_30s_percent": m.get("retention_at_30s_percent"),
    }


def _leggi_performance_impl(
    n_video: int = 5,
    *,
    profiles_hint: list[dict] | None = None,
) -> list[dict]:
    """Implementazione leggi_performance — può sollevare eccezioni API."""
    from moduli.analytics_cache import cache_ttl_minutes, is_metrics_fresh, is_retention_fresh

    creds = get_credentials()
    yt = build("youtube", "v3", credentials=creds)
    yta = build("youtubeAnalytics", "v2", credentials=creds)
    profiles_by_id = _profiles_map(profiles_hint)
    ttl = cache_ttl_minutes()
    skipped = 0

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
        profile = profiles_by_id.get(vid)
        published_at = v["snippet"].get("publishedAt", "")
        duration_seconds = _parse_duration_iso(
            v.get("contentDetails", {}).get("duration", "PT0S")
        )

        if profile and is_metrics_fresh(profile, ttl):
            ana = _metrics_from_profile(profile, stats, duration_seconds)
            skipped += 1
        else:
            ana = _query_video_analytics(yta, vid)

        views_ana = ana["views"]
        avg_duration = ana["avg_view_duration_seconds"]
        avg_view_pct = ana["avg_view_percentage"]
        minutes_watched = ana["estimated_minutes_watched"]
        impressions = ana["impressions"]
        ctr = ana["ctr"]

        if ctr:
            ctr_real = ctr * 100
        elif impressions and views_ana:
            ctr_real = (views_ana / impressions) * 100
        else:
            ctr_real = 0

        retention_30s = ana.get("retention_at_30s_percent")
        if retention_30s is None and profile and is_retention_fresh(profile):
            retention_30s = (profile.get("metrics") or {}).get("retention_at_30s_percent")
        if retention_30s is None:
            retention_30s = _query_retention_at_seconds(yta, vid, duration_seconds, at_seconds=30)

        retention_pct = (avg_duration / duration_seconds * 100) if duration_seconds else 0

        results.append({
            "video_id": vid,
            "title": v["snippet"]["title"],
            "published_at": published_at,
            "published_hour_utc": _published_hour(published_at),
            "published_day_utc": _published_day(published_at),
            "views": int(stats.get("viewCount", views_ana or 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "shares": ana.get("shares"),
            "subscribers_gained": ana.get("subscribers_gained"),
            "duration_seconds": duration_seconds,
            "avg_view_duration_seconds": avg_duration,
            "avg_view_percentage": round(avg_view_pct, 2) if avg_view_pct else 0,
            "retention_percent": round(retention_pct, 2),
            "retention_at_30s_percent": retention_30s,
            "estimated_minutes_watched": minutes_watched,
            "impressions": impressions,
            "ctr_percent": round(ctr_real, 2),
            "ctr": ctr,
        })

    if skipped:
        print(
            f"[analytics] {skipped}/{len(results)} video — metriche da cache profili "
            f"(TTL {ttl}m, niente query Analytics per video)",
            flush=True,
        )

    return results


def leggi_audience_activity(*, days: int = 28) -> dict:
    """
    Viewer activity by day-of-week and hour from YouTube Analytics.
    Returns structured buckets for the deterministic scheduler.
    Never raises.
    """
    try:
        return _leggi_audience_activity_impl(days=days)
    except Exception as e:
        print(f"[analytics] audience activity unavailable ({type(e).__name__}: {e})", flush=True)
        return {"has_data": False, "buckets": [], "total_views": 0, "error": str(e)}


def _leggi_audience_activity_impl(*, days: int = 28) -> dict:
    """
    Build audience activity buckets for the deterministic scheduler.

    Prefers YouTube's dayOfWeek+hour grid when available; otherwise falls back
    to weekday rollup + performance-hour hint.
    """
    hour_grid = leggi_audience_hour_grid(days=days)
    if hour_grid.get("has_data") and hour_grid.get("buckets"):
        buckets = hour_grid["buckets"][:40]
        return {
            "has_data": True,
            "buckets": buckets,
            "total_views": hour_grid.get("total_views", 0),
            "period_days": days,
            "signal": "dayOfWeek_hour_grid",
            "source": "dayOfWeek_hour",
        }

    import os

    yta = _analytics_client()
    end = date.today()
    start = end - timedelta(days=max(7, days))

    resp = (
        yta.reports()
        .query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="views",
            dimensions="day",
            sort="-views",
            maxResults=500,
        )
        .execute()
    )

    # YouTube dayOfWeek: Sunday=1 … Saturday=7
    _py_to_yt = {6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7}
    dow_views: dict[int, int] = {}
    total = 0
    for row in resp.get("rows") or []:
        day_str, views = row[0], int(row[1])
        total += views
        dt = date.fromisoformat(day_str)
        yt_dow = _py_to_yt[dt.weekday()]
        dow_views[yt_dow] = dow_views.get(yt_dow, 0) + views

    default_hour = 18
    try:
        default_hour = int(os.environ.get("DEFAULT_PUBLISH_TIME", "18:00").split(":")[0])
    except (ValueError, IndexError):
        pass

    hour_hint = default_hour
    signal = "daily_views_by_weekday"
    try:
        from moduli.performance import carica_profili
        from moduli.publish_optimization import analyze_publish_timing

        profiles = carica_profili()
        if profiles:
            analysis = analyze_publish_timing(profiles)
            evidenced = [
                r for r in (analysis.get("hour_rankings") or [])
                if r.get("evidence_ok") and r.get("sample_size", 0) >= 2
            ]
            if evidenced:
                hour_hint = int(evidenced[0]["hour_utc"])
                signal = "daily_views_plus_performance_hour"
    except Exception:
        pass

    buckets = []
    for yt_dow, views in dow_views.items():
        if views > 0:
            buckets.append({
                "day_of_week": yt_dow,
                "hour": hour_hint,
                "views": views,
                "day_name": _WEEKDAY_NAMES_YT.get(yt_dow, ""),
                "source": signal,
            })
    buckets.sort(key=lambda b: b["views"], reverse=True)

    return {
        "has_data": bool(buckets) and total > 0,
        "buckets": buckets,
        "total_views": total,
        "period_days": days,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "signal": signal,
    }


_WEEKDAY_NAMES_YT = {
    1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday",
    5: "Thursday", 6: "Friday", 7: "Saturday",
}


def _analytics_client():
    creds = get_credentials()
    return build("youtubeAnalytics", "v2", credentials=creds)


def _safe_channel_report(
    yta,
    *,
    metrics: str,
    dimensions: str,
    days: int = 28,
    filters: str = "",
    sort: str = "-views",
    max_results: int = 50,
) -> dict:
    """Run a channel report; return {has_data, rows, error} without raising."""
    end = date.today()
    start = end - timedelta(days=max(7, days))
    try:
        params = {
            "ids": "channel==MINE",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "metrics": metrics,
            "dimensions": dimensions,
            "sort": sort,
            "maxResults": max_results,
        }
        if filters:
            params["filters"] = filters
        resp = yta.reports().query(**params).execute()
        headers = [h["name"] for h in resp.get("columnHeaders", [])]
        rows = []
        for raw in resp.get("rows") or []:
            rows.append(dict(zip(headers, raw)))
        return {
            "has_data": bool(rows),
            "rows": rows,
            "period_days": days,
            "dimensions": dimensions,
            "metrics": metrics,
        }
    except Exception as e:
        return {"has_data": False, "rows": [], "error": str(e), "dimensions": dimensions}


def leggi_audience_hour_grid(*, days: int = 28) -> dict:
    """
    When viewers are on YouTube — day-of-week x hour grid (if API permits).
    Never raises.
    """
    try:
        yta = _analytics_client()
        report = _safe_channel_report(
            yta,
            metrics="views",
            dimensions="dayOfWeek,hour",
            days=days,
            sort="-views",
            max_results=200,
        )
        if not report.get("has_data"):
            return {"has_data": False, "buckets": [], "source": "dayOfWeek_hour", "error": report.get("error")}
        buckets = []
        total = 0
        for row in report["rows"]:
            views = int(float(row.get("views") or 0))
            if views <= 0:
                continue
            total += views
            dow = int(float(row.get("dayOfWeek") or 0))
            hour = int(float(row.get("hour") or 0))
            buckets.append({
                "day_of_week": dow,
                "hour": hour,
                "views": views,
                "day_name": _WEEKDAY_NAMES_YT.get(dow, ""),
                "source": "dayOfWeek_hour",
            })
        buckets.sort(key=lambda b: b["views"], reverse=True)
        return {
            "has_data": bool(buckets),
            "buckets": buckets,
            "total_views": total,
            "period_days": days,
            "source": "dayOfWeek_hour",
        }
    except Exception as e:
        return {"has_data": False, "buckets": [], "error": str(e)}


def leggi_traffic_sources(*, days: int = 28) -> dict:
    """How viewers find the channel. Never raises."""
    try:
        yta = _analytics_client()
        report = _safe_channel_report(
            yta,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            days=days,
            sort="-views",
        )
        if not report.get("has_data"):
            return {"has_data": False, "sources": [], "error": report.get("error")}
        sources = []
        total_views = 0
        for row in report["rows"]:
            views = int(float(row.get("views") or 0))
            total_views += views
            sources.append({
                "source_type": str(row.get("insightTrafficSourceType") or "UNKNOWN"),
                "views": views,
                "estimated_minutes_watched": round(float(row.get("estimatedMinutesWatched") or 0), 1),
            })
        return {"has_data": bool(sources), "sources": sources, "total_views": total_views, "period_days": days}
    except Exception as e:
        return {"has_data": False, "sources": [], "error": str(e)}


def leggi_audience_demographics(*, days: int = 28) -> dict:
    """Age/gender audience breakdown. Never raises."""
    try:
        yta = _analytics_client()
        report = _safe_channel_report(
            yta,
            metrics="viewerPercentage",
            dimensions="ageGroup,gender",
            days=days,
            sort="-viewerPercentage",
            max_results=30,
        )
        if not report.get("has_data"):
            return {"has_data": False, "segments": [], "error": report.get("error")}
        segments = []
        for row in report["rows"]:
            pct = float(row.get("viewerPercentage") or 0)
            if pct <= 0:
                continue
            segments.append({
                "age_group": str(row.get("ageGroup") or ""),
                "gender": str(row.get("gender") or ""),
                "viewer_percentage": round(pct, 2),
            })
        return {"has_data": bool(segments), "segments": segments, "period_days": days}
    except Exception as e:
        return {"has_data": False, "segments": [], "error": str(e)}


def leggi_subscriber_watch_behavior(*, days: int = 28) -> dict:
    """Watch time from subscribers vs non-subscribers. Never raises."""
    try:
        yta = _analytics_client()
        report = _safe_channel_report(
            yta,
            metrics="views,estimatedMinutesWatched,averageViewDuration",
            dimensions="subscribedStatus",
            days=days,
            sort="-views",
        )
        if not report.get("has_data"):
            return {"has_data": False, "segments": [], "error": report.get("error")}
        segments = []
        for row in report["rows"]:
            views = int(float(row.get("views") or 0))
            segments.append({
                "status": str(row.get("subscribedStatus") or "unknown"),
                "views": views,
                "estimated_minutes_watched": round(float(row.get("estimatedMinutesWatched") or 0), 1),
                "avg_view_duration_seconds": round(float(row.get("averageViewDuration") or 0), 1),
            })
        return {"has_data": bool(segments), "segments": segments, "period_days": days}
    except Exception as e:
        return {"has_data": False, "segments": [], "error": str(e)}


def leggi_monthly_audience(*, months: int = 6) -> dict:
    """Monthly views trend (proxy for monthly audience activity). Never raises."""
    try:
        yta = _analytics_client()
        end = date.today()
        raw_start = end - timedelta(days=max(30, months * 30))
        start = raw_start.replace(day=1)
        report = _safe_channel_report(
            yta,
            metrics="views,estimatedMinutesWatched",
            dimensions="month",
            days=(end - start).days,
            sort="month",
            max_results=months,
        )
        if not report.get("has_data"):
            return {"has_data": False, "months": [], "error": report.get("error")}
        months_rows = []
        for row in report["rows"]:
            months_rows.append({
                "month": str(row.get("month") or ""),
                "views": int(float(row.get("views") or 0)),
                "estimated_minutes_watched": round(float(row.get("estimatedMinutesWatched") or 0), 1),
            })
        return {"has_data": bool(months_rows), "months": months_rows}
    except Exception as e:
        return {"has_data": False, "months": [], "error": str(e)}


def leggi_channel_audience_bundle(*, days: int = 28) -> dict:
    """
    Fetch all optional channel-level audience reports once per analytics cycle.
    Skips unavailable metrics cleanly — never raises.
    """
    bundle = {
        "hour_grid": leggi_audience_hour_grid(days=days),
        "traffic_sources": leggi_traffic_sources(days=days),
        "demographics": leggi_audience_demographics(days=days),
        "subscriber_watch": leggi_subscriber_watch_behavior(days=days),
        "monthly": leggi_monthly_audience(),
        "geography": leggi_audience_geography(days=days),
    }
    available = [k for k, v in bundle.items() if isinstance(v, dict) and v.get("has_data")]
    bundle["reports_available"] = available
    return bundle


def leggi_audience_geography(*, days: int = 28) -> dict:
    """Top audience countries (and US provinces when available). Never raises."""
    try:
        return _leggi_audience_geography_impl(days=days)
    except Exception as e:
        print(f"[analytics] audience geography unavailable ({type(e).__name__}: {e})", flush=True)
        return {"has_data": False, "countries": [], "provinces": [], "error": str(e)}


def _leggi_audience_geography_impl(*, days: int = 28) -> dict:
    yta = _analytics_client()
    end = date.today()
    start = end - timedelta(days=max(7, days))

    countries_resp = (
        yta.reports()
        .query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="views",
            dimensions="country",
            sort="-views",
            maxResults=25,
        )
        .execute()
    )
    countries = [
        {"country": row[0], "views": int(row[1])}
        for row in (countries_resp.get("rows") or [])
    ]

    provinces: list[dict] = []
    us_views = sum(c["views"] for c in countries if c["country"] == "US")
    if us_views > 0:
        try:
            prov_resp = (
                yta.reports()
                .query(
                    ids="channel==MINE",
                    startDate=start.isoformat(),
                    endDate=end.isoformat(),
                    metrics="views",
                    dimensions="province",
                    filters="country==US",
                    sort="-views",
                    maxResults=25,
                )
                .execute()
            )
            provinces = [
                {"province": row[0], "views": int(row[1])}
                for row in (prov_resp.get("rows") or [])
            ]
        except Exception:
            pass

    return {
        "has_data": bool(countries),
        "countries": countries,
        "provinces": provinces,
        "period_days": days,
    }
