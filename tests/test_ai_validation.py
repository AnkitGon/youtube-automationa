"""Test validazione risposte AI."""
import json
import unittest

from moduli.ai_validation import (
    AIResponseError,
    CONTENT_REQUIRED_FIELDS,
    clean_topic_response,
    contains_banned_reasoning,
    fetch_json_with_retries,
    parse_content_json,
    parse_json_object,
)


class AIValidationTests(unittest.TestCase):
    def test_rejects_thinking_process(self):
        self.assertTrue(contains_banned_reasoning("Here's a thinking process:\n1. Analyze"))

    def test_rejects_analysis_reasoning_labels(self):
        self.assertTrue(contains_banned_reasoning("Analysis:\nPick a topic"))
        self.assertTrue(contains_banned_reasoning("Reasoning:\nBecause..."))

    def test_parse_json_strips_fence(self):
        payload = {
            "title": "T",
            "description": "D",
            "tags": ["a"],
            "script": "word " * 200,
            "video_keywords": ["x"],
        }
        raw = f"```json\n{json.dumps(payload)}\n```"
        data = parse_content_json(raw)
        self.assertEqual(data["title"], "T")

    def test_parse_json_rejects_prose_wrapper(self):
        with self.assertRaises(AIResponseError):
            parse_json_object(
                "Here's a thinking process:\n\n1. Analyze...\n"
                '{"title": "T", "description": "D", "tags": [], "script": "x", "video_keywords": []}'
            )

    def test_parse_json_missing_fields(self):
        with self.assertRaises(AIResponseError) as ctx:
            parse_content_json('{"title": "only title"}')
        self.assertIn("missing required fields", str(ctx.exception))

    def test_fetch_json_retries(self):
        calls = {"n": 0}
        good = {
            "title": "T",
            "description": "D",
            "tags": ["a"],
            "script": "word " * 200,
            "video_keywords": ["k"],
        }

        def fetch():
            calls["n"] += 1
            if calls["n"] == 1:
                return "Reasoning: planning..."
            return json.dumps(good)

        data = fetch_json_with_retries(
            fetch, required_fields=CONTENT_REQUIRED_FIELDS, max_attempts=3,
        )
        self.assertEqual(data["title"], "T")
        self.assertEqual(calls["n"], 2)

    def test_clean_topic_strips_quotes_and_markdown(self):
        topic = clean_topic_response('"Why Nokia Failed in Smartphones"')
        self.assertEqual(topic, "Why Nokia Failed in Smartphones")

    def test_clean_topic_rejects_reasoning(self):
        with self.assertRaises(AIResponseError):
            clean_topic_response("Here's a thinking process:\nNokia story")

    def test_clean_topic_rejects_markdown(self):
        with self.assertRaises(AIResponseError):
            clean_topic_response("**Why Nokia Failed**")

    def test_clean_topic_from_json_field(self):
        topic = clean_topic_response('{"topic": "TSMC Arizona Fab Delays"}')
        self.assertEqual(topic, "TSMC Arizona Fab Delays")


if __name__ == "__main__":
    unittest.main()
