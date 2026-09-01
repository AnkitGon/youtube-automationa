"""Test prompt topic generation e validazione post-LLM."""
import os
import tempfile
import unittest
from unittest.mock import patch

from moduli import topic_history as th
from moduli.cervello import (
    build_topic_prompt,
    genera_topic,
    _rejected_topics_block,
    _strategy_block,
    _winning_patterns_block,
    _losing_patterns_block,
    _topic_avoid_block,
)
from moduli.topic_history import TopicDuplicateError, record_topic


class TopicGenerationPromptTests(unittest.TestCase):
    def test_prompt_contains_novelty_mandate(self):
        prompt = build_topic_prompt(
            strategy={"topic_focus": "AI chips", "notes": "focus on failures"},
            pref={},
            recent_topics=["Recent Topic A"],
            rejected=["Rejected Nokia Topic"],
            trending_block="AI chip news headline",
            diversity_block="EXPLOITATION MODE",
            subtheme="semiconductor wars",
            angle="failure story",
            fmt="case study",
            historical_topics="- How Nokia Failed",
        )
        self.assertIn("NEVER been covered before", prompt)
        self.assertIn("NOT semantically similar", prompt)
        self.assertIn("=== CURRENT STRATEGY ===", prompt)
        self.assertIn("=== WINNING PATTERNS", prompt)
        self.assertIn("=== LOSING PATTERNS", prompt)
        self.assertIn("=== CHANNEL TOPIC HISTORY", prompt)
        self.assertIn("=== REJECTED THIS SESSION", prompt)
        self.assertIn("EXPLOITATION MODE", prompt)
        self.assertIn("AI chip news headline", prompt)
        self.assertIn("Rejected Nokia Topic", prompt)
        self.assertIn("How Nokia Failed", prompt)

    def test_strategy_block_lists_fields(self):
        block = _strategy_block({
            "topic_focus": "robotics",
            "preferred_angle": "contrarian",
            "content_format": "case study",
            "notes": "double down on hardware",
        })
        self.assertIn("Topic focus: robotics", block)
        self.assertIn("Preferred angle: contrarian", block)
        self.assertIn("double down on hardware", block)

    def test_winning_and_losing_blocks(self):
        wins = _winning_patterns_block({
            "_winning_patterns": [{"pattern": "failure case studies", "vs_channel_median": 12}],
        })
        self.assertIn("failure case studies", wins)
        self.assertIn("+12", wins)

        losses = _losing_patterns_block(
            {"_losing_patterns": [{"pattern": "generic AI news"}], "avoid_patterns": "listicles"},
            {"argomenti_evitare": ["crypto scams"]},
        )
        self.assertIn("generic AI news", losses)
        self.assertIn("crypto scams", losses)
        avoid = _topic_avoid_block(
            {"avoid_patterns": "listicles"},
            {},
        )
        self.assertIn("listicles", avoid)

    def test_rejected_block_includes_session_failures(self):
        block = _rejected_topics_block(
            ["Why Nokia Failed", "Blockbuster Collapse"],
            force_category=True,
            subtheme="robotics",
        )
        self.assertIn("Why Nokia Failed", block)
        self.assertIn("MANDATORY category shift", block)
        self.assertIn("robotics", block)


class TopicGenerationValidationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_file = th.TOPIC_HISTORY_FILE
        th.TOPIC_HISTORY_FILE = os.path.join(self._tmpdir.name, "topic_history.json")
        record_topic("How Nokia Lost the Smartphone War", video_id="n1")

    def tearDown(self):
        th.TOPIC_HISTORY_FILE = self._old_file
        self._tmpdir.cleanup()

    @patch("moduli.cervello.chat_ollama")
    @patch("moduli.cervello._fetch_trending", return_value="")
    @patch("moduli.topic_diversity.decide_mode", return_value="explore")
    @patch("moduli.topic_diversity.record_mode")
    def test_genera_topic_rejects_reasoning_response(
        self, _record, _mode, _trend, mock_chat
    ):
        mock_chat.side_effect = [
            "Here's a thinking process:\n1. Pick Nokia",
            "The Rise of RISC-V Open Chips",
        ]
        topic = genera_topic(strategy={}, recent_topics=[])
        self.assertEqual(topic, "The Rise of RISC-V Open Chips")
        self.assertEqual(mock_chat.call_count, 2)

    @patch("moduli.cervello.chat_ollama")
    @patch("moduli.cervello._fetch_trending", return_value="")
    @patch("moduli.topic_diversity.decide_mode", return_value="explore")
    @patch("moduli.topic_diversity.record_mode")
    def test_genera_topic_rejects_duplicate_then_accepts_unique(
        self, _record, _mode, _trend, mock_chat
    ):
        mock_chat.side_effect = [
            "Why Nokia Failed in Smartphones",
            "The Rise of RISC-V Open Chips",
        ]
        topic = genera_topic(strategy={}, recent_topics=[])
        self.assertEqual(topic, "The Rise of RISC-V Open Chips")
        self.assertEqual(mock_chat.call_count, 2)

    @patch("moduli.cervello.chat_ollama")
    @patch("moduli.cervello._fetch_trending", return_value="")
    @patch("moduli.topic_diversity.decide_mode", return_value="explore")
    @patch("moduli.topic_diversity.record_mode")
    def test_genera_topic_rejects_reasoning_response(
        self, _record, _mode, _trend, mock_chat
    ):
        mock_chat.side_effect = [
            "Here's a thinking process:\n1. Pick Nokia",
            "The Rise of RISC-V Open Chips",
        ]
        topic = genera_topic(strategy={}, recent_topics=[])
        self.assertEqual(topic, "The Rise of RISC-V Open Chips")
        self.assertEqual(mock_chat.call_count, 2)

    @patch("moduli.cervello.chat_ollama", return_value="Why Nokia Failed Again")
    @patch("moduli.cervello._fetch_trending", return_value="")
    @patch("moduli.topic_diversity.decide_mode", return_value="explore")
    def test_genera_topic_raises_after_all_duplicates(self, _mode, _trend, mock_chat):
        with self.assertRaises(RuntimeError):
            genera_topic(strategy={}, recent_topics=[])
        self.assertGreater(mock_chat.call_count, 1)


if __name__ == "__main__":
    unittest.main()
