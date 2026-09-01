"""Test confidenza campione e ottimizzazione publish."""
import unittest

from moduli.channel_confidence import (
    channel_confidence,
    confidence_from_profiles,
    should_claim_pattern,
)
from moduli.publish_optimization import analyze_publish_timing, recommend_publish_hours


class ChannelConfidenceTests(unittest.TestCase):
    def test_low_for_one_or_two_videos(self):
        c = channel_confidence(1)
        self.assertEqual(c.level, "LOW")
        self.assertFalse(c.apply_learning)
        self.assertFalse(c.apply_publish_changes)

        c2 = channel_confidence(2)
        self.assertEqual(c2.level, "LOW")

    def test_medium_weak_signals(self):
        c = channel_confidence(4)
        self.assertEqual(c.level, "MEDIUM")
        self.assertTrue(c.apply_learning)
        self.assertFalse(c.apply_publish_changes)

    def test_high_at_ten_plus(self):
        c = channel_confidence(12)
        self.assertEqual(c.level, "HIGH")
        self.assertTrue(c.apply_publish_changes)

    def test_should_not_claim_on_tiny_sample(self):
        self.assertFalse(should_claim_pattern(1, 3))
        self.assertTrue(should_claim_pattern(2, 6))


class PublishOptimizationTests(unittest.TestCase):
    def _profile(self, vid, hour, ctr, views, retention=50):
        return {
            "video_id": vid,
            "title": f"Video {vid}",
            "published_hour_utc": hour,
            "published_day_utc": "Monday",
            "published_at": "2026-08-01T12:00:00Z",
            "metrics": {
                "ctr_percent": ctr,
                "views": views,
                "duration_seconds": 480,
                "avg_view_duration_seconds": retention / 100 * 480,
                "retention_percent": retention,
            },
        }

    def test_low_confidence_keeps_defaults(self):
        profiles = [
            self._profile("a", 20, 8, 1000, 60),
            self._profile("b", 8, 2, 100, 30),
        ]
        rec = recommend_publish_hours(profiles, videos_per_day=2)
        self.assertEqual(rec["confidence"], "LOW")
        self.assertFalse(rec.get("changed", True) and rec["confidence"] == "LOW")

    def test_analyze_publish_timing_rankings(self):
        profiles = [
            self._profile(f"v{i}", h, ctr, views, ret)
            for i, (h, ctr, views, ret) in enumerate([
                (20, 8, 1000, 60),
                (20, 7, 900, 55),
                (8, 2, 100, 30),
                (14, 6, 700, 50),
                (14, 5, 600, 48),
                (17, 4, 400, 45),
            ])
        ]
        analysis = analyze_publish_timing(profiles)
        self.assertTrue(analysis["has_data"])
        self.assertGreaterEqual(len(analysis["hour_rankings"]), 2)
        top_hour = analysis["hour_rankings"][0]["hour_utc"]
        self.assertIn(top_hour, (14, 20))

    def test_no_change_on_single_video_hour(self):
        profiles = [self._profile("only", 20, 10, 5000, 70)]
        rec = recommend_publish_hours(profiles, videos_per_day=1, current_hours=[14])
        self.assertFalse(rec.get("changed"))


if __name__ == "__main__":
    unittest.main()
