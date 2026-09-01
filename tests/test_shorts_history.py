"""Tests for Shorts history fingerprinting."""

import os
import tempfile
import unittest
from unittest.mock import patch

from moduli.shorts.history import (
    content_fingerprint,
    find_duplicate,
    normalize_text,
    record_entry,
    similarity,
)


class ShortsHistoryTests(unittest.TestCase):
    def test_fingerprint_stable(self):
        script = "Hello world this is a test script."
        self.assertEqual(content_fingerprint(script), content_fingerprint(script))
        self.assertNotEqual(
            content_fingerprint(script),
            content_fingerprint("Different script entirely."),
        )

    def test_normalize_text(self):
        self.assertEqual(normalize_text("  Hello   World  "), "hello world")

    def test_hook_similarity_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist_file = os.path.join(tmp, "shorts_history.json")
            with patch("moduli.shorts.history.HISTORY_FILE", hist_file):
                with patch("moduli.shorts.config.load_config") as mock_cfg:
                    mock_cfg.return_value.similarity_threshold = 0.78
                    record_entry(
                        topic="AI chips",
                        angle="GPU dominance",
                        hook="Nvidia owns the AI chip market completely",
                        title="Nvidia AI Dominance",
                        script="Nvidia dominates AI chips with CUDA ecosystem lock-in.",
                    )
                    dup, _, reason = find_duplicate(
                        topic="AI chips",
                        hook="Nvidia owns the AI chip market entirely",
                    )
                    self.assertTrue(dup)


if __name__ == "__main__":
    unittest.main()
