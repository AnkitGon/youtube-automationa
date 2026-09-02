"""Test avoid_patterns — raccolta, prompt e validazione programmatica."""
import unittest

from moduli.avoid_patterns import (
    AvoidPatternError,
    assert_not_avoided,
    avoid_prompt_section,
    collect_avoid_patterns,
    find_avoid_match,
    validate_content_fields,
)
from moduli.cervello import _avoid_block, _topic_avoid_block, build_topic_prompt


class AvoidPatternsTests(unittest.TestCase):
    def test_collect_from_strategy_and_prefs(self):
        pats = collect_avoid_patterns(
            {"avoid_patterns": "generic AI future predictions; listicles"},
            {"argomenti_evitare": ["crypto scams"]},
        )
        self.assertIn("generic AI future predictions", pats)
        self.assertIn("listicles", pats)
        self.assertIn("crypto scams", pats)

    def test_find_match_substring_and_tokens(self):
        patterns = ["generic AI future predictions"]
        self.assertIsNotNone(
            find_avoid_match("The Future of AI: Predictions for 2027", patterns)
        )
        self.assertIsNone(find_avoid_match("Why Nokia Failed in 2007", patterns))

    def test_assert_raises(self):
        with self.assertRaises(AvoidPatternError):
            assert_not_avoided(
                "AI Future Predictions That Will Shock You",
                "title",
                {"avoid_patterns": "generic AI future predictions"},
            )

    def test_validate_content_fields(self):
        errors = validate_content_fields(
            {
                "title": "Generic AI Future Predictions for 2027",
                "script": "Opening about the future of AI predictions...",
                "thumbnail_phrase": "AI FUTURE",
                "thumbnail_description": "futuristic city skyline predicting AI future",
            },
            {"avoid_patterns": "generic AI future predictions"},
            {},
        )
        self.assertTrue(errors)
        self.assertTrue(any("title" in e for e in errors))

    def test_topic_prompt_includes_avoid_section(self):
        prompt = build_topic_prompt(
            strategy={"avoid_patterns": "generic AI future predictions"},
            pref={},
            recent_topics=[],
            rejected=[],
            trending_block="",
            diversity_block="EXPLOIT",
            subtheme="chips",
            angle="case study",
            fmt="analysis",
            historical_topics="- none",
        )
        self.assertIn("AVOID PATTERNS", prompt)
        self.assertIn("generic AI future predictions", prompt)

    def test_avoid_blocks_for_stages(self):
        strategy = {"avoid_patterns": "generic AI future predictions"}
        self.assertIn("generic AI future", _topic_avoid_block(strategy, {}))
        self.assertIn("generic AI future", _avoid_block(strategy, {}))
        title_block = avoid_prompt_section(strategy, stage="title")
        thumb_block = avoid_prompt_section(strategy, stage="thumbnail")
        self.assertIn("MANDATORY", title_block)
        self.assertIn("MANDATORY", thumb_block)

    def test_title_like_pattern_only_blocks_title_fields(self):
        strategy = {
            "_recent_underperformers": ["Your Phone Case That Fixes Itself by 2026"],
        }
        errors = validate_content_fields(
            {
                "title": "Why Mars Colony Plans Failed in 2026",
                "thumbnail_phrase": "TOO LATE",
                "script": (
                    "In 2026, your phone case might fix itself, but Mars colony plans "
                    "collapsed for a completely different reason involving budgets and radiation."
                ),
                "thumbnail_description": "Mars habitat exterior at sunset, documentary cinematic lighting",
            },
            strategy,
            {},
        )
        self.assertFalse(any("script opening" in e for e in errors))

    def test_preference_conflicts_filtered(self):
        pats = collect_avoid_patterns(
            {"avoid_patterns": ["video style: cinematic", "generic AI future predictions"]},
            {"stile_clip": "cinematic"},
        )
        self.assertNotIn("video style: cinematic", pats)
        self.assertIn("generic AI future predictions", pats)


if __name__ == "__main__":
    unittest.main()
