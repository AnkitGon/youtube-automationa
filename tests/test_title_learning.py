"""Test analisi pattern titoli e guida sperimentale."""
import os
import tempfile
import unittest
from unittest.mock import patch

from moduli import title_learning as tl
from moduli.title_learning import (
    analyze_title_patterns,
    classify_title_pattern,
    pick_title_experiment,
    title_guidance_block,
)


class TitleLearningTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_file = tl.TITLE_STATS_FILE
        tl.TITLE_STATS_FILE = os.path.join(self._tmpdir.name, "title_learning.json")

    def tearDown(self):
        tl.TITLE_STATS_FILE = self._old_file
        self._tmpdir.cleanup()

    def test_classify_patterns(self):
        self.assertEqual(classify_title_pattern("Why Nokia Failed in Smartphones"), "why_x_failed")
        self.assertEqual(classify_title_pattern("The Truth About OpenAI's Board"), "truth_about")
        self.assertEqual(classify_title_pattern("How ChatGPT Changed Google"), "how_x_changed")
        self.assertEqual(classify_title_pattern("5 Reasons AI Chips Are Exploding"), "numbered")
        self.assertEqual(classify_title_pattern("Is Apple Building Its Own AI?"), "question")
        self.assertEqual(classify_title_pattern("The Hidden Cost of AI Data Centers"), "curiosity")
        self.assertEqual(
            classify_title_pattern("The Hidden Reason Google Killed This Product"),
            "hidden_reason",
        )

    def test_analyze_correlations(self):
        profiles = [
            {
                "video_id": "v1",
                "title": "Why Blockbuster Failed So Fast",
                "published_at": "2026-08-01T12:00:00Z",
                "performance_score": 0.85,
                "metrics": {
                    "views": 5000, "ctr_percent": 8.0, "duration_seconds": 480,
                    "avg_view_duration_seconds": 360,
                },
            },
            {
                "video_id": "v2",
                "title": "Random Tech Statement Title Here",
                "published_at": "2026-08-01T12:00:00Z",
                "performance_score": 0.35,
                "metrics": {
                    "views": 200, "ctr_percent": 2.0, "duration_seconds": 480,
                    "avg_view_duration_seconds": 120,
                },
            },
        ]
        analysis = analyze_title_patterns(profiles)
        self.assertTrue(analysis["has_data"])
        self.assertGreaterEqual(len(analysis["patterns"]), 1)
        why_rows = [p for p in analysis["patterns"] if p["pattern_id"] == "why_x_failed"]
        self.assertTrue(why_rows)
        self.assertGreater(why_rows[0]["avg_ctr"], 2.0)

    def test_pick_experiment_exploit_vs_explore(self):
        analysis = {
            "has_data": True,
            "video_count": 10,
            "winning_title_patterns": [{
                "pattern_id": "why_x_failed",
                "pattern_label": "Why X Failed",
                "score_vs_channel": 12,
                "avg_ctr": 7.0,
                "ctr_vs_channel": 2.0,
                "avg_retention": 55,
                "retention_vs_channel": 5,
                "avg_velocity": 100,
            }],
            "losing_title_patterns": [],
            "patterns": [],
        }
        with patch.object(tl, "_decide_title_mode", return_value="exploit"):
            exp = pick_title_experiment(analysis)
        self.assertEqual(exp["mode"], "exploit")
        self.assertEqual(exp["pattern_id"], "why_x_failed")

        with patch.object(tl, "_decide_title_mode", return_value="explore"):
            exp = pick_title_experiment(analysis)
        self.assertEqual(exp["mode"], "explore")

    def test_title_guidance_block_includes_experiment(self):
        strategy = {"title_style": "curiosity-driven"}
        with patch("moduli.performance.carica_profili", return_value=[]):
            block = title_guidance_block(strategy)
        self.assertIn("TITLE LEARNING", block)
        self.assertIn("Suggested structure", block)
        self.assertIn("Experiment", block)
        self.assertIsNotNone(strategy.get("_title_experiment"))


if __name__ == "__main__":
    unittest.main()
