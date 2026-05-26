import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RuntimeSafetyTests(unittest.TestCase):
    def test_authorized_chat_ids_are_fail_closed(self):
        from moduli import telegram_handler as tg

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(tg._authorized_chat_ids(), set())

        with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "123", "TELEGRAM_ALLOWED_CHAT_IDS": "456, 789"}):
            self.assertEqual(tg._authorized_chat_ids(), {"123", "456", "789"})

    def test_llm_channel_update_is_queued_for_confirmation(self):
        from moduli import telegram_handler as tg

        state = {}
        clean, added, saved, removed, results = tg._execute_actions(
            "Ok [AGGIORNA_DESC: nuova descrizione]",
            state,
        )

        self.assertEqual(clean, "Ok")
        self.assertEqual(added, [])
        self.assertEqual(saved, [])
        self.assertEqual(removed, [])
        self.assertEqual(len(results), 1)
        self.assertIn("pending_actions", state)
        self.assertEqual(state["pending_actions"][0]["type"], "AGGIORNA_DESC")
        self.assertEqual(state["pending_actions"][0]["payload"], "nuova descrizione")

    def test_confirmed_force_now_sets_immediate_publish(self):
        from moduli import telegram_handler as tg

        state = {}
        result = tg._execute_confirmed_action(
            state,
            {"type": "FORZA_ORA", "payload": "AI topic"},
        )

        self.assertIn("pipeline immediata", result)
        self.assertTrue(state["force_run"])
        self.assertTrue(state["publish_immediately"])
        self.assertEqual(state["topic_queue"], ["AI topic"])

    def test_pipeline_passes_immediate_to_upload(self):
        import importlib

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "123",
            "AI_SERVICE": "openrouter",
            "OPENROUTER_API_KEY": "key",
            "PEXELS_API_KEY": "pexels",
        }, clear=False):
            agent = importlib.import_module("agent")

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                Path("state.json").write_text("{}", encoding="utf-8")
                calls = {}

                def fake_audio(_script, output_path):
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(b"audio")

                def fake_video(_audio, _keywords, _clips, output_path):
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(b"video")

                def fake_thumb(_title, output_path, **_kwargs):
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(b"thumb")

                def fake_publish(*args, **kwargs):
                    calls["args"] = args
                    calls["kwargs"] = kwargs
                    return "video123"

                with patch.object(agent, "leggi_performance", return_value=[]), \
                    patch.object(agent, "calcola_strategia", return_value={}), \
                    patch.object(agent, "genera_topic", return_value="topic"), \
                    patch.object(agent, "genera_contenuto", return_value={
                        "title": "Title",
                        "description": "Desc",
                        "tags": ["tag"],
                        "script": "hello world",
                        "video_keywords": ["office"],
                    }), \
                    patch.object(agent, "genera_audio", side_effect=fake_audio), \
                    patch.object(agent, "scarica_clip", return_value="clip.mp4"), \
                    patch.object(agent, "monta_video", side_effect=fake_video), \
                    patch.object(agent, "genera_thumbnail", side_effect=fake_thumb), \
                    patch.object(agent, "pubblica_video", side_effect=fake_publish), \
                    patch.object(agent, "notify_step"), \
                    patch.object(agent, "notify_start"), \
                    patch.object(agent, "notify_done"), \
                    patch.object(agent, "notify_error"), \
                    patch.object(agent, "notify_analytics"):
                    agent.run_pipeline({"publish_immediately": True})

                self.assertIsNone(calls["args"][3])
                self.assertTrue(calls["kwargs"]["immediate"])
                self.assertEqual(calls["kwargs"]["privacy_status"], "public")
            finally:
                os.chdir(old_cwd)

    def test_model_json_parser_uses_first_complete_object(self):
        from moduli.cervello import _parse_json

        data = _parse_json(
            'intro {"title":"T","description":"D","tags":["a"],'
            '"script":"S","video_keywords":["office"]} trailing {"bad": true}'
        )

        self.assertEqual(data["title"], "T")
        self.assertEqual(data["video_keywords"], ["office"])

    def test_autoscheduling_uses_best_performance_hours(self):
        import importlib

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "123",
            "AI_SERVICE": "openrouter",
            "OPENROUTER_API_KEY": "key",
            "PEXELS_API_KEY": "pexels",
        }, clear=False):
            agent = importlib.import_module("agent")
        state = {"videos_per_day": 2}
        agent._update_best_hours(state, [
            {"published_hour_utc": 8, "views": 10, "ctr_percent": 1, "duration_seconds": 100, "avg_view_duration_seconds": 20},
            {"published_hour_utc": 20, "views": 1000, "ctr_percent": 8, "duration_seconds": 100, "avg_view_duration_seconds": 70},
            {"published_hour_utc": 14, "views": 700, "ctr_percent": 6, "duration_seconds": 100, "avg_view_duration_seconds": 50},
        ])

        self.assertEqual(state["best_hours_utc"], [14, 20])


if __name__ == "__main__":
    unittest.main()
