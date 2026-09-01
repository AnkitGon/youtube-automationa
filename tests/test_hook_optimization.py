"""Test analisi hook e guida script."""
import os
import tempfile
import unittest
from unittest.mock import patch

from moduli import hook_optimization as ho
from moduli.hook_optimization import (
    analyze_hook_patterns,
    classify_hook_type,
    hook_guidance_block,
    pick_hook_experiment,
)


class HookOptimizationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_file = ho.HOOK_STATS_FILE
        ho.HOOK_STATS_FILE = os.path.join(self._tmpdir.name, "hook_learning.json")

    def tearDown(self):
        ho.HOOK_STATS_FILE = self._old_file
        self._tmpdir.cleanup()

    def test_classify_hook_types(self):
        self.assertEqual(
            classify_hook_type("Did you know that 90% of startups fail within two years?"),
            "surprising_fact",
        )
        self.assertEqual(
            classify_hook_type("What if everything you knew about AI chips was wrong?"),
            "question",
        )
        self.assertEqual(
            classify_hook_type(
                "By the end of this story, the company had lost everything. But it started small."
            ),
            "outcome_first",
        )
        self.assertEqual(
            classify_hook_type("You need to understand this before the next AI wave hits."),
            "immediate_stakes",
        )
        self.assertEqual(
            classify_hook_type("In 2007, a small team in Finland made a decision that changed phones forever."),
            "story_opening",
        )
        self.assertEqual(
            classify_hook_type("Before we dive in, let me explain what this video is about."),
            "delayed_context",
        )

    def test_analyze_correlates_retention(self):
        profiles = [
            {
                "video_id": "v1",
                "title": "Stakes Video",
                "performance_score": 0.85,
                "content_metadata": {
                    "hook_type": "immediate_stakes",
                    "script_hook_excerpt": "You need to understand this now.",
                },
                "metrics": {
                    "retention_percent": 62,
                    "retention_at_30s_percent": 78,
                    "duration_seconds": 480,
                    "avg_view_duration_seconds": 300,
                },
            },
            {
                "video_id": "v2",
                "title": "Slow Intro",
                "performance_score": 0.3,
                "content_metadata": {
                    "hook_type": "delayed_context",
                    "script_hook_excerpt": "Before we begin, let me explain.",
                },
                "metrics": {
                    "retention_percent": 28,
                    "retention_at_30s_percent": 40,
                    "duration_seconds": 480,
                    "avg_view_duration_seconds": 130,
                },
            },
        ]
        analysis = analyze_hook_patterns(profiles)
        self.assertTrue(analysis["has_data"])
        self.assertTrue(analysis["has_30s_data"])
        self.assertTrue(analysis["strategy_recommendations"])
        winners = {w["hook_id"] for w in analysis["winning_hook_patterns"]}
        self.assertIn("immediate_stakes", winners)

    def test_pick_experiment_modes(self):
        analysis = {
            "winning_hook_patterns": [{
                "hook_id": "immediate_stakes",
                "hook_label": "immediate stakes opener",
                "retention_vs_channel": 10,
                "retention_30s_vs_channel": 15,
            }],
            "losing_hook_patterns": [{"hook_id": "delayed_context"}],
        }
        with patch.object(ho, "_decide_hook_mode", return_value="exploit"):
            exp = pick_hook_experiment(analysis)
        self.assertEqual(exp["mode"], "exploit")
        self.assertEqual(exp["hook_id"], "immediate_stakes")
        self.assertIn("15 seconds", exp["rationale"])

    def test_hook_guidance_block(self):
        strategy = {}
        with patch("moduli.performance.carica_profili", return_value=[]):
            block = hook_guidance_block(strategy)
        self.assertIn("HOOK OPTIMIZATION", block)
        self.assertIn("opening 30 seconds", block)
        self.assertIn("First 2 sentences", block)
        self.assertIsNotNone(strategy.get("_hook_experiment"))


if __name__ == "__main__":
    unittest.main()
