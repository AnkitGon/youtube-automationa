"""Test validazione qualità topic."""
import unittest

from moduli.topic_quality import (
    TopicQualityError,
    assert_topic_quality,
    validate_topic_quality,
)


class TopicQualityTests(unittest.TestCase):
    def test_valid_concrete_topic(self):
        ok, cleaned, reason = validate_topic_quality("RISC-V Chip Wars Escalation")
        self.assertTrue(ok)
        self.assertEqual(cleaned, "RISC-V Chip Wars Escalation")
        self.assertEqual(reason, "")

    def test_word_count_bounds(self):
        ok, _, reason = validate_topic_quality("AI")
        self.assertFalse(ok)
        self.assertTrue("too short" in reason or "generic" in reason)

        ok, _, reason = validate_topic_quality(
            "The Complete Comprehensive History Of Every Major Semiconductor Company Failure Story Ever Told"
        )
        self.assertFalse(ok)
        self.assertIn("too long", reason)

    def test_rejects_generic(self):
        ok, _, reason = validate_topic_quality("The Future of AI")
        self.assertFalse(ok)
        self.assertIn("generic", reason)

        ok, _, reason = validate_topic_quality("AI News and Trends")
        self.assertFalse(ok)
        self.assertIn("generic", reason)

    def test_rejects_reasoning(self):
        ok, _, reason = validate_topic_quality(
            "Here's a thinking process: Nokia smartphone collapse"
        )
        self.assertFalse(ok)
        self.assertIn("reasoning", reason)

    def test_rejects_analysis_and_reasoning_labels(self):
        ok, _, reason = validate_topic_quality("Analysis:\nNokia smartphone collapse")
        self.assertFalse(ok)
        self.assertIn("reasoning", reason)

        ok, _, reason = validate_topic_quality("Reasoning:\nPick Blockbuster")
        self.assertFalse(ok)
        self.assertIn("reasoning", reason)

    def test_rejects_markdown(self):
        ok, _, reason = validate_topic_quality("**Why Nokia Failed**")
        self.assertFalse(ok)
        self.assertIn("markdown", reason)

    def test_extracts_topic_from_json(self):
        ok, cleaned, reason = validate_topic_quality('{"topic": "Nokia Smartphone Collapse Story"}')
        self.assertTrue(ok)
        self.assertEqual(cleaned, "Nokia Smartphone Collapse Story")
        self.assertEqual(reason, "")

        topic = assert_topic_quality('{"topic": "TSMC Arizona Fab Delays"}')
        self.assertEqual(topic, "TSMC Arizona Fab Delays")

    def test_assert_raises(self):
        with self.assertRaises(TopicQualityError):
            assert_topic_quality("AI technology trends")


if __name__ == "__main__":
    unittest.main()
