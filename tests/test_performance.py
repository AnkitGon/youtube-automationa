"""Test profili performance e scoring normalizzato."""
import unittest
from datetime import datetime, timezone, timedelta

from moduli.performance import (
    apply_tier_classification,
    classify_profiles,
    classify_tier,
    compute_score_breakdown,
    detect_patterns,
    registra_pubblicazione,
    score_video,
    sync_profiles,
    video_age_hours,
    _load_weights,
)


class PerformanceProfileTests(unittest.TestCase):
    def test_video_age_hours_recent(self):
        pub = (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
        age = video_age_hours(pub)
        self.assertGreater(age, 10)
        self.assertLess(age, 14)

    def test_younger_video_can_outscore_older_on_velocity(self):
        now = datetime.now(timezone.utc)
        young_pub = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_pub = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        young = {
            "published_at": young_pub,
            "metrics": {
                "views": 8000, "ctr_percent": 5, "duration_seconds": 600,
                "avg_view_duration_seconds": 300, "retention_percent": 50,
                "likes": 40, "comments": 5, "impressions": 100000,
            },
        }
        old = {
            "published_at": old_pub,
            "metrics": {
                "views": 10000, "ctr_percent": 3, "duration_seconds": 600,
                "avg_view_duration_seconds": 200, "retention_percent": 33,
                "likes": 30, "comments": 2, "impressions": 200000,
            },
        }
        young_score = compute_score_breakdown(young)["performance_score"]
        old_score = compute_score_breakdown(old)["performance_score"]
        # 8k in 1 day beats 10k in 30 days on velocity-normalized score
        self.assertGreater(young_score, old_score)

    def test_score_bounded_zero_to_one(self):
        profile = {
            "published_at": "2026-08-01T12:00:00Z",
            "metrics": {
                "views": 500, "ctr_percent": 8, "duration_seconds": 480,
                "avg_view_duration_seconds": 240, "retention_percent": 50,
                "likes": 20, "comments": 3,
            },
        }
        breakdown = compute_score_breakdown(profile)
        self.assertGreaterEqual(breakdown["performance_score"], 0)
        self.assertLessEqual(breakdown["performance_score"], 1.0)

    def test_weights_normalize_to_one(self):
        w = _load_weights()
        self.assertAlmostEqual(sum(w.values()), 1.0, places=4)

    def test_sync_profiles_merges_analytics(self):
        row = {
            "video_id": "testvid123",
            "title": "Test Video",
            "published_at": "2026-08-30T20:00:00Z",
            "published_hour_utc": 20,
            "views": 100,
            "likes": 5,
            "comments": 1,
            "duration_seconds": 300,
            "avg_view_duration_seconds": 120,
            "avg_view_percentage": 40,
            "retention_percent": 40,
            "ctr_percent": 4.5,
            "impressions": 2000,
            "estimated_minutes_watched": 200,
            "shares": None,
            "subscribers_gained": None,
        }
        profiles = sync_profiles([row])
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["video_id"], "testvid123")
        self.assertIn("performance_score", profiles[0])
        self.assertIn("metrics", profiles[0])

    def test_registra_pubblicazione_stores_metadata(self):
        import os
        import tempfile
        from moduli import performance as perf_mod
        old_file = perf_mod.PROFILES_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                perf_mod.PROFILES_FILE = os.path.join(tmp, "profiles.json")
                p = registra_pubblicazione(
                    "vid99", "AI Jobs Future", "Will AI Replace You?",
                    {"script": "Hook line here. " * 20, "mood": "tense",
                     "thumbnail_phrase": "AI JOBS", "thumbnail_description": "robot office"},
                    {"preferred_angle": "contrarian", "content_format": "case study",
                     "hook_strength": "aggressive", "topic_focus": "AI jobs"},
                )
                self.assertEqual(p["content_metadata"]["topic_angle"], "contrarian")
                self.assertEqual(p["content_metadata"]["thumbnail_concept"], "AI JOBS")
        finally:
            perf_mod.PROFILES_FILE = old_file

    def test_score_video_api_compat(self):
        row = {
            "published_at": "2026-08-29T10:00:00Z",
            "views": 200, "ctr_percent": 6, "duration_seconds": 400,
            "avg_view_duration_seconds": 200, "likes": 10, "comments": 2,
        }
        s = score_video(row)
        self.assertGreater(s, 0)
        self.assertLessEqual(s, 100)


