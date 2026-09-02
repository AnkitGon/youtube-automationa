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
