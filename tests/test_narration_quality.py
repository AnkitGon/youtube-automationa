"""Tests for spoken-narration quality (TTS-aware scripting)."""

import unittest

from moduli.narration_quality import (
    analyze_narration_flow,
    normalize_script_for_tts,
    validate_spoken_narration,
)


FLOWING = (
    "Nokia was huge, but then Apple arrived with a completely different idea of what a phone "
    "could be, and that changed the game almost overnight. Nokia still had millions of customers, "
    "but the battlefield had moved somewhere it wasn't prepared to fight, which is why the "
    "company's decline happened faster than most people expected."
)

STACCATO = (
    "Nokia was huge. Then Apple arrived. Everything changed. Nokia failed. "
    "The market moved. They lost. It was over. Nobody saw it coming."
)

ARTICLE = (
    "Furthermore, the organizational structure contributed significantly to its decline. "
    "Moreover, the company failed to adapt. Subsequently, competitors gained share."
)


class NarrationQualityTests(unittest.TestCase):
    def test_flowing_script_passes(self):
        ok, errors, score = validate_spoken_narration(FLOWING, fmt="longform")
        self.assertTrue(ok, errors)
        self.assertGreaterEqual(score, 0.7)

    def test_staccato_script_fails(self):
        ok, errors, _ = validate_spoken_narration(STACCATO, fmt="longform")
        self.assertFalse(ok)
        self.assertTrue(any("short" in e.lower() or "staccato" in e.lower() or "streak" in e.lower() for e in errors))

    def test_article_tone_fails(self):
        ok, errors, _ = validate_spoken_narration(ARTICLE, fmt="longform")
        self.assertFalse(ok)
        self.assertTrue(any("article" in e.lower() or "essay" in e.lower() for e in errors))

    def test_normalize_removes_line_breaks(self):
        raw = "Nokia was huge.\n\nThen Apple arrived.\nEverything changed."
        norm = normalize_script_for_tts(raw)
        self.assertNotIn("\n", norm)
        self.assertIn("Nokia was huge.", norm)

    def test_shorts_allows_slightly_punchier(self):
        short_script = (
            "Nokia wasn't asleep—it was investing heavily, but the company couldn't agree on "
            "what smartphones were supposed to become, and that's when Apple took the lead."
        )
        ok, errors, _ = validate_spoken_narration(short_script, fmt="short")
        self.assertTrue(ok, errors)

    def test_analyze_metrics(self):
        m = analyze_narration_flow(STACCATO)
        self.assertGreater(m["max_short_streak"], 2)
        self.assertGreater(m["short_sentence_ratio"], 0.4)


if __name__ == "__main__":
    unittest.main()
