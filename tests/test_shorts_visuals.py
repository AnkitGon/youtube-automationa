"""Tests for Shorts visual clip acquisition."""

import unittest
from unittest.mock import patch

from moduli.shorts.visuals import _build_search_queries, _is_generic_query, acquire_segment_clips, parse_duration_seconds


class ShortsVisualsTests(unittest.TestCase):
    def test_rejects_generic_keywords(self):
        self.assertTrue(_is_generic_query("technology abstract"))
        self.assertTrue(_is_generic_query("business concept"))
        self.assertFalse(_is_generic_query("factory assembly line"))

    def test_build_queries_from_segment(self):
        seg = {
            "text": "Digital twins let factories simulate failures before they happen.",
            "keywords": ["factory", "computer simulation"],
            "visual_intent": "engineer at factory control screen",
        }
        queries = _build_search_queries(seg)
        self.assertTrue(any("factory" in q.lower() for q in queries))
        self.assertFalse(any("abstract" in q.lower() for q in queries))

    def test_parse_duration_seconds_accepts_suffix(self):
        self.assertEqual(parse_duration_seconds("8s"), 8.0)
        self.assertEqual(parse_duration_seconds("4 sec"), 4.0)
        self.assertEqual(parse_duration_seconds(3.5), 3.5)
        self.assertEqual(parse_duration_seconds("bad", default=2.0), 2.0)

    @patch("moduli.shorts.visuals.scarica_clips")
    def test_portrait_orientation_used(self, mock_scarica):
        mock_scarica.return_value = ["/tmp/clip1.mp4", "/tmp/clip2.mp4"]
        segs = [{
            "text": "Hospitals use MRI scanners every day.",
            "keywords": ["hospital", "MRI scanner"],
            "visual_intent": "MRI machine in hospital room",
            "duration_hint": 3,
        }]
        result = acquire_segment_clips(segs)
        mock_scarica.assert_called()
        self.assertEqual(mock_scarica.call_args.kwargs.get("orientation"), "portrait")
        self.assertTrue(result[0]["clip_path"])


if __name__ == "__main__":
    unittest.main()
