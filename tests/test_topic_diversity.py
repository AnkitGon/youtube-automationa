"""Test bilanciamento exploit/explore per topic diversity."""
import os
import tempfile
import unittest
from unittest.mock import patch

from moduli import topic_diversity as td


class TopicDiversityTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_file = td.DIVERSITY_STATS_FILE
        td.DIVERSITY_STATS_FILE = os.path.join(self._tmpdir.name, "topic_diversity.json")
        self._env_patch = patch.dict(
            os.environ,
            {"TOPIC_EXPLOIT_RATIO": "0.75", "TOPIC_EXPLORE_RATIO": ""},
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        td.DIVERSITY_STATS_FILE = self._old_file
        self._tmpdir.cleanup()

    def test_default_ratios(self):
        self.assertEqual(td.exploit_ratio(), 0.75)
        self.assertAlmostEqual(td.explore_ratio(), 0.25)

    def test_exploit_ratio_env_clamped(self):
        with patch.dict(os.environ, {"TOPIC_EXPLOIT_RATIO": "0.99"}):
            self.assertEqual(td.exploit_ratio(), 0.95)
        with patch.dict(os.environ, {"TOPIC_EXPLOIT_RATIO": "0.1"}):
            self.assertEqual(td.exploit_ratio(), 0.5)

    def test_explore_ratio_override(self):
        with patch.dict(os.environ, {"TOPIC_EXPLORE_RATIO": "0.3"}):
            self.assertEqual(td.explore_ratio(), 0.3)

    def test_cold_start_no_winners_explores(self):
        self.assertEqual(td.decide_mode({}), "explore")

    def test_with_winners_first_is_exploit(self):
        strategy = {"_winning_patterns": [{"pattern": "failure case studies"}]}
        self.assertEqual(td.decide_mode(strategy), "exploit")

    def test_balancing_toward_target(self):
        strategy = {"_winning_patterns": [{"pattern": "failure case studies"}]}
        stats = {"exploit": 8, "explore": 2, "recent": []}
        with open(td.DIVERSITY_STATS_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump(stats, f)
        # 80% exploit > 75% target → next should be explore
        self.assertEqual(td.decide_mode(strategy), "explore")

        stats = {"exploit": 5, "explore": 5, "recent": []}
        with open(td.DIVERSITY_STATS_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump(stats, f)
        # 50% exploit < 75% target → next should be exploit
        self.assertEqual(td.decide_mode(strategy), "exploit")

    def test_record_mode_updates_stats(self):
        td.record_mode("exploit", "New AI Chip Startup")
        td.record_mode("explore", "Quantum Biology Breakthrough")
        stats = td.diversity_stats()
        self.assertEqual(stats["exploit"], 1)
        self.assertEqual(stats["explore"], 1)
        self.assertEqual(stats["total"], 2)
        self.assertAlmostEqual(stats["exploit_ratio_actual"], 0.5)

    def test_exploit_prompt_mentions_winning_patterns(self):
        strategy = {
            "_winning_patterns": [{"pattern": "tech failure stories"}],
            "topic_focus": "corporate collapse",
            "content_format": "case study",
        }
        block = td.diversity_prompt_block("exploit", strategy, "chip wars")
        self.assertIn("EXPLOITATION", block)
        self.assertIn("tech failure stories", block)
        self.assertIn("DIFFERENT company", block)

    def test_explore_prompt_mentions_subtheme(self):
        block = td.diversity_prompt_block("explore", {}, "obscure hardware hacks")
        self.assertIn("EXPLORATION", block)
        self.assertIn("obscure hardware hacks", block)

    def test_map_winning_pattern_to_levers(self):
        strategy = {
            "_winning_patterns": [
                {"pattern": "why companies failed", "dimension": "content_format", "value": "case study"},
            ],
            "topic_focus": "semiconductor industry",
        }
        angle, fmt, subtheme = td.map_winning_pattern_to_levers(
            strategy, ["angle a", "angle b"], ["listicle", "deep dive"]
        )
        self.assertIn("failure", angle.lower())
        self.assertEqual(fmt, "case study")
        self.assertEqual(subtheme, "semiconductor industry")


if __name__ == "__main__":
    unittest.main()
