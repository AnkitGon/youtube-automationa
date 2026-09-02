"""Test validazione risposte AI."""
import json
import unittest

from moduli.ai_validation import (
    AIResponseError,
    CONTENT_REQUIRED_FIELDS,
    clean_topic_response,
    contains_banned_reasoning,
    fetch_json_with_retries,
    fill_missing_content_fields,
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

    def test_parse_json_fills_video_keywords_from_visual_segments(self):
        payload = {
            "title": "Nokia Fall",
            "description": "Story of Nokia decline in smartphones.",
            "tags": ["nokia", "phones"],
            "script": "word " * 200,
            "visual_segments": [
                {"text_excerpt": "intro", "keyword": "vintage mobile phone", "visual_type": "stock"},
                {"text_excerpt": "market", "keyword": "smartphone market chart", "visual_type": "chart"},
            ],
        }
        data = parse_content_json(json.dumps(payload), topic="Nokia smartphone failure")
        self.assertEqual(
            data["video_keywords"][:2],
            ["vintage mobile phone", "smartphone market chart"],
        )

    def test_fill_video_keywords_from_tags(self):
        data = fill_missing_content_fields(
            {
                "title": "AI Agents",
                "tags": ["ai agents", "automation"],
                "script": "x",
            },
            topic="AI agents",
        )
        self.assertEqual(data["video_keywords"], ["ai agents", "automation"])

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
