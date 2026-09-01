"""Test memoria strategica persistente."""
import json
import os
import tempfile
import unittest

from moduli import strategy_memory as sm


class StrategyMemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_history = sm.HISTORY_FILE
        self._old_memory = sm.MEMORY_FILE
        sm.HISTORY_FILE = os.path.join(self._tmpdir.name, "strategia_storia.json")
        sm.MEMORY_FILE = os.path.join(self._tmpdir.name, "strategy_memory.json")

    def tearDown(self):
        sm.HISTORY_FILE = self._old_history
        sm.MEMORY_FILE = self._old_memory
        self._tmpdir.cleanup()

    def _profile(self, vid, topic, score, tier, **meta):
        return {
            "video_id": vid,
            "title": f"Title {vid}",
            "topic": topic,
            "performance_tier": tier,
            "performance_score": score,
            "published_hour_utc": 14,
            "metrics": {"duration_seconds": 480, "ctr_percent": 5, "retention_percent": 50},
            "content_metadata": {
                "title_pattern": meta.get("title_pattern", "how_why_what"),
                "content_format": meta.get("content_format", "case study"),
                "thumbnail_concept": meta.get("thumbnail_concept", "BOLD TEXT"),
                "hook_strength": meta.get("hook_strength", "aggressive"),
            },
        }

    def _insights(self):
        return {
            "video_count": 4,
            "winning_patterns": [{"pattern": "topic theme: failure stories", "vs_channel_median": 20}],
            "losing_patterns": [{"pattern": "topic theme: generic AI future", "vs_channel_median": -18}],
            "winners_count": 2,
            "losers_count": 2,
        }

    def _strategy(self):
        return {
            "topic_focus": "AI business failures",
            "preferred_angle": "case study",
            "title_style": "curiosity-driven",
            "hook_strength": "aggressive",
            "target_minutes": 8,
            "avoid_patterns": "generic AI future titles",
        }

    def test_record_cycle_extends_history_and_memory(self):
        profiles = [
            self._profile("w1", "Why Nokia Failed", 0.9, "breakout"),
            self._profile("l1", "Future of AI", 0.2, "poor"),
        ]
        result = sm.record_strategy_cycle(
            profiles, self._insights(), self._strategy(), [{"title": "top"}], [{"title": "bot"}]
        )
        self.assertIn("entry", result)
        self.assertIn("memory", result)

        history = sm.load_history()
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertIn("strategy", entry)
        self.assertIn("top_performers", entry)
        self.assertIn("successful_topics", entry)
        self.assertIn("confidence_level", entry)
        self.assertIn("video_ids", entry)

        memory = sm.load_memory()
        self.assertEqual(memory["cycles"], 1)
        self.assertTrue(memory["rollup"]["winning_patterns"])

    def test_memory_accumulates_confidence_across_cycles(self):
        profiles = [self._profile("w1", "Failure story", 0.85, "strong")]
        insights = {
            "video_count": 1,
            "winning_patterns": [{"pattern": "case study format", "vs_channel_median": 12, "video_id": "w1"}],
            "losing_patterns": [],
            "winners_count": 1,
            "losers_count": 0,
        }
        sm.record_strategy_cycle(profiles, insights, self._strategy(), [], [])
        sm.record_strategy_cycle(profiles, insights, self._strategy(), [], [])
        rollup = sm.load_memory()["rollup"]
        pattern = rollup["winning_patterns"][0]
        self.assertGreaterEqual(pattern.get("times_seen", 0), 2)
        self.assertGreater(pattern.get("confidence_level", 0), 0.4)

    def test_legacy_history_entries_still_load(self):
        legacy = [{
            "date": "2026-01-01",
            "strategy": {"topic_focus": "old"},
            "top_performers": [],
            "underperformers": [],
        }]
        sm.save_history(legacy)
        loaded = sm.load_history()
        self.assertEqual(loaded[0]["strategy"]["topic_focus"], "old")

    def test_memory_for_llm_includes_success_and_failure(self):
        profiles = [
            self._profile("w1", "Why X Failed", 0.9, "breakout", title_pattern="how_why_what"),
            self._profile("l1", "AI Future 2030", 0.15, "poor", title_pattern="statement"),
        ]
        sm.record_strategy_cycle(profiles, self._insights(), self._strategy(), [], [])
        llm = sm.memory_for_llm()
        self.assertGreater(llm["cycles_recorded"], 0)
        self.assertTrue(
            llm.get("historical_winning_patterns") or llm.get("successful_topics")
        )

    def test_memory_context_block_non_empty_after_record(self):
        profiles = [self._profile("w1", "Topic A", 0.8, "strong")]
        sm.record_strategy_cycle(profiles, self._insights(), self._strategy(), [], [])
        block = sm.memory_context_block()
        self.assertIn("Cycles recorded", block)


if __name__ == "__main__":
    unittest.main()
