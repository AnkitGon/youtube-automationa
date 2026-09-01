"""Test dashboard learning Telegram."""
import os
import tempfile
import unittest

from moduli import topic_history as th
from moduli.telegram_learning import (
    build_analytics_summary,
    build_learning_dashboard,
    build_strategy_summary,
    build_topic_memory_summary,
    build_topics_summary,
)


class TelegramLearningTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_file = th.TOPIC_HISTORY_FILE
        th.TOPIC_HISTORY_FILE = os.path.join(self._tmpdir.name, "topic_history.json")

    def tearDown(self):
        th.TOPIC_HISTORY_FILE = self._old_file
        self._tmpdir.cleanup()

    def test_registry_stats_counts(self):
        th.reserve_topic("Why Blockbuster Failed", source="manual")
        th.record_topic("How Nokia Lost the Smartphone War", video_id="n1")
        th.record_rejected_topic("Blockbuster collapse", matched="Why Blockbuster Failed")
        stats = th.registry_stats()
        self.assertEqual(stats["historical"], 2)
        self.assertEqual(stats["rejected_duplicate"], 1)
        self.assertEqual(stats["published"], 1)
        self.assertEqual(stats["reserved"], 1)

    def test_dashboard_sections(self):
        th.record_topic("Why Blockbuster Failed", video_id="b1")
        profiles = [{
            "title": "Why Blockbuster Failed",
            "performance_tier": "strong",
            "performance_score": 0.82,
            "metrics": {"ctr_percent": 5.2, "views": 1000},
        }, {
            "title": "Weak Video Title",
            "performance_tier": "weak",
            "performance_score": 0.35,
            "metrics": {"ctr_percent": 1.1, "views": 50},
        }]
        insights = {
            "video_count": 2,
            "avg_ctr": 3.1,
            "avg_retention": 42.0,
            "avg_performance_score": 58.5,
            "winning_patterns": [{"pattern": "Technology failure stories", "vs_channel_median": 12}],
            "losing_patterns": [{"pattern": "Generic AI explainers", "vs_channel_median": -8}],
        }
        strategy = {
            "topic_focus": "Business + technology failures",
            "_topic_diversity_mode": "explore",
            "_explore_subtheme": "AI hardware",
        }
        state = {"topic_queue": ["Manual topic queued"]}
        text = "\n".join(build_learning_dashboard(
            state=state, insights=insights, profiles=profiles, strategy=strategy,
        ))
        self.assertIn("ANALYTICS", text)
        self.assertIn("Videos analyzed: 2", text)
        self.assertIn("Best performer:", text)
        self.assertIn("Weakest performer:", text)
        self.assertIn("LEARNING", text)
        self.assertIn("Technology failure stories", text)
        self.assertIn("Generic AI explainers", text)
        self.assertIn("NEXT STRATEGY", text)
        self.assertIn("Business + technology failures", text)
        self.assertIn("AI hardware", text)
        self.assertIn("TOPIC MEMORY", text)
        self.assertIn("Historical topics: 1", text)
        self.assertIn("Duplicate topics rejected: 0", text)

    def test_strategy_summary(self):
        strategy = {
            "topic_focus": "Business failures",
            "avoid_patterns": "generic listicles",
            "target_minutes": 9,
        }
        insights = {
            "winning_patterns": [{"pattern": "Tech failure stories"}],
            "losing_patterns": [{"pattern": "Generic AI explainers"}],
        }
        text = "\n".join(build_strategy_summary(strategy=strategy, insights=insights))
        self.assertIn("Current learned strategy", text)
        self.assertIn("Business failures", text)
        self.assertIn("Tech failure stories", text)

    def test_topics_summary(self):
        state = {
            "topic_queue": ["Queued topic"],
            "recent_topics": ["Recent A", "Recent B"],
        }
        th.record_topic("Registry topic", video_id="v1")
        text = "\n".join(build_topics_summary(state=state))
        self.assertIn("In queue", text)
        self.assertIn("Queued topic", text)
        self.assertIn("Recently produced", text)
        self.assertIn("Registry topic", text)

    def test_topic_memory_summary(self):
        th.reserve_topic("Manual reserved topic", source="manual")
        th.record_rejected_topic("Dup topic", matched="Manual reserved topic")
        text = "\n".join(build_topic_memory_summary())
        self.assertIn("Topic memory", text)
        self.assertIn("Historical topics: 1", text)
        self.assertIn("Duplicate topics rejected: 1", text)
        self.assertIn("Reserved", text)

    def test_analytics_summary(self):
        profiles = [{
            "title": "Video A",
            "performance_tier": "strong",
            "performance_score": 0.9,
            "metrics": {},
        }]
        insights = {"video_count": 1, "avg_ctr": 4.5, "by_tier": {"strong": [{}]}}
        text = "\n".join(build_analytics_summary(insights=insights, profiles=profiles))
        self.assertIn("Analytics summary", text)
        self.assertIn("Videos analyzed: 1", text)


if __name__ == "__main__":
    unittest.main()
