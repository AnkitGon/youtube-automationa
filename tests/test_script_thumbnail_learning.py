"""Test script e thumbnail learning."""
import unittest
from unittest.mock import patch

from moduli.script_optimization import (
    analyze_script_optimization,
    extract_script_traits,
    script_guidance_block,
)
from moduli.thumbnail_learning import (
    analyze_thumbnail_patterns,
    classify_thumbnail_traits,
    thumbnail_guidance_block,
)


class ScriptOptimizationTests(unittest.TestCase):
    def test_extract_script_traits(self):
        script = (
            "In 2007, a small team made a bet that would change everything. "
            "They had no idea what was coming. "
            "Subscribe now if you want more stories like this."
        )
        traits = extract_script_traits(script)
        self.assertEqual(traits["story_vs_explainer"], "story")
        self.assertIn(traits["cta_placement"], ("early", "mid", "late"))

    def test_insufficient_data_no_claims(self):
        analysis = analyze_script_optimization([])
        self.assertFalse(analysis["has_data"])
        with patch("moduli.performance.carica_profili", return_value=[]):
            block = script_guidance_block({}, {})
        self.assertIn("Insufficient published videos", block)

    def test_recommendations_need_samples(self):
        profiles = [
            {
                "video_id": "a",
                "metrics": {"retention_percent": 60, "duration_seconds": 480, "views": 100},
                "content_metadata": {
                    "pacing": "fast", "hook_strength": "aggressive",
                    "script_traits": {"pacing": "fast", "story_vs_explainer": "story"},
                },
            },
            {
                "video_id": "b",
                "metrics": {"retention_percent": 55, "duration_seconds": 480, "views": 90},
                "content_metadata": {
                    "pacing": "fast", "hook_strength": "aggressive",
                    "script_traits": {"pacing": "fast", "story_vs_explainer": "story"},
                },
            },
            {
                "video_id": "c",
                "metrics": {"retention_percent": 30, "duration_seconds": 600, "views": 50},
                "content_metadata": {
                    "pacing": "slow", "hook_strength": "soft",
                    "script_traits": {"pacing": "slow", "story_vs_explainer": "explainer"},
                },
            },
        ]
        analysis = analyze_script_optimization(profiles)
        self.assertTrue(analysis["has_data"])


class ThumbnailLearningTests(unittest.TestCase):
    def test_classify_traits(self):
        traits = classify_thumbnail_traits(
            "Close-up portrait of a person, dramatic lighting, high contrast, bold colors",
            "AI FAILS",
            "tense",
        )
        self.assertEqual(traits["subject_type"], "human_face")
        self.assertEqual(traits["shot_type"], "close_up")
        self.assertEqual(traits["visual_style"], "dramatic")
        self.assertEqual(traits["phrase_style"], "short_caps")

    @patch("moduli.performance.carica_profili", return_value=[])
    def test_no_success_without_data(self, _mock_profiles):
        block = thumbnail_guidance_block({})
        self.assertTrue(
            "Insufficient data" in block or "NOT ENOUGH DATA" in block
        )
        self.assertIn("Do NOT claim", block)

    def test_winning_traits_need_min_samples(self):
        profiles = [
            {
                "video_id": "v1",
                "title": "A",
                "metrics": {"ctr_percent": 8.0},
                "content_metadata": {
                    "thumbnail_traits": {"subject_type": "human_face", "contrast": "high"},
                    "thumbnail_description_snippet": "close-up face dramatic",
                    "thumbnail_concept": "AI CRASH",
                },
            },
            {
                "video_id": "v2",
                "title": "B",
                "metrics": {"ctr_percent": 2.0},
                "content_metadata": {
                    "thumbnail_traits": {"subject_type": "object", "contrast": "low"},
                },
            },
        ]
        analysis = analyze_thumbnail_patterns(profiles)
        self.assertTrue(analysis["has_data"])
        # n=1 per trait — should NOT claim sufficient evidence
        self.assertFalse(analysis["sufficient_evidence"])
        block = thumbnail_guidance_block({})
        self.assertTrue(
            "NOT ENOUGH DATA" in block or "Insufficient" in block
        )


if __name__ == "__main__":
    unittest.main()
