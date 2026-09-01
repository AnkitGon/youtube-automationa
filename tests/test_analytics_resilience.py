"""Test resilienza analytics — pipeline non deve crashare."""
import unittest
from unittest.mock import patch

from moduli.analytics import leggi_performance
from moduli.strategia import (
    ANALYTICS_UNAVAILABLE_NOTE,
    calcola_strategia,
    standard_strategy,
)


class AnalyticsResilienceTests(unittest.TestCase):
    def test_leggi_performance_returns_empty_on_api_error(self):
        with patch("moduli.analytics._leggi_performance_impl", side_effect=RuntimeError("quota exceeded")):
            rows = leggi_performance(n_video=5)
        self.assertEqual(rows, [])

    def test_calcola_strategia_empty_uses_standard_note(self):
        strat = calcola_strategia([])
        self.assertIn(ANALYTICS_UNAVAILABLE_NOTE, strat.get("notes", ""))

    def test_calcola_strategia_survives_sync_failure(self):
        perf = [{
            "video_id": "v1",
            "title": "Test",
            "views": 10,
            "ctr_percent": 2,
            "duration_seconds": 480,
            "avg_view_duration_seconds": 60,
        }]
        with patch("moduli.strategia.sync_profiles", side_effect=OSError("disk")):
            strat = calcola_strategia(perf)
        self.assertTrue(strat.get("topic_focus"))
        self.assertIn("notes", strat)

    def test_calcola_strategia_survives_analyze_failure(self):
        perf = [{
            "video_id": "v1",
            "title": "T",
            "views": 1,
            "ctr_percent": 1,
            "duration_seconds": 480,
            "avg_view_duration_seconds": 60,
            "published_at": "2026-08-28T12:00:00Z",
        }]
        with patch("moduli.strategia.analyze_performance", side_effect=ValueError("broken")), \
             patch("moduli.strategia.chat_ollama", side_effect=RuntimeError("AI down")):
            strat = calcola_strategia(perf)
        self.assertTrue(strat.get("topic_focus"))
        self.assertIn(ANALYTICS_UNAVAILABLE_NOTE, strat.get("notes", ""))

    def test_calcola_strategia_survives_llm_failure(self):
        perf = [{
            "video_id": "v1",
            "title": "Test Video",
            "views": 100,
            "ctr_percent": 5,
            "duration_seconds": 480,
            "avg_view_duration_seconds": 200,
            "published_at": "2026-08-28T12:00:00Z",
        }]
        with patch("moduli.strategia.chat_ollama", side_effect=RuntimeError("AI down")):
            strat = calcola_strategia(perf)
        self.assertTrue(strat.get("topic_focus"))
        self.assertIn("notes", strat)

    def test_standard_strategy_flag(self):
        strat = standard_strategy()
        self.assertTrue(strat.get("_analytics_fallback"))
        self.assertEqual(strat.get("notes"), ANALYTICS_UNAVAILABLE_NOTE)

    def test_calcola_strategia_never_raises(self):
        with patch("moduli.strategia._calcola_strategia_core", side_effect=RuntimeError("total failure")):
            strat = calcola_strategia([{"video_id": "v1"}])
        self.assertEqual(strat.get("notes"), ANALYTICS_UNAVAILABLE_NOTE)

    def test_agent_pipeline_continues_without_analytics(self):
        import agent
        from contextlib import ExitStack

        patches = [
            patch.object(agent, "get_channel_performance", return_value=([], "none")),
            patch.object(agent, "calcola_strategia", return_value=standard_strategy()),
            patch.object(agent, "genera_topic", return_value="Robotics Startup Failure"),
            patch.object(agent, "genera_contenuto", return_value={
                "title": "Title",
                "description": "Desc",
                "tags": ["tag"],
                "script": "word " * 600,
                "video_keywords": ["office"],
            }),
            patch.object(agent, "genera_audio"),
            patch.object(agent, "_scarica_tutte_le_clips", return_value={"office": "clip.mp4"}),
            patch.object(agent, "monta_video"),
            patch.object(agent, "genera_thumbnail"),
            patch.object(agent, "pubblica_video", return_value="vid123"),
            patch.object(agent, "notify_step"),
            patch.object(agent, "notify_start"),
            patch.object(agent, "notify_done"),
            patch.object(agent, "notify_error"),
            patch.object(agent, "notify_analytics"),
            patch.object(agent, "_load_state", return_value={"publish_immediately": True}),
            patch.object(agent, "_save_state"),
            patch.object(agent, "_load_checkpoint", return_value={"steps": []}),
            patch.object(agent, "_save_checkpoint"),
            patch.object(agent, "_clear_checkpoint"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1024),
            patch.object(agent, "_check_abort"),
            patch.object(agent, "_segna_step"),
            patch.object(agent, "_pulisci_status_pipeline"),
            patch.object(agent, "_increment_runs_today"),
            patch("moduli.publish_gate.run_pre_publish_gate", return_value=(True, [], [])),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            agent.run_pipeline({"publish_immediately": True})


if __name__ == "__main__":
    unittest.main()
