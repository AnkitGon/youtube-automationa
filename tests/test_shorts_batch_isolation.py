"""Tests for Shorts slot isolation — one slot failure does not block later slots."""

import unittest
from unittest.mock import patch

from moduli.shorts.config import ShortsConfig


class ShortsSlotIsolationTests(unittest.TestCase):
    @patch("moduli.shorts.pipeline.run_learning_update")
    @patch("moduli.shorts.pipeline.sync_shorts_profiles", return_value=[])
    @patch("moduli.shorts.pipeline.shorts_activity_signal", return_value={"has_data": False})
    @patch("moduli.shorts.pipeline.leggi_audience_geography", return_value={})
    @patch("moduli.shorts.pipeline.run_single_short")
    @patch("moduli.shorts.pipeline.load_config")
    @patch("moduli.shorts.pipeline.load_state")
    @patch("moduli.shorts.state.runs_today", return_value=0)
    @patch("moduli.shorts.pipeline.save_state")
    @patch("moduli.shorts.pipeline.clear_pipeline_status")
    def test_single_slot_failure_returns_failure(
        self, _clear, _save, _runs, mock_load_state, mock_cfg,
        mock_single, *_rest,
    ):
        mock_cfg.return_value = ShortsConfig(enabled=True, per_day=3)
        mock_load_state.return_value = {"enabled": True, "runs_today": {}}
        mock_single.return_value = None

        concepts = [{"topic": "A", "angle": "a"}]
        with patch("moduli.shorts.pipeline.plan_daily_batch", return_value=concepts):
            from moduli.shorts.pipeline import run_shorts_slot
            result = run_shorts_slot(0)

        self.assertIsNone(result["success"])
        self.assertIsNotNone(result["failure"])
        mock_single.assert_called_once()


if __name__ == "__main__":
    unittest.main()
