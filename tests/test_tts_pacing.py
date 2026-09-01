"""Tests for TTS pause compression (unit + optional live Edge TTS)."""

import os
import unittest
from unittest.mock import patch

from moduli.tts_pacing import (
    compress_long_pauses,
    detect_silences,
    speech_segments_and_gaps,
)


class TtsPacingUnitTests(unittest.TestCase):
    def test_speech_segments_from_silence_list(self):
        with patch("moduli.tts_pacing.detect_silences") as mock_sil:
            with patch("moduli.tts_pacing.media_duration", return_value=10.0):
                mock_sil.return_value = [
                    (0.0, 0.2, 0.2),
                    (2.0, 3.0, 1.0),
                    (5.0, 6.0, 1.0),
                    (9.0, 10.0, 1.0),
                ]
                speech, gaps = speech_segments_and_gaps("fake.mp3")
        self.assertEqual(len(speech), 3)
        self.assertAlmostEqual(gaps[0], 1.0, places=1)
        self.assertAlmostEqual(gaps[1], 1.0, places=1)

    def test_compress_skips_single_span(self):
        with patch("moduli.tts_pacing.media_duration", return_value=5.0):
            with patch("moduli.tts_pacing.detect_silences", return_value=[(0.0, 0.2, 0.2), (4.8, 5.0, 0.2)]):
                with patch("shutil.copy2") as mock_copy:
                    stats = compress_long_pauses("in.mp3", "out.mp3")
        # one speech span only -> skip compression
        self.assertTrue(stats.get("skipped"))


@unittest.skipUnless(os.environ.get("RUN_LIVE_API_TESTS") == "1", "live TTS tests disabled")
class TtsPacingLiveTests(unittest.TestCase):
    def test_staccato_pauses_compressed(self):
        import asyncio
        import tempfile

        import edge_tts

        from moduli.ffmpeg_utils import media_duration

        text = "Nokia was huge. Then Apple arrived. Everything changed."
        raw = tempfile.mktemp(suffix=".mp3")
        out = tempfile.mktemp(suffix="_paced.mp3")
        asyncio.run(edge_tts.Communicate(text, "en-US-GuyNeural").save(raw))
        before = media_duration(raw)
        sil_before = [d for s, e, d in detect_silences(raw) if s > 0.1]
        stats = compress_long_pauses(raw, out)
        after = media_duration(out)
        sil_after = [d for s, e, d in detect_silences(out) if s > 0.1]
        self.assertLess(after, before)
        self.assertGreater(stats.get("gaps_compressed", 0), 0)
        if sil_before and sil_after:
            self.assertLess(max(sil_after), max(sil_before))
        os.remove(raw)
        os.remove(out)


class TtsVoiceTests(unittest.TestCase):
    def test_invalid_placeholder_falls_back(self):
        from moduli.audio import VOICE_DEFAULT, _normalize_voice

        self.assertEqual(_normalize_voice("..."), VOICE_DEFAULT)
        self.assertEqual(_normalize_voice(""), VOICE_DEFAULT)
        self.assertEqual(_normalize_voice("en-US-GuyNeural"), "en-US-GuyNeural")


if __name__ == "__main__":
    unittest.main()
