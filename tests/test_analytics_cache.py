"""Test cache analytics — meno chiamate API."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from moduli import analytics_cache as ac
from moduli.performance import profilo_to_analytics_row


class AnalyticsCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_cache = ac.CACHE_FILE
        ac.CACHE_FILE = os.path.join(self._tmpdir.name, "analytics_snapshot.json")

    def tearDown(self):
        ac.CACHE_FILE = self._old_cache
        self._tmpdir.cleanup()

    def _fresh_profile(self, vid: str = "v1") -> dict:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "video_id": vid,
            "title": "Test Video",
            "published_at": "2026-08-28T12:00:00Z",
            "metrics_updated_at": now,
            "metrics": {
                "views": 100,
                "ctr_percent": 5.0,
                "avg_view_duration_seconds": 120,
                "duration_seconds": 480,
                "retention_percent": 25.0,
                "impressions": 1000,
            },
        }

    def test_snapshot_roundtrip(self):
        rows = [{"video_id": "a", "title": "A", "views": 1}]
        ac.save_snapshot(rows, 5)
        snap = ac.load_snapshot()
        self.assertTrue(ac.snapshot_is_fresh(snap, 5, ttl_minutes=90))
        self.assertEqual(snap["rows"][0]["video_id"], "a")

    def test_get_channel_performance_uses_cache(self):
        ac.save_snapshot([{"video_id": "x", "title": "X", "views": 9}], 5)
        with patch("moduli.analytics.leggi_performance") as mock_live:
            rows, source = ac.get_channel_performance(5, force=False)
        self.assertEqual(source, "cache")
        self.assertEqual(rows[0]["video_id"], "x")
        mock_live.assert_not_called()

    def test_get_channel_performance_force_calls_api(self):
        ac.save_snapshot([{"video_id": "x"}], 5)
        with patch("moduli.analytics.leggi_performance", return_value=[{"video_id": "y"}]) as mock_live:
            rows, source = ac.get_channel_performance(5, force=True)
        self.assertEqual(source, "api")
        self.assertEqual(rows[0]["video_id"], "y")
        mock_live.assert_called_once()

    def test_profilo_to_analytics_row(self):
        row = profilo_to_analytics_row(self._fresh_profile())
        self.assertEqual(row["video_id"], "v1")
        self.assertEqual(row["views"], 100)
        self.assertEqual(row["ctr_percent"], 5.0)

    def test_stale_snapshot_not_fresh(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M UTC")
        snap = {"fetched_at": old, "n_video": 5, "rows": [{"video_id": "a"}]}
        self.assertFalse(ac.snapshot_is_fresh(snap, 5, ttl_minutes=90))


if __name__ == "__main__":
    unittest.main()
