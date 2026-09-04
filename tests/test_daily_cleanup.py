"""Tests for daily cache/ + output/ cleanup."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from moduli.manutenzione import (
    is_pipeline_busy,
    maybe_daily_runtime_cleanup,
    purge_runtime_dirs,
    wipe_dir_contents,
)


class DailyCleanupTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.output = self.root / "output"
        self.cache = self.root / "cache"
        self.output.mkdir()
        self.cache.mkdir()
        (self.output / "old.mp4").write_bytes(b"video")
        (self.output / "shorts").mkdir()
        (self.output / "shorts" / "x.mp4").write_bytes(b"short")
        (self.cache / "pexels").mkdir()
        (self.cache / "pexels" / "clip.mp4").write_bytes(b"clip")
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_wipe_and_purge_recreates_scaffold(self):
        removed, mb = wipe_dir_contents(str(self.output))
        self.assertGreaterEqual(removed, 1)
        self.assertFalse((self.output / "old.mp4").exists())
        self.assertTrue(self.output.is_dir())

        with patch.dict(os.environ, {"DAILY_CLEANUP_ENABLED": "1"}, clear=False):
            stats = purge_runtime_dirs(output_dir="output", cache_dir="cache")
        self.assertGreater(stats["freed_mb"] + stats["output_items"] + stats["cache_items"], 0)
        self.assertTrue((self.root / "output" / "shorts").is_dir())
        self.assertTrue((self.root / "cache" / "pexels").is_dir())

    def test_busy_when_longform_or_shorts_running(self):
        busy, reason = is_pipeline_busy(longform_state={"pipeline_status": {"step": "montage"}})
        self.assertTrue(busy)
        self.assertIn("long-form", reason)

        busy, reason = is_pipeline_busy(
            longform_state={},
            shorts_state={"pipeline_status": {"step": "render"}},
        )
        self.assertTrue(busy)
        self.assertIn("shorts", reason)

        busy, reason = is_pipeline_busy(
            longform_state={},
            shorts_state={"pending_upload": {"slot": 0}},
        )
        self.assertTrue(busy)
        self.assertIn("pending_upload", reason)

    def test_busy_when_today_checkpoint_exists(self):
        now = datetime(2026, 3, 15, 20, 0, tzinfo=timezone.utc)
        cp = self.output / "pipeline_checkpoint.json"
        cp.write_text(json.dumps({"date": "2026-03-15", "steps": {"audio": True}}), encoding="utf-8")
        busy, reason = is_pipeline_busy(longform_state={}, shorts_state={}, now_utc=now)
        self.assertTrue(busy)
        self.assertIn("checkpoint", reason)

    def test_runs_after_cleanup_hour_when_idle(self):
        # 01:15 Asia/Kolkata = 19:45 UTC previous calendar day in UTC, but local date Mar 15
        now = datetime(2026, 3, 14, 19, 45, tzinfo=timezone.utc)
        local = now.astimezone(ZoneInfo("Asia/Kolkata"))
        self.assertEqual(local.hour, 1)
        self.assertEqual(local.strftime("%Y-%m-%d"), "2026-03-15")

        with patch.dict(
            os.environ,
            {
                "DAILY_CLEANUP_ENABLED": "1",
                "DAILY_CLEANUP_HOUR": "1",
                "DAILY_CLEANUP_TIMEZONE": "Asia/Kolkata",
            },
            clear=False,
        ):
            result = maybe_daily_runtime_cleanup(
                now_utc=now,
                longform_state={},
                shorts_state={},
                last_cleanup_date=None,
            )
        self.assertTrue(result["ran"])
        self.assertEqual(result["date"], "2026-03-15")
        self.assertFalse((self.output / "old.mp4").exists())
        self.assertTrue((self.root / "cache" / "pexels").is_dir())

    def test_skips_before_cleanup_hour(self):
        # 00:30 IST = 19:00 UTC Mar 14 → local date Mar 15 hour 0
        now = datetime(2026, 3, 14, 19, 0, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {"DAILY_CLEANUP_HOUR": "1", "DAILY_CLEANUP_TIMEZONE": "Asia/Kolkata"},
            clear=False,
        ):
            result = maybe_daily_runtime_cleanup(
                now_utc=now,
                longform_state={},
                shorts_state={},
                last_cleanup_date=None,
            )
        self.assertFalse(result["ran"])
        self.assertEqual(result["reason"], "before_hour")
        self.assertTrue((self.output / "old.mp4").exists())

    def test_defers_when_busy_then_does_not_mark_done(self):
        now = datetime(2026, 3, 14, 19, 45, tzinfo=timezone.utc)  # 01:15 IST
        with patch.dict(
            os.environ,
            {"DAILY_CLEANUP_HOUR": "1", "DAILY_CLEANUP_TIMEZONE": "Asia/Kolkata"},
            clear=False,
        ):
            result = maybe_daily_runtime_cleanup(
                now_utc=now,
                longform_state={"pipeline_status": {"step": "clips"}},
                shorts_state={},
                last_cleanup_date=None,
            )
        self.assertTrue(result["deferred"])
        self.assertFalse(result["ran"])
        self.assertTrue((self.output / "old.mp4").exists())

    def test_skips_if_already_cleaned_today(self):
        now = datetime(2026, 3, 14, 19, 45, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {"DAILY_CLEANUP_HOUR": "1", "DAILY_CLEANUP_TIMEZONE": "Asia/Kolkata"},
            clear=False,
        ):
            result = maybe_daily_runtime_cleanup(
                now_utc=now,
                longform_state={},
                shorts_state={},
                last_cleanup_date="2026-03-15",
            )
        self.assertEqual(result["reason"], "already_done")
        self.assertTrue((self.output / "old.mp4").exists())

    def test_does_not_delete_outside_cache_output(self):
        secret = self.root / "state.json"
        secret.write_text("{}", encoding="utf-8")
        now = datetime(2026, 3, 14, 19, 45, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {"DAILY_CLEANUP_HOUR": "1", "DAILY_CLEANUP_TIMEZONE": "Asia/Kolkata"},
            clear=False,
        ):
            maybe_daily_runtime_cleanup(
                now_utc=now,
                longform_state={},
                shorts_state={},
                last_cleanup_date=None,
            )
        self.assertTrue(secret.exists())


if __name__ == "__main__":
    unittest.main()
