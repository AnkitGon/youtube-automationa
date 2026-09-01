"""Test strategy_output — oggetto strategico strutturato."""
import unittest

from moduli.strategy_output import (
    attach_structured_strategy,
    build_structured_strategy,
    structured_summary_text,
)


class StrategyOutputTests(unittest.TestCase):
    def _insights(self, n=4):
        return {
            "video_count": n,
            "avg_ctr": 4.2,
            "avg_retention": 48.0,
            "suggested_target_minutes": 7,
            "winning_patterns": [{"pattern": "failure stories", "vs_channel_median": 12}],
            "losing_patterns": [{"pattern": "generic AI future", "vs_channel_median": -15}],
            "channel_confidence": {
                "level": "MEDIUM",
                "video_count": n,
                "optimization_mode": "weak_signals",
            },
            "title_pattern_analysis": {
                "winning_title_patterns": [{
                    "pattern_id": "why_x_failed",
                    "pattern_label": "Why X Failed",
                    "avg_ctr": 7.5,
                    "ctr_vs_channel": 2.1,
                    "sample_size": 2,
                }],
            },
            "hook_pattern_analysis": {
                "winning_hook_patterns": [{
                    "hook_id": "cold_open",
                    "hook_label": "Cold open",
                    "retention_vs_channel": 8,
                    "sample_size": 2,
                }],
            },
            "thumbnail_pattern_analysis": {
                "winning_traits": [{
                    "dimension": "contrast",
                    "value": "high",
                    "avg_ctr": 6.0,
                    "ctr_vs_channel": 1.5,
                    "sample_size": 2,
                }],
            },
            "publish_timing_analysis": {
                "recommended_hours_utc": [14, 20],
                "sufficient_evidence": False,
            },
            "experimentation": {"pending_experiments": 1, "promoted_experiments": 0, "recent": []},
        }

    def test_build_structured_has_required_keys(self):
        strategy = {
            "topic_focus": "AI chips, failure stories",
            "content_format": "case study",
            "avoid_patterns": "generic AI future predictions",
            "target_minutes": 8,
            "notes": "Double down on hardware failures",
            "_winning_patterns": [{"pattern": "failure stories"}],
            "_losing_patterns": [{"pattern": "generic AI future"}],
        }
        st = build_structured_strategy(
            strategy,
            self._insights(),
            state={"best_hours_utc": [14, 20]},
            profiles=[{"video_id": "v1"}, {"video_id": "v2"}],
        )
        for key in (
            "topic_focus", "winning_patterns", "losing_patterns", "avoid_patterns",
            "title_patterns", "hook_patterns", "thumbnail_patterns", "preferred_formats",
            "preferred_duration", "best_hours_utc", "exploration_ratio", "confidence",
            "sample_size", "notes", "evidence_video_ids",
        ):
            self.assertIn(key, st, msg=key)
        self.assertIsInstance(st["topic_focus"], list)
        self.assertIn("AI chips", st["topic_focus"][0])
        self.assertEqual(st["preferred_duration"], 8)
        self.assertEqual(st["confidence"], "medium")
        self.assertEqual(st["sample_size"], 4)
        self.assertIn("generic AI future predictions", st["avoid_patterns"])
        self.assertTrue(st["title_patterns"])
        self.assertEqual(st["best_hours_utc"], [14, 20])

    def test_attach_preserves_legacy_fields(self):
        strategy = {"topic_focus": "robotics", "avoid_patterns": "listicles"}
        out = attach_structured_strategy(strategy, self._insights(2))
        self.assertEqual(out["topic_focus"], "robotics")
        self.assertIn("structured", out)
        self.assertEqual(out["_confidence"], "medium")
        self.assertEqual(out["_sample_size"], 2)

    def test_summary_text(self):
        st = build_structured_strategy(
            {"topic_focus": "chips", "notes": "test"},
            self._insights(1),
        )
        text = structured_summary_text(st)
        self.assertIn("Confidence", text)
        self.assertIn("chips", text)


if __name__ == "__main__":
    unittest.main()
