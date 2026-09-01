"""Tests for Shorts quality gate."""

import os
import tempfile
import unittest
from unittest.mock import patch

from moduli.shorts.config import ShortsConfig
from moduli.shorts.quality import validate_short


class ShortsQualityTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ShortsConfig(min_duration=20, max_duration=60, skip_quality_gate=False)
        self.content = {
            "title": "Test Short",
            "hook": "Opening hook line here.",
            "script": "Opening hook line here. " + "word " * 80,
            "description": "Desc",
            "tags": ["test"],
        }
        self.concept = {"topic": "Test", "angle": "Angle", "source_topic": ""}

    def test_missing_files_fail(self):
        ok, errors = validate_short(
            content=self.content,
            concept=self.concept,
            audio_path="/nonexistent/audio.mp3",
            video_path="/nonexistent/video.mp4",
            ass_path="/nonexistent/captions.ass",
            segments=[],
            config=self.cfg,
        )
        self.assertFalse(ok)
        self.assertTrue(any("audio" in e for e in errors))

    def test_skip_gate_passes(self):
        ok, errors = validate_short(
            content=self.content,
            concept=self.concept,
            audio_path="/nonexistent/audio.mp3",
            video_path="/nonexistent/video.mp4",
            ass_path="/nonexistent/captions.ass",
            segments=[],
            config=ShortsConfig(skip_quality_gate=True),
        )
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    @patch("moduli.shorts.quality.media_duration", return_value=30.0)
    @patch("moduli.shorts.quality.caption_coverage_ratio", return_value=0.9)
    @patch("moduli.shorts.quality.os.path.getsize", return_value=100_000)
    @patch("moduli.shorts.quality.os.path.exists", return_value=True)
    @patch("moduli.shorts.quality.find_duplicate", return_value=(False, "", ""))
    def test_valid_files_pass(self, *_mocks):
        ok, errors = validate_short(
            content=self.content,
            concept=self.concept,
            audio_path="a.mp3",
            video_path="v.mp4",
            ass_path="c.ass",
            segments=[{"clip_path": "clip.mp4"}],
            config=self.cfg,
        )
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
