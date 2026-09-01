"""Test isolati per OpenRouter: content vs reasoning e json_mode."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from moduli import ai_client, cervello


class OpenRouterContentExtractionTests(unittest.TestCase):
    def test_message_content_text_ignores_reasoning_field(self):
        msg = {
            "content": "How Robots Are Replacing Jobs",
            "reasoning": "Here's a thinking process:\n1. Analyze...",
        }
        self.assertEqual(ai_client._message_content_text(msg), "How Robots Are Replacing Jobs")

    def test_message_content_text_empty_when_only_reasoning(self):
        msg = {
            "content": None,
            "reasoning": "Here's a thinking process:\n1. Analyze...",
        }
        self.assertIsNone(ai_client._message_content_text(msg))

    def test_openrouter_plain_text_disables_reasoning_and_no_json_format(self):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{
                    "message": {"content": "Hello", "reasoning": "thinking..."},
                    "finish_reason": "stop",
                }],
            }
            resp.raise_for_status = MagicMock()
            return resp

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/model"}), \
             patch("moduli.ai_client.requests.post", side_effect=fake_post):
            result = ai_client.chat_ollama("Reply with only: Hello", max_tokens=64)

        self.assertEqual(result, "Hello")
        self.assertNotIn("response_format", captured["payload"])
        self.assertEqual(captured["payload"]["reasoning"], {"effort": "none"})

    def test_openrouter_json_mode_uses_structured_output(self):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{
                    "message": {
                        "content": '{"title": "T", "tags": ["a"]}',
                        "reasoning": "planning json...",
                    },
                    "finish_reason": "stop",
                }],
            }
            resp.raise_for_status = MagicMock()
            return resp

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/model"}), \
             patch("moduli.ai_client.requests.post", side_effect=fake_post):
            result = ai_client.chat_ollama("give json", max_tokens=500, json_mode=True)

        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["payload"]["reasoning"], {"effort": "none"})
        parsed = json.loads(result)
        self.assertEqual(parsed["title"], "T")

    def test_openrouter_model_fallback_chain(self):
        models_tried = []

        def fake_post(url, headers=None, json=None, timeout=None):
            models_tried.append(json["model"])
            resp = MagicMock()
            if json["model"] == "primary/fail":
                resp.status_code = 503
                resp.raise_for_status = MagicMock()
                return resp
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            }
            resp.raise_for_status = MagicMock()
            return resp

        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_MODEL": "primary/fail",
            "OPENROUTER_FALLBACK_MODELS": "backup/ok",
        }), patch("moduli.ai_client.requests.post", side_effect=fake_post), \
             patch("moduli.ai_client.time.sleep"):
            result = ai_client._openrouter([{"role": "user", "content": "x"}])

        self.assertEqual(result, "ok")
        self.assertEqual(models_tried[0], "primary/fail")
        self.assertIn("backup/ok", models_tried)


class ParseJsonTests(unittest.TestCase):
    def test_parse_json_strips_markdown_fence(self):
        payload = {
            "title": "T",
            "description": "D",
            "tags": ["a"],
            "script": " ".join(["word"] * 200),
            "video_keywords": ["x"],
        }
        raw = f"```json\n{json.dumps(payload)}\n```"
        data = cervello._parse_json(raw)
        self.assertEqual(data["title"], "T")

    def test_parse_json_rejects_prose(self):
        with self.assertRaises(ValueError):
            cervello._parse_json("Here's a thinking process:\n\n1. Analyze...")


class LiveOpenRouterTests(unittest.TestCase):
    """Chiamate reali — saltate se manca OPENROUTER_API_KEY."""

    @classmethod
    def setUpClass(cls):
        from dotenv import load_dotenv
        load_dotenv()
        cls.has_key = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
        cls.model = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")

    def setUp(self):
        if os.environ.get("RUN_LIVE_API_TESTS", "").lower() not in {"1", "true", "yes"}:
            self.skipTest("Set RUN_LIVE_API_TESTS=1 to run live OpenRouter tests")
        if not self.has_key:
            self.skipTest("OPENROUTER_API_KEY not configured")

    def test_live_plain_text_not_reasoning(self):
        with patch.dict(os.environ, {"AI_SERVICE": "openrouter", "OPENROUTER_MODEL": self.model}):
            result = ai_client.chat_ollama("Reply with only the word: Hello", max_tokens=64)
        self.assertTrue(result)
        self.assertNotIn("thinking process", result.lower())
        self.assertNotIn("analyze the request", result.lower())
        self.assertLessEqual(len(result.split()), 10)

    def test_live_json_mode_returns_valid_json(self):
        with patch.dict(os.environ, {"AI_SERVICE": "openrouter", "OPENROUTER_MODEL": self.model}):
            result = ai_client.chat_ollama(
                'Return JSON only: {"title":"HELLO","tags":["test"]}',
                max_tokens=500,
                json_mode=True,
            )
        data = json.loads(result)
        self.assertIn("title", data)
        self.assertIsInstance(data.get("tags"), list)


if __name__ == "__main__":
    unittest.main()
