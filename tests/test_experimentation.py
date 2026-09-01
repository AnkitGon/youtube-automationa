"""Test sistema sperimentazione controllata."""
import json
import os
import tempfile
import unittest

from moduli import experimentation as ex
from moduli import strategy_memory as sm


class ExperimentationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_exp = ex.EXPERIMENTS_FILE
        self._old_memory = sm.MEMORY_FILE
        ex.EXPERIMENTS_FILE = os.path.join(self._tmpdir.name, "experiments.json")
        sm.MEMORY_FILE = os.path.join(self._tmpdir.name, "strategy_memory.json")

    def tearDown(self):
        ex.EXPERIMENTS_FILE = self._old_exp
        sm.MEMORY_FILE = self._old_memory
        self._tmpdir.cleanup()

    def test_classify_exploitation(self):
        strategy = {
            "_topic_diversity_mode": "exploit",
            "_winning_patterns": [{"pattern": "technology failure stories"}],
            "_title_experiment": {"mode": "exploit", "pattern_label": "Why X Failed"},
        }
        content = {"title": "Why This AI Startup Failed", "script": "x" * 200}
        cls = ex.classify_video_strategy("AI startup collapse", strategy, content)
        self.assertEqual(cls["mode"], "exploitation")
        self.assertIn("proven", cls["label"].lower())

    def test_classify_experiment_from_topic_explore(self):
        strategy = {
            "_topic_diversity_mode": "explore",
            "_explore_subtheme": "AI hardware business",
            "_title_experiment": {"mode": "exploit"},
            "_hook_experiment": {"mode": "exploit"},
        }
        content = {"title": "The Hidden Business of AI Chips", "script": "x" * 200}
        cls = ex.classify_video_strategy("AI chip economics", strategy, content)
        self.assertEqual(cls["mode"], "experiment")
        self.assertIn("hardware", cls["label"].lower())

    def test_record_and_format(self):
        cls = {"mode": "experiment", "label": "AI hardware business story", "dimensions": {}}
        rec = ex.record_video_classification("vid1", "topic", "Title", cls)
        self.assertEqual(rec["video_number"], 1)
        text = ex.format_classification(rec)
        self.assertIn("EXPERIMENT", text)
        self.assertIn("AI hardware", text)

    def test_promote_winning_experiment(self):
        cls = {"mode": "experiment", "label": "curiosity-driven framing", "dimensions": {}}
        ex.record_video_classification("vid_win", "topic", "Title", cls)
        profiles = [{
            "video_id": "vid_win",
            "topic": "topic",
            "title": "Title",
            "performance_tier": "strong",
            "performance_score": 0.82,
            "metrics": {"views": 500, "ctr_percent": 8, "retention_percent": 55, "duration_seconds": 480},
            "content_metadata": {},
        }]
        evaluated = ex.evaluate_pending_experiments(profiles)
        self.assertEqual(len(evaluated), 1)
        self.assertEqual(evaluated[0]["outcome"], "win")
        stats = ex.experiment_stats()
        self.assertEqual(stats["promoted_experiments"], 1)
        self.assertTrue(stats["winning_pool"])

    def test_demote_losing_experiment(self):
        cls = {"mode": "experiment", "label": "generic AI future topics", "dimensions": {}}
        ex.record_video_classification("vid_lose", "topic", "Title", cls)
        profiles = [{
            "video_id": "vid_lose",
            "topic": "topic",
            "title": "Title",
            "performance_tier": "poor",
            "performance_score": 0.12,
            "metrics": {"views": 100, "ctr_percent": 1, "retention_percent": 20, "duration_seconds": 480},
            "content_metadata": {},
        }]
        evaluated = ex.evaluate_pending_experiments(profiles)
        self.assertEqual(evaluated[0]["outcome"], "loss")
        stats = ex.experiment_stats()
        self.assertTrue(stats["losing_pool"])

    def test_exploitation_not_promoted_as_experiment(self):
        cls = {"mode": "exploitation", "label": "proven failure story", "dimensions": {}}
        ex.record_video_classification("vid_exp", "topic", "Title", cls)
        profiles = [{
            "video_id": "vid_exp",
            "performance_tier": "breakout",
            "performance_score": 0.95,
            "metrics": {"views": 1000, "duration_seconds": 480},
        }]
        evaluated = ex.evaluate_pending_experiments(profiles)
        self.assertEqual(len(evaluated), 0)


if __name__ == "__main__":
    unittest.main()
