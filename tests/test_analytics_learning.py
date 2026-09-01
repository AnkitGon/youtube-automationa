"""Tests for compact analytics learning summaries."""
import unittest

from moduli.analytics_learning import (
    build_action_signals,
    build_compact_learning_summary,
    compute_channel_baselines,
    diagnose_video_card,
    enrich_insights_with_learning,
    insights_for_llm,
    learning_block_for_prompt,
)


def _profile(
    *,
    vid="v1",
    title="Test Video",
    views=100,
    ctr=5.0,
    retention=50.0,
    watch_min=80.0,
    impressions=2000,
    subs=2,
    published_at="2026-08-01T12:00:00Z",
):
    return {
        "video_id": vid,
        "title": title,
        "published_at": published_at,
        "metrics": {
            "views": views,
            "ctr_percent": ctr,
            "retention_percent": retention,
            "estimated_minutes_watched": watch_min,
            "impressions": impressions,
            "subscribers_gained": subs,
            "duration_seconds": 600,
            "avg_view_duration_seconds": 300,
        },
        "content_metadata": {"topic_category": "AI tools", "title_pattern": "how"},
    }


class AnalyticsLearningTests(unittest.TestCase):
    def test_baselines_from_profiles(self):
        profiles = [
            _profile(vid="a", ctr=4, retention=40, views=50),
            _profile(vid="b", ctr=6, retention=60, views=200),
            _profile(vid="c", ctr=5, retention=50, views=100),
        ]
        b = compute_channel_baselines(profiles)
        self.assertEqual(b["sample_size"], 3)
        self.assertGreater(b["median_ctr"], 0)

    def test_insufficient_data_for_single_video(self):
        card = diagnose_video_card(_profile(), compute_channel_baselines([_profile()]))
        self.assertEqual(card["confidence"], "insufficient_data")

    def test_overpromise_diagnosis(self):
        profiles = [
            _profile(vid="a", ctr=4, retention=50, views=100),
            _profile(vid="b", ctr=5, retention=55, views=120),
            _profile(vid="c", ctr=10, retention=20, views=500, title="Clickbait"),
        ]
        baselines = compute_channel_baselines(profiles)
        card = diagnose_video_card(profiles[2], baselines)
        self.assertEqual(card["ctr_strength"], "strong")
        self.assertEqual(card["retention_strength"], "weak")
        self.assertIn("overpromise", card["diagnosis"])

    def test_compact_summary_includes_audience(self):
        bundle = {
            "hour_grid": {
                "has_data": True,
                "buckets": [{"day_name": "Saturday", "hour": 20, "views": 500}],
            },
            "traffic_sources": {
                "has_data": True,
                "sources": [{"source_type": "YT_SEARCH", "views": 100}],
            },
            "reports_available": ["hour_grid", "traffic_sources"],
        }
        profiles = [_profile(vid=f"v{i}") for i in range(3)]
        summary = build_compact_learning_summary(profiles, channel_bundle=bundle)
        self.assertTrue(summary["text_block"])
        self.assertTrue(any("Traffic sources" in l for l in summary["audience_summary"]))

    def test_enrich_insights_attaches_learning(self):
        profiles = [_profile(vid=f"v{i}") for i in range(4)]
        insights = {"video_count": 4, "signals": ["existing"]}
        out = enrich_insights_with_learning(insights, profiles)
        self.assertIn("learning_summary", out)
        self.assertTrue(out["signals"])

    def test_insights_for_llm_is_compact(self):
        profiles = [_profile(vid=f"v{i}") for i in range(3)]
        insights = enrich_insights_with_learning({"video_count": 3}, profiles)
        slim = insights_for_llm(insights)
        self.assertIn("action_signals", slim)
        self.assertNotIn("video_cards", slim)

    def test_early_sample_conservative_signal(self):
        profiles = [_profile(vid="a"), _profile(vid="b")]
        baselines = compute_channel_baselines(profiles)
        cards = [diagnose_video_card(p, baselines) for p in profiles]
        signals = build_action_signals(profiles, baselines, cards, [])
        self.assertTrue(any("EARLY SAMPLE" in s for s in signals))

    def test_learning_block_from_strategy(self):
        block = learning_block_for_prompt({
            "_learning_summary": {
                "text_block": "Channel baselines (n=3): CTR 5%",
            },
        })
        self.assertIn("Channel baselines", block)


if __name__ == "__main__":
    unittest.main()
