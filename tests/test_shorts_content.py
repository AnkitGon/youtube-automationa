"""Tests for Shorts content validation."""

import unittest

from moduli.shorts.config import ShortsConfig
from moduli.shorts.content import _ensure_script_starts_with_hook, _validate_structure, run_shorts_content_gate
from moduli.shorts.visuals import refine_segment_visuals, refine_visual_segments, segment_search_ready


def _sample_content(**overrides):
    base = {
        "title": "Why Nokia Lost the Smartphone War",
        "hook": "Nokia had 50% market share — then one decision changed everything.",
        "script": (
            "Nokia had 50% market share — then one decision changed everything. "
            "In 2007 Apple launched the iPhone and Nokia dismissed touchscreens as a fad. "
            "They doubled down on Symbian while competitors moved fast. "
            "By 2013 Nokia sold its phone division to Microsoft. "
            "The lesson: ignoring platform shifts is fatal in tech."
        ),
        "angle": "platform shift blindness",
        "key_claims": ["Nokia ignored touchscreen trend", "Symbian bet failed"],
        "payoff": "Platform shifts kill market leaders who hesitate",
        "description": "The real reason Nokia collapsed",
        "tags": ["nokia", "tech", "business"],
        "hashtags": ["#Shorts"],
        "visual_segments": [
            {
                "text": "Nokia had 50% market share before one decision changed everything.",
                "keywords": ["nokia phone", "old mobile"],
                "visual_intent": "vintage Nokia mobile phones on desk",
                "duration_hint": 3,
            },
            {
                "text": "Apple launched the iPhone and Nokia dismissed touchscreens as a fad.",
                "keywords": ["iphone", "touchscreen smartphone"],
                "visual_intent": "person using smartphone touchscreen",
                "duration_hint": 3,
            },
        ],
        "target_duration_seconds": 35,
        "source_type": "longform_angle",
    }
    base.update(overrides)
    return base


class ShortsContentTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ShortsConfig(min_duration=20, max_duration=60)
        self.concept = {"topic": "Nokia", "angle": "failure", "source_topic": "How Nokia Lost"}

    def test_valid_content_passes_gate(self):
        content = _sample_content()
        ok, errors = run_shorts_content_gate(content, self.concept, self.cfg)
        self.assertTrue(ok, errors)

    def test_banned_opener_fails(self):
        content = _sample_content(
            hook="Hey guys welcome back",
            script="Hey guys welcome back to the channel. " + _sample_content()["script"],
        )
        errors = _validate_structure(content, self.cfg)
        self.assertTrue(any("banned" in e for e in errors))

    def test_summary_rejected(self):
        content = _sample_content(
            title="How Nokia Lost — in 60 seconds",
            script="Quick summary of How Nokia Lost in 60 seconds. " + _sample_content()["script"][:100],
        )
        ok, errors = run_shorts_content_gate(content, self.concept, self.cfg)
        self.assertFalse(ok)
        self.assertTrue(any("summary" in e.lower() or "dedup" in e.lower() or "short" in e.lower() for e in errors))

    def test_missing_visual_segments(self):
        content = _sample_content(visual_segments=[])
        errors = _validate_structure(content, self.cfg)
        self.assertTrue(any("visual" in e for e in errors))

    def test_hook_prepended_when_missing_from_opening(self):
        hook = "Your laptop is wasting power on AI."
        body = (
            "Small models run locally and use a fraction of the energy that cloud APIs need. "
            "They fit on consumer hardware and respond in milliseconds without sending data anywhere. "
            "That combination is why edge AI is winning for everyday tasks."
        )
        fixed = _ensure_script_starts_with_hook(_sample_content(hook=hook, script=body))
        self.assertTrue(fixed["script"].startswith(hook))
        ok, errors = run_shorts_content_gate(fixed, self.concept, self.cfg)
        self.assertTrue(ok, errors)

    def test_abstract_keywords_auto_fixed(self):
        content = _sample_content(
            visual_segments=[
                {
                    "text": "Nokia had 50% market share before one decision changed everything.",
                    "keywords": ["technology", "innovation"],
                    "visual_intent": "",
                },
                {
                    "text": "Apple launched the iPhone and Nokia dismissed touchscreens as a fad.",
                    "keywords": ["digital transformation", "future tech"],
                    "visual_intent": "",
                },
            ],
        )
        fixed = refine_visual_segments(content)
        for seg in fixed["visual_segments"]:
            self.assertTrue(segment_search_ready(seg), seg)
        ok, errors = run_shorts_content_gate(fixed, self.concept, self.cfg)
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