class WinnerLoserTests(unittest.TestCase):
    def _profile(self, vid, title, score, **meta_kw):
        return {
            "video_id": vid,
            "title": title,
            "topic": meta_kw.pop("topic", title),
            "published_at": "2026-08-20T12:00:00Z",
            "performance_score": score,
            "metrics": {
                "views": int(score * 1000),
                "ctr_percent": 3 + score * 5,
                "duration_seconds": meta_kw.pop("duration_seconds", 480),
                "avg_view_duration_seconds": meta_kw.pop("avg_view_duration_seconds", 200),
                "retention_percent": meta_kw.pop("retention_percent", 40),
                "likes": 5,
                "comments": 1,
            },
            "content_metadata": {
                "title_pattern": meta_kw.pop("title_pattern", "statement"),
                "content_format": meta_kw.pop("content_format", "explainer"),
                "topic_angle": meta_kw.pop("topic_angle", ""),
                "thumbnail_concept": meta_kw.pop("thumbnail_concept", ""),
                "hook_strength": meta_kw.pop("hook_strength", "medium"),
                **meta_kw,
            },
        }

    def test_tier_classification_relative(self):
        profiles = [
            self._profile("a", "Why Google Failed", 0.9, title_pattern="how_why_what",
                          topic="Google collapse"),
            self._profile("b", "AI Future 2030", 0.7, title_pattern="statement",
                          topic="future of ai"),
            self._profile("c", "Random Tech", 0.5),
            self._profile("d", "Everything About AI", 0.3, title_pattern="statement",
                          topic="everything about AI"),
            self._profile("e", "Weak Video", 0.1, hook_strength="soft", retention_percent=20),
        ]
        tiers = classify_profiles(profiles)
        self.assertEqual(tiers["a"], "breakout")
        self.assertEqual(tiers["e"], "poor")

    def test_detect_winning_failure_story_pattern(self):
        profiles = [
            self._profile("w1", "Why Nokia Failed", 0.85, topic="Nokia failure collapse"),
            self._profile("w2", "The WeWork Disaster", 0.75, topic="startup failure"),
            self._profile("l1", "The Future of AI", 0.25, topic="future of ai revolution"),
            self._profile("l2", "AI News This Week", 0.2, topic="latest ai news"),
        ]
        patterns = detect_patterns(profiles)
        winning_text = " ".join(p["pattern"] for p in patterns["winning_patterns"]).lower()
        losing_text = " ".join(p["pattern"] for p in patterns["losing_patterns"]).lower()
        self.assertTrue(
            "failure" in winning_text or "why" in winning_text,
            f"expected failure/why in winners, got {winning_text}",
        )
        self.assertTrue(
            "generic ai" in losing_text or "future" in losing_text or "news" in losing_text,
            f"expected generic AI in losers, got {losing_text}",
        )

    def test_duration_comparison_pattern(self):
        profiles = [
            self._profile("long", "Good Long", 0.8, duration_seconds=480),
            self._profile("long2", "Also Long", 0.75, duration_seconds=500),
            self._profile("short", "Bad Short", 0.2, duration_seconds=300),
            self._profile("short2", "Also Short", 0.25, duration_seconds=280),
        ]
        patterns = detect_patterns(profiles)
        duration_wins = [p for p in patterns["winning_patterns"] if "length" in p["pattern"]]
        self.assertTrue(duration_wins)

    def test_single_video_tier_is_average(self):
        tiers = classify_profiles([self._profile("only", "Solo", 0.5)])
        self.assertEqual(tiers.get("only"), "average")


if __name__ == "__main__":
    unittest.main()
