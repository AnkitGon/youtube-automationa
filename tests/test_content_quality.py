"""Tests for content quality and research modules."""

import unittest

from moduli.content_quality import (
    detect_ai_filler,
    prepare_content_for_validation,
    run_content_quality_gate,
    validate_title_thumbnail_pair,
    validate_viewer_value,
)
from moduli.research import score_topic_candidate, infer_topic_source


class ContentQualityTests(unittest.TestCase):
    def test_detect_ai_filler(self):
        bad = (
            "In today's rapidly evolving world, imagine this. "
            "But here's the thing. Let's dive in without further ado."
        )
        issues = detect_ai_filler(bad)
        self.assertGreaterEqual(len(issues), 2)

    def test_title_thumbnail_pair_complement(self):
        errs = validate_title_thumbnail_pair(
            "How Nokia Lost the Smartphone War",
            "TOO LATE",
        )
        self.assertEqual(errs, [])
        errs2 = validate_title_thumbnail_pair(
            "How Nokia Lost the Smartphone War",
            "WHY NOKIA FAILED",
        )
        self.assertTrue(errs2)

    def test_viewer_value_weak_script(self):
        content = {
            "title": "How Nokia Lost the Smartphone War",
            "thumbnail_phrase": "TOO LATE",
            "script": "Nokia was a company. Phones existed. The end.",
        }
        ok, errors, score = validate_viewer_value(content, "How Nokia Lost the Smartphone War")
        self.assertFalse(ok)
        self.assertLess(score, 0.6)

    def test_quality_gate_accepts_substantive_script(self):
        script = (
            "Nokia dominated mobile phones for a decade because they controlled distribution "
            "and hardware margins across Europe. When smartphones arrived, the company "
            "underestimated software ecosystems. Apple and Google built platforms while Nokia "
            "treated Symbian as sufficient. By 2013, market share collapsed because developers "
            "followed users, and users followed apps. The lesson is that platform shifts punish "
            "incumbents who optimize the old business model instead of the new user experience."
        ) * 8
        content = {
            "title": "How Nokia Lost the Smartphone War",
            "thumbnail_phrase": "TOO LATE",
            "script": script,
            "video_keywords": ["nokia phone vintage", "smartphone timeline", "mobile market chart"],
            "visual_segments": [
                {"keyword": "nokia phone vintage", "text_excerpt": "Nokia dominated"},
            ],
        }
        ok, errors = run_content_quality_gate(content, "How Nokia Lost the Smartphone War", {})
        self.assertTrue(ok, errors)

    def test_prepare_content_normalizes_line_breaks(self):
        raw = {
            "title": "Mars Colony Failure",
            "thumbnail_phrase": "TOO LATE",
            "description": "Why the mission failed.",
            "tags": ["mars", "space"],
            "script": "Line one.\n\nLine two.\nLine three.\nLine four.",
            "visual_segments": [{"keyword": "mars habitat", "text_excerpt": "Line one"}],
        }
        prepared = prepare_content_for_validation(raw, topic="Mars colony")
        self.assertNotIn("\n", prepared["script"])
        self.assertIn("video_keywords", prepared)

    def test_quality_gate_relaxes_on_late_attempt(self):
        script = (
            "Nokia was big.\n"
            "Apple arrived.\n"
            "Everything changed.\n"
            "Nokia failed.\n"
        ) * 30
        content = {
            "title": "How Nokia Lost the Smartphone War",
            "thumbnail_phrase": "TOO LATE",
            "script": script,
            "video_keywords": ["nokia phone", "smartphone timeline"],
            "visual_segments": [{"keyword": "nokia phone", "text_excerpt": "Nokia was big"}],
        }
        ok_strict, errors_strict = run_content_quality_gate(
            content, "How Nokia Lost the Smartphone War", {}, attempt=0,
        )
        ok_late, errors_late = run_content_quality_gate(
            content, "How Nokia Lost the Smartphone War", {}, attempt=4, max_attempts=5,
        )
        self.assertFalse(ok_strict)
        self.assertTrue(any("line breaks" in e or "short sentences" in e for e in errors_strict))
        self.assertTrue(ok_late, errors_late)


class ResearchTests(unittest.TestCase):
    def test_topic_source_tags(self):
        self.assertEqual(infer_topic_source({}, diversity_mode="explore"), "experiment")
        self.assertEqual(infer_topic_source({}, from_queue=True), "manual")

    def test_score_generic_penalty(self):
        low = score_topic_candidate("The Future of AI Revolution", {})
        high = score_topic_candidate("How Kodak Missed the Digital Camera Shift", {})
        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()
