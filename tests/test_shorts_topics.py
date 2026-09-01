"""Tests for Shorts topic batch planner and dedup."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from moduli.shorts.history import (
    content_fingerprint,
    find_duplicate,
    is_summary_of,
    record_entry,
    similarity,
)
from moduli.shorts.topics import _diversity_penalty, plan_daily_batch


class ShortsTopicsTests(unittest.TestCase):
    def test_similarity_overlap(self):
        a = "Nokia smartphone market collapse"
        b = "Nokia phone market failure story"
        self.assertGreater(similarity(a, b), 0.3)

    def test_summary_detection(self):
        self.assertTrue(is_summary_of("How Nokia Lost Everything", "Nokia in 60 seconds summary"))
        self.assertFalse(is_summary_of("How Nokia Lost Everything", "The one decision that killed Nokia"))

    def test_dedup_blocks_identical_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_file = os.path.join(tmp, "shorts_history.json")
            with patch("moduli.shorts.history.HISTORY_FILE", hist_file):
                record_entry(
                    topic="Test topic",
                    angle="Test angle",
                    hook="Hook line",
                    title="Test Title",
                    script="This is a unique script for testing dedup.",
                )
                dup, _, reason = find_duplicate(
                    topic="Different",
                    script="This is a unique script for testing dedup.",
                )
                self.assertTrue(dup)
                self.assertIn("fingerprint", reason)

    def test_dedup_allows_different_angle(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_file = os.path.join(tmp, "shorts_history.json")
            with patch("moduli.shorts.history.HISTORY_FILE", hist_file):
                record_entry(
                    topic="Nokia collapse",
                    angle="Market share loss",
                    hook="Nokia was unstoppable",
                    title="Why Nokia Failed",
                    script="Nokia dominated mobile phones for years before a critical mistake.",
                )
                dup, _, _ = find_duplicate(
                    topic="Nokia collapse",
                    angle="The Symbian decision",
                    hook="One OS choice destroyed them",
                    title="Nokia's Fatal OS Bet",
                    script="While competitors adopted touchscreens Nokia doubled down on Symbian.",
                )
                self.assertFalse(dup)

    def test_diversity_penalty(self):
        selected = [{"topic": "AI chips", "angle": "Nvidia dominance", "hook_hint": "GPU wars"}]
        cand = {"topic": "AI chips market", "angle": "Nvidia monopoly", "hook_hint": "GPU battle"}
        self.assertGreater(_diversity_penalty(cand, selected), 0)

    @patch("moduli.shorts.topics._ai_batch_candidates", return_value=[])
    @patch("moduli.shorts.topics._trending_candidates", return_value=[])
    @patch("moduli.shorts.topics._longform_angle_candidates")
    @patch("moduli.shorts.topics._evergreen_candidates")
    @patch("moduli.shorts.topics._historical_followup", return_value=[])
    def test_batch_returns_distinct(self, mock_hist, mock_evergreen, mock_lf, _mock_trend, _mock_ai):
        mock_lf.return_value = [
            {"topic": "Nokia smartphone collapse", "angle": "Market share loss", "hook_hint": "Nokia dominated phones", "source_type": "longform_angle", "source_topic": "", "source_longform_video_id": ""},
            {"topic": "Blockbuster Netflix disruption", "angle": "Digital pivot failure", "hook_hint": "Late fees killed them", "source_type": "longform_angle", "source_topic": "", "source_longform_video_id": ""},
            {"topic": "Kodak digital photography", "angle": "Innovation paradox", "hook_hint": "They invented digital", "source_type": "longform_angle", "source_topic": "", "source_longform_video_id": ""},
        ]
        mock_evergreen.return_value = []
        with tempfile.TemporaryDirectory() as tmp:
            hist_file = os.path.join(tmp, "shorts_history.json")
            with patch("moduli.shorts.history.HISTORY_FILE", hist_file):
                from moduli.shorts.config import ShortsConfig
                batch = plan_daily_batch(count=3, config=ShortsConfig(per_day=3))
                topics = {c["topic"] for c in batch}
                self.assertEqual(len(batch), 3)
                self.assertEqual(len(topics), 3)


if __name__ == "__main__":
    unittest.main()
