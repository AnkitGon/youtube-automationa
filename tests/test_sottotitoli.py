"""Tests for long-form SRT subtitle generation."""

import os
import tempfile
import unittest
from pathlib import Path

from moduli.sottotitoli import estimate_duration_from_script, prepare_srt


class SottotitoliTests(unittest.TestCase):
    def test_estimate_duration_from_script(self):
        script = " ".join(["word"] * 150)
        self.assertGreater(estimate_duration_from_script(script), 30)

    def test_prepare_srt_without_media_uses_script_estimate(self):
        script = (
            "BlackBerry dominated enterprise mobile because companies valued secure email. "
            "When Apple launched the iPhone, consumers chose apps over physical keyboards. "
        ) * 40
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "subs.srt")
            path = prepare_srt(script, out)
            self.assertEqual(path, out)
            text = Path(out).read_text(encoding="utf-8")
            self.assertIn("-->", text)
            self.assertGreater(os.path.getsize(out), 50)


if __name__ == "__main__":
    unittest.main()
