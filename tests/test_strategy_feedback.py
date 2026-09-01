"""Test feedback loop strategia → cervello."""
import unittest

from moduli.performance import score_video
from moduli.strategia import analyze_performance, normalize_strategy
from moduli.cervello import _avoid_block, _pick_levers, _target_minutes
from moduli.montaggio import resolve_segment_duration


class StrategyFeedbackTests(unittest.TestCase):
    def test_score_video_weights_ctr_and_retention(self):
        good = {
            "published_at": "2026-08-28T12:00:00Z",
            "views": 1000, "ctr_percent": 8, "duration_seconds": 600,
            "avg_view_duration_seconds": 360, "retention_percent": 60,
            "likes": 50, "comments": 10,
        }
        bad = {
            "published_at": "2026-08-28T12:00:00Z",
            "views": 10, "ctr_percent": 0.5, "duration_seconds": 600,
            "avg_view_duration_seconds": 30, "retention_percent": 5,
            "likes": 0, "comments": 0,
        }
        self.assertGreater(score_video(good), score_video(bad))

    def test_analyze_low_ctr_suggests_aggressive_signals(self):
        perf = [{"views": 5, "ctr_percent": 1.0, "duration_seconds": 480,
                 "avg_view_duration_seconds": 60, "title": "Test",
                 "video_id": "v1", "performance_score": 0.15}]
        insights = analyze_performance(perf, {"durata_target_minuti": 8})
        self.assertLess(insights["suggested_target_minutes"], 8)
        self.assertTrue(any("CTR" in s for s in insights["signals"]))

    def test_normalize_strategy_flattens_notes_list(self):
        s = normalize_strategy({"notes": ["a", "b"], "target_minutes": 6})
        self.assertIn("a", s["notes"])
        self.assertEqual(s["target_minutes"], 6)

    def test_avoid_block_includes_strategy_and_prefs(self):
        block = _avoid_block(
            {"avoid_patterns": "generic AI titles"},
            {"argomenti_evitare": ["crypto"]},
        )
        self.assertIn("generic AI", block)
        self.assertIn("crypto", block)

    def test_pick_levers_prefers_strategy(self):
        angle, fmt, _ = _pick_levers({
            "preferred_angle": "contrarian take",
            "content_format": "case study",
            "topic_focus": "AI business failures",
        })
        self.assertEqual(angle, "contrarian take")
        self.assertEqual(fmt, "case study")

    def test_target_minutes_from_strategy(self):
        self.assertEqual(_target_minutes({"target_minutes": 5}, {"durata_target_minuti": 8}), 5)

    def test_segment_duration_from_pacing(self):
        self.assertEqual(resolve_segment_duration({"pacing": "fast"}), 3.5)
        self.assertEqual(resolve_segment_duration({"pacing": "slow"}), 7.0)


if __name__ == "__main__":
    unittest.main()
