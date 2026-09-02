"""Tests for hashtag normalization in descriptions."""

from moduli.hashtags import (
    append_hashtags_to_description,
    fix_spaced_hashtags,
    format_hashtag_line,
    normalize_hashtags,
)
from moduli.pubblica import pubblica_short


def test_join_string_hashtag_does_not_space_characters():
    """Regression: ' '.join('#Shorts') produced '# S h o r'."""
    assert format_hashtag_line("#Shorts") == "#Shorts"
    assert format_hashtag_line("#Shorts", max_count=5) == "#Shorts"
    assert format_hashtag_line("#AI") == "#AI"


def test_fix_spaced_hashtags_in_text():
    assert fix_spaced_hashtags("Line one.\n\n# S h o r") == "Line one.\n\n#Shor"
    assert fix_spaced_hashtags("# A I  #") == "#AI"
    assert fix_spaced_hashtags("# Q u a n") == "#Quan"
    assert fix_spaced_hashtags("#Shorts") == "#Shorts"


def test_normalize_hashtags_from_string_list_and_fragments():
    assert normalize_hashtags("#Shorts #AI") == ["#Shorts", "#AI"]
    assert normalize_hashtags(["#", "S", "h", "o", "r", "t", "s"]) == ["#Shorts"]
    assert normalize_hashtags(["#Shorts", "#AI"]) == ["#Shorts", "#AI"]
    assert normalize_hashtags("# S h o r t s") == ["#Shorts"]


def test_append_hashtags_to_description():
    body = "How 2026 quantum milestones will render current laptop computing obsolete."
    out = append_hashtags_to_description(body, "#Shorts", required="#Shorts")
    assert out.endswith("#Shorts")
    assert "# S h o r" not in out

    broken = f"{body}\n\n# S h o r"
    fixed = append_hashtags_to_description(broken, "#Shorts", required="#Shorts")
    assert "# S h o r" not in fixed
    assert "#Shor" in fixed or "#Shorts" in fixed


def test_pubblica_short_builds_description():
    from unittest.mock import patch

    captured: dict = {}

    class FakeYt:
        def videos(self):
            return self

        def insert(self, **kwargs):
            captured["body"] = kwargs["body"]
            return self

        def next_chunk(self):
            return None, {"id": "abc123", "status": {}}

    with patch("moduli.pubblica._get_youtube", return_value=FakeYt()), patch(
        "moduli.pubblica._resumable_video_upload",
        side_effect=lambda yt, body, path: captured.update({"body": body}) or {"id": "abc123"},
    ), patch("moduli.pubblica.os.path.exists", return_value=True):
        pubblica_short(
            "video.mp4",
            "thumb.jpg",
            {
                "title": "Test Short",
                "description": "A short about AI.",
                "tags": ["ai"],
                "hashtags": "#Shorts",
            },
            immediate=True,
        )
    desc = captured["body"]["snippet"]["description"]
    assert "# S h o r" not in desc
    assert desc.endswith("#Shorts")
