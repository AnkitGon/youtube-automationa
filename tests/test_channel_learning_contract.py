"""§31 — learning loop: adapt over time, never reuse same subject."""

import os
import tempfile
import unittest

from moduli import topic_history as th
from moduli.channel_learning import CATEGORY_REUSE_RULE, describe_learning_stage
from moduli.strategy_memory import _collect_from_profiles
from moduli.topic_history import TopicDuplicateError, find_semantic_duplicate, reserve_topic


class ChannelLearningContractTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_file = th.TOPIC_HISTORY_FILE
        th.TOPIC_HISTORY_FILE = os.path.join(self._tmpdir.name, "topic_history.json")

    def tearDown(self):
        th.TOPIC_HISTORY_FILE = self._old_file
        self._tmpdir.cleanup()

    def test_good_sequence_different_subjects(self):
        """Same category (tech failure) — different companies — all allowed."""
        topics = [
            "How Nokia Lost the Smartphone War",
            "Why BlackBerry Lost to the iPhone",
            "How Kodak Missed the Digital Revolution",
        ]
        for t in topics:
            reserve_topic(t, source="test")
        self.assertEqual(len(topics), 3)

    def test_bad_sequence_same_subject_rejected(self):
        """Nokia rewordings must be rejected as semantic duplicates."""
        reserve_topic("How Nokia Lost the Smartphone War", source="test")
        bad = [
            "Why Nokia Failed in the Smartphone Market",
            "The Real Reason Nokia Lost to Apple",
            "How Nokia Lost Apple in the Smartphone War",
        ]
        for t in bad:
            with self.subTest(topic=t):
                with self.assertRaises(TopicDuplicateError):
                    reserve_topic(t, source="test")

    def test_semantic_duplicate_detector_nokia_variants(self):
        th.record_topic("How Nokia Lost the Smartphone War", video_id="n1")
        dup, _, _ = find_semantic_duplicate(
            "Why Nokia Failed in the Smartphone Market", use_llm=False,
        )
        self.assertTrue(dup)
        dup2, _, _ = find_semantic_duplicate(
            "Why BlackBerry Lost to the iPhone", use_llm=False,
        )
        self.assertFalse(dup2)

    def test_learning_stage_progression(self):
        self.assertIn("Cold start", describe_learning_stage(0))
        self.assertIn("Video 1", describe_learning_stage(1))
        self.assertIn("Early learning", describe_learning_stage(2))
        self.assertIn("Maturing", describe_learning_stage(7))
        self.assertIn("Established", describe_learning_stage(15))
        self.assertIn("Deep channel memory", describe_learning_stage(50))

    def test_category_reuse_rule_documents_good_bad(self):
        self.assertIn("Nokia", CATEGORY_REUSE_RULE)
        self.assertIn("BlackBerry", CATEGORY_REUSE_RULE)
        self.assertIn("Kodak", CATEGORY_REUSE_RULE)
        self.assertIn("FORBIDDEN", CATEGORY_REUSE_RULE)


class StrategyMemoryCategoryTests(unittest.TestCase):
    def test_successful_topics_store_category_not_literal_topic(self):
        profiles = [
            {
                "video_id": "v1",
                "title": "How Nokia Lost the Smartphone War",
                "topic": "How Nokia Lost the Smartphone War",
                "performance_tier": "strong",
                "performance_score": 0.8,
                "content_metadata": {
                    "topic_category": "technology failure stories",
                    "content_format": "case study",
                },
                "metrics": {},
            }
        ]
        collected = _collect_from_profiles(profiles)
        winners = collected["successful_topics"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["story_category"], "technology failure stories")
        self.assertNotIn("topic", winners[0])
        self.assertIn("Nokia", winners[0].get("example_title", ""))


if __name__ == "__main__":
    unittest.main()
