"""Regression tests for long-form content generation resilience."""

import json
import unittest
from unittest.mock import patch

from moduli.ai_validation import parse_content_json
from moduli.content_quality import prepare_content_for_validation


class GeneraContenutoResilienceTests(unittest.TestCase):
    def test_parse_fills_missing_video_keywords(self):
        payload = {
            "title": "Mars Colony Collapse",
            "description": "Why the mission failed.",
            "tags": ["mars", "space"],
            "script": "word " * 400,
            "visual_segments": [
                {"keyword": "mars habitat exterior", "text_excerpt": "intro"},
                {"keyword": "rocket launch pad", "text_excerpt": "launch"},
            ],
        }
        data = parse_content_json(json.dumps(payload), topic="Mars colony failure")
        self.assertGreaterEqual(len(data["video_keywords"]), 2)

    def test_prepare_adds_keywords_from_segments(self):
        content = prepare_content_for_validation(
            {
                "title": "Test",
                "description": "Desc",
                "tags": ["mars"],
                "script": "word " * 50,
                "visual_segments": [{"keyword": "mars rover", "text_excerpt": "x"}],
            },
            topic="Mars",
        )
        self.assertIn("mars rover", content["video_keywords"])


if __name__ == "__main__":
    unittest.main()
