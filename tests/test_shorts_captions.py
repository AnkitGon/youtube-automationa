"""Tests for Shorts ASS caption styling."""

import os
import tempfile
import unittest

from moduli.shorts.captions import caption_layout, generate_ass, resolve_caption_font_size


class ShortsCaptionsTests(unittest.TestCase):
    def test_auto_font_size_scales_with_height(self):
        self.assertEqual(resolve_caption_font_size(1920, None), 86)
        self.assertGreater(resolve_caption_font_size(1920, 0), 70)
        self.assertEqual(resolve_caption_font_size(1920, 96), 96)

    def test_layout_uses_mobile_safe_zone(self):
        layout = caption_layout(width=1080, height=1920)
        self.assertGreaterEqual(layout["font_size"], 72)
        self.assertGreaterEqual(layout["outline"], 5)
        self.assertGreaterEqual(layout["margin_v"], int(1920 * 0.20))

    def test_generated_ass_is_large_bold_and_uppercase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.ass")
            generate_ass(
                "you are doing anything important with quantum chips",
                12.0,
                path,
                width=1080,
                height=1920,
                uppercase=True,
                words_per_group=3,
            )
            text = open(path, encoding="utf-8").read()
        self.assertIn("Arial Black,86,", text)
        self.assertIn(",6,2,2,", text)  # thick outline + shadow
        self.assertIn("MarginV, Encoding", text)
        self.assertIn("YOU ARE DOING", text)
        self.assertNotIn("you are doing", text)

    def test_caption_timing_sync_matches_audio_duration(self):
        import re
        script = (
            "Welcome to this quick short! Today we are exploring space facts. "
            "Did you know neutron stars spin 600 times per second? That is faster than a blender! "
            "A day on Venus is longer than a year. Imagine celebrating your birthday twice in one day!"
        )
        audio_duration = 20.0
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timing_test.ass")
            generate_ass(script, audio_duration, path, words_per_group=3)
            with open(path, encoding="utf-8") as f:
                content = f.read()
        
        matches = re.findall(r"Dialogue: 0,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+)", content)
        self.assertTrue(len(matches) > 5)
        
        def _to_sec(ts: str) -> float:
            h, m, s = ts.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)

        first_start = _to_sec(matches[0][0])
        last_end = _to_sec(matches[-1][1])
        
        self.assertAlmostEqual(first_start, 0.0, places=2)
        self.assertAlmostEqual(last_end, audio_duration, places=2)

