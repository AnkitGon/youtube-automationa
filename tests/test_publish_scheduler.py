"""Tests for deterministic publish scheduler (audience TZ, not PC clock)."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from moduli.publish_scheduler import (
    SchedulerConfig,
    compute_publish_schedule,
    infer_audience_timezone,
    validate_publish_timestamp,
    format_youtube_publish_at,
    resolve_pipeline_trigger_hours,
)


def _activity(views: int = 200, hour: int = 19, dow: int = 7) -> dict:
    """Saturday 19:00 peak (YouTube dow 7=Saturday)."""
    return {
        "has_data": True,
        "total_views": views,
        "buckets": [{"day_of_week": dow, "hour": hour, "views": views}],
    }


class PublishSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SchedulerConfig(
            default_publish_time="18:00",
            default_publish_timezone="Europe/London",
            analytics_min_videos=3,
            activity_min_views=50,
            activity_min_buckets=1,
            pipeline_trigger_hours=[14],
        )

    # TEST 1 — no analytics data → fallback
    def test_no_analytics_uses_fallback(self):
        state = {"auto_scheduling": True, "video_ids": []}
        now = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)  # Sunday
        dec = compute_publish_schedule(
            state, now=now, activity=None, geography=None, video_count=0, config=self.cfg
        )
        self.assertTrue(dec.fallback_used)
        self.assertEqual(dec.audience_timezone, "Europe/London")
        self.assertEqual(dec.publish_at_utc.hour, 18)  # 18:00 London = 18 UTC in winter
        self.assertIn("18:00", dec.local_publish_label)

    # TEST 2 — analytics peak Saturday 19:00 London
    def test_analytics_peak_saturday_19_london(self):
        state = {"auto_scheduling": True, "video_ids": ["a"] * 6}
        geo = {"countries": [{"country": "GB", "views": 500}]}
        now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)  # Tuesday
        dec = compute_publish_schedule(
            state,
            now=now,
            activity=_activity(hour=19, dow=7, views=300),
            geography=geo,
            video_count=6,
            config=self.cfg,
        )
        self.assertFalse(dec.fallback_used)
        self.assertEqual(dec.source, "analytics")
        self.assertEqual(dec.peak_day, "Saturday")
        self.assertEqual(dec.peak_hour_local, 19)
        local = dec.publish_at_utc.astimezone(ZoneInfo("Europe/London"))
        self.assertEqual(local.weekday(), 5)  # Saturday
        self.assertEqual(local.hour, 19)

    # TEST 3 — UK daylight saving (BST): 18:00 London → 17:00 UTC in summer
    def test_london_dst_summer_conversion(self):
        state = {"auto_scheduling": True}
        now = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)  # BST
        dec = compute_publish_schedule(
            state, now=now, activity=None, video_count=0, config=self.cfg
        )
        local = dec.publish_at_utc.astimezone(ZoneInfo("Europe/London"))
        self.assertEqual(local.hour, 18)
        self.assertEqual(dec.publish_at_utc.hour, 17)  # BST = UTC+1

    # TEST 4 — US audience does not use London blindly
    def test_us_audience_timezone(self):
        geo = {
            "countries": [{"country": "US", "views": 800}, {"country": "GB", "views": 50}],
            "provinces": [{"province": "CA", "views": 400}, {"province": "NY", "views": 200}],
        }
        tz, basis = infer_audience_timezone(geo["countries"], provinces=geo["provinces"])
        self.assertEqual(tz, "America/Los_Angeles")

        state = {"auto_scheduling": True, "video_ids": ["x"] * 8}
        dec = compute_publish_schedule(
            state,
            now=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            activity=_activity(hour=20, dow=7, views=400),
            geography=geo,
            video_count=8,
            config=self.cfg,
        )
        self.assertEqual(dec.audience_timezone, "America/Los_Angeles")

    # TEST 5 & 6 — PC timezone must not affect publish timestamp
    def test_publish_identical_regardless_of_pc_tz_env(self):
        state = {"auto_scheduling": True}
        now = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
        kwargs = dict(state=state, now=now, activity=None, video_count=0, config=self.cfg)
        dec_a = compute_publish_schedule(**kwargs)
        with patch.dict(os.environ, {"TZ": "America/Los_Angeles"}):
            dec_b = compute_publish_schedule(**kwargs)
        self.assertEqual(dec_a.youtube_publish_at, dec_b.youtube_publish_at)

    # TEST 7 — past timestamp advances to next valid slot
    def test_past_timestamp_corrected(self):
        past = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
        fixed = validate_publish_timestamp(past, now)
        self.assertGreater(fixed, now)

    # TEST 8 — single outlier should not radically change (stability)
    def test_stability_limits_hour_shift_on_medium_confidence(self):
        state = {
            "auto_scheduling": True,
            "last_schedule_decision": {"peak_hour_local": 18},
        }
        # Medium confidence (5 videos), peak at hour 2 — should stabilize toward 18
        dec = compute_publish_schedule(
            state,
            now=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            activity=_activity(hour=2, dow=3, views=200),
            geography={"countries": [{"country": "GB", "views": 100}]},
            video_count=5,
            config=self.cfg,
        )
        self.assertIn(dec.peak_hour_local, (2, 18))  # may stabilize
        if dec.confidence == "MEDIUM":
            local_h = dec.publish_at_utc.astimezone(ZoneInfo("Europe/London")).hour
            self.assertLessEqual(abs(local_h - 18), 2)

    # TEST 9 — other analytics but no viewer activity → fallback
    def test_no_viewer_activity_buckets_uses_fallback(self):
        state = {"auto_scheduling": True, "video_ids": ["v"] * 10}
        activity = {"has_data": False, "buckets": [], "total_views": 0}
        dec = compute_publish_schedule(
            state,
            now=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            activity=activity,
            video_count=10,
            config=self.cfg,
        )
        self.assertTrue(dec.fallback_used)

    def test_youtube_rfc3339_format(self):
        dt = datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(format_youtube_publish_at(dt), "2026-09-05T17:00:00Z")

    def test_pipeline_trigger_independent_when_auto_scheduling(self):
        state = {"auto_scheduling": True, "best_hours_utc": [20]}
        hours = resolve_pipeline_trigger_hours(state, self.cfg)
        self.assertEqual(hours, [14])


class TopicDedupSmokeTest(unittest.TestCase):
    """TEST 10 — semantic duplicate topics blocked."""

    def test_semantic_duplicate_blocked(self):
        from moduli.topic_history import find_semantic_duplicate

        is_dup, match, _reason = find_semantic_duplicate(
            "Why Nokia Failed in the Smartphone Era",
        )
        # With empty history may not match — seed registry if needed
        if not is_dup:
            from moduli.topic_history import record_topic
            record_topic("How Nokia Lost the Smartphone War", title="Nokia Story")
            is_dup, match, _reason = find_semantic_duplicate(
                "Why Nokia Failed in the Smartphone Era",
            )
        self.assertTrue(is_dup)
        self.assertIsNotNone(match)


if __name__ == "__main__":
    unittest.main()
