"""Test deduplicazione semantica topic."""
import os
import tempfile
import unittest
from unittest.mock import patch

from moduli import topic_history as th
from moduli.topic_history import (
    TopicDuplicateError,
    assert_unique_topic,
    find_semantic_duplicate,
    record_topic,
)


class TopicHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_file = th.TOPIC_HISTORY_FILE
        th.TOPIC_HISTORY_FILE = os.path.join(self._tmpdir.name, "topic_history.json")

    def tearDown(self):
        th.TOPIC_HISTORY_FILE = self._old_file
        self._tmpdir.cleanup()

    def test_record_and_exact_duplicate(self):
        record_topic("Why Blockbuster Failed", video_id="v1")
        dup, match, _ = find_semantic_duplicate("Why Blockbuster Failed", use_llm=False)
        self.assertTrue(dup)
        self.assertEqual(match, "Why Blockbuster Failed")

    def test_nokia_variants_are_duplicates(self):
        record_topic("How Nokia Lost the Smartphone War", video_id="n1")
        variants = [
            "Why Nokia Failed in Smartphones",
            "Nokia's Smartphone Collapse Explained",
            "The Real Reason Nokia Lost to Apple",
        ]
        for v in variants:
            dup, match, reason = find_semantic_duplicate(v, use_llm=False)
            self.assertTrue(dup, f"expected duplicate for '{v}', got reason={reason}")
            self.assertIn("nokia", (match or v).lower())

    def test_nokia_identity_fields(self):
        ident = th.build_topic_identity("How Nokia Lost the Smartphone War")
        self.assertEqual(ident["core_entity"], "Nokia")
        self.assertIn("smartphone", ident["subject"])
        self.assertIn("loss", ident["core_event"].lower() + ident["core_event"])
        self.assertIn("nokia", ident["normalized_topic"])
        self.assertTrue(ident["identity_hash"])

    def test_same_story_same_hash_family(self):
        a = th.build_topic_identity("How Nokia Lost the Smartphone War")
        b = th.build_topic_identity("Why Nokia Failed in Smartphones")
        score = th.identity_match_score(b, a)
        self.assertGreaterEqual(score, th.similarity_threshold())

    def test_different_entity_different_identity(self):
        a = th.build_topic_identity("Why Blockbuster Failed")
        b = th.build_topic_identity("How Tesla Builds Batteries")
        score = th.identity_match_score(b, a)
        self.assertLess(score, th.similarity_threshold())

    def test_record_stores_registry_fields(self):
        entry = record_topic(
            "How Nokia Lost the Smartphone War",
            title="Nokia's Fall: Smartphone War Lost",
            video_id="n1",
        )
        self.assertEqual(entry["status"], th.STATUS_PUBLISHED)
        self.assertEqual(entry["topic"], "How Nokia Lost the Smartphone War")
        self.assertTrue(entry.get("normalized"))
        self.assertTrue(entry.get("date"))
        self.assertEqual(entry["video_id"], "n1")
        self.assertTrue(entry.get("category"))
        self.assertIn("Nokia", entry.get("entities") or [])
        self.assertIn("identity", entry)

    def test_record_rejected_duplicate_persisted(self):
        record_topic("Why Blockbuster Failed", video_id="b1")
        entry = th.record_rejected_topic(
            "How Blockbuster Died",
            matched="Why Blockbuster Failed",
            reason="similarity 0.88",
            status=th.STATUS_REJECTED_DUPLICATE,
        )
        self.assertEqual(entry["status"], th.STATUS_REJECTED_DUPLICATE)
        self.assertEqual(entry["matched_topic"], "Why Blockbuster Failed")
        registry = th.load_topic_registry()
        self.assertEqual(len(registry), 2)
        rejected = th.load_topic_registry(status=th.STATUS_REJECTED_DUPLICATE)
        self.assertEqual(len(rejected), 1)
        dup, _, _ = find_semantic_duplicate("The Fall of Blockbuster", use_llm=False)
        self.assertTrue(dup)

    def test_try_reserve_records_rejected(self):
        record_topic("OpenAI GPT History", video_id="o1")
        ok, err = th.try_reserve_topic("The Story of OpenAI GPT")
        self.assertFalse(ok)
        self.assertIn("duplicat", err.lower())
        rejected = th.load_topic_registry(status=th.STATUS_REJECTED_DUPLICATE)
        self.assertEqual(len(rejected), 1)

    def test_record_stores_identity(self):
        entry = record_topic(
            "How Nokia Lost the Smartphone War",
            title="Nokia's Fall: Smartphone War Lost",
            video_id="n1",
        )
        self.assertIn("identity", entry)
        self.assertEqual(entry["core_entity"], "Nokia")
        self.assertIn("normalized_topic", entry)

    def test_registry_survives_reload(self):
        record_topic("Tesla Battery Breakthrough", video_id="t1")
        raw_path = th.TOPIC_HISTORY_FILE
        self.assertTrue(os.path.exists(raw_path))
        th.TOPIC_HISTORY_FILE = raw_path
        loaded = th.load_topic_registry(status=th.STATUS_PUBLISHED)
        self.assertEqual(loaded[0]["topic"], "Tesla Battery Breakthrough")
        self.assertEqual(loaded[0]["video_id"], "t1")

    def test_same_entity_different_story_not_duplicate(self):
        record_topic("Why Nokia Failed in Smartphones", video_id="n1")
        dup, _, _ = find_semantic_duplicate(
            "How Nokia Dominated Early Mobile Phones in the 2000s",
            use_llm=False,
        )
        self.assertFalse(dup)

    def test_blockbuster_variants_are_duplicates(self):
        record_topic("Why Blockbuster Failed", video_id="b1")
        for v in ("How Blockbuster Died", "The Fall of Blockbuster", "What Killed Blockbuster?"):
            self.assertTrue(find_semantic_duplicate(v, use_llm=False)[0], v)

    def test_different_subjects_not_duplicate(self):
        record_topic("Why Blockbuster Failed", video_id="b1")
        dup, _, _ = find_semantic_duplicate("How Tesla Builds Batteries", use_llm=False)
        self.assertFalse(dup)

    def test_assert_unique_raises(self):
        record_topic("AI Chip Wars", video_id="c1")
        with self.assertRaises(TopicDuplicateError):
            assert_unique_topic("The AI Chip War Explained", use_llm=False)

    def test_queue_exact_duplicate_blocked(self):
        record_topic("Netflix Streaming Rise", video_id="n1")
        dup, _, _ = find_semantic_duplicate(
            "Netflix Streaming Rise",
            queue_peers=["Amazon Prime Video Growth"],
            use_llm=False,
        )
        self.assertTrue(dup)

    def test_try_reserve_topic_api(self):
        record_topic("OpenAI GPT History", video_id="o1")
        ok, err = th.try_reserve_topic("The Story of OpenAI GPT")
        self.assertFalse(ok)
        self.assertIn("duplicat", err.lower())

    def test_similarity_threshold_from_env(self):
        with patch.dict(os.environ, {"TOPIC_SIMILARITY_THRESHOLD": "0.90"}):
            self.assertAlmostEqual(th.similarity_threshold(), 0.90)

    def test_compute_similarity_detects_rewording(self):
        a = th.build_topic_identity("How Nokia Lost the Smartphone War")
        b = th.build_topic_identity("Why Nokia Failed in Smartphones")
        detail = th.compute_similarity(b, a)
        self.assertGreaterEqual(detail["combined"], th.similarity_threshold())
        self.assertGreaterEqual(detail["entity_overlap"], 0.3)

    def test_below_threshold_not_duplicate(self):
        record_topic("Why Blockbuster Failed", video_id="b1")
        with patch.dict(os.environ, {"TOPIC_SIMILARITY_THRESHOLD": "0.95"}):
            dup, _, _ = find_semantic_duplicate("How Tesla Builds Batteries", use_llm=False)
        self.assertFalse(dup)

    @patch("moduli.ai_client.chat_ollama")
    def test_llm_duplicate_judge(self, mock_chat):
        from moduli.topic_history import _llm_duplicate_judge
        mock_chat.return_value = '{"duplicate": true, "matches": "Why Nokia Failed", "reason": "same company failure"}'
        dup, match, reason = _llm_duplicate_judge(
            "Nokia smartphone collapse",
            ["How Nokia Lost the Smartphone War"],
        )
        self.assertTrue(dup)
        self.assertIn("Nokia", match or "")

    def test_manual_reserve_registers_immediately(self):
        ok, err = th.try_reserve_topic("How Nokia Lost the Smartphone War")
        self.assertTrue(ok, err)
        reserved = th.load_topic_registry(status=th.STATUS_RESERVED)
        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0]["topic"], "How Nokia Lost the Smartphone War")
        self.assertEqual(reserved[0]["source"], "manual")

    def test_manual_reserve_blocks_semantically_similar(self):
        th.reserve_topic("Why Blockbuster Failed", source="manual")
        dup, _, _ = find_semantic_duplicate("How Blockbuster Died", use_llm=False)
        self.assertTrue(dup)
        ok, err = th.try_reserve_topic("The Fall of Blockbuster")
        self.assertFalse(ok)
        self.assertIn("duplicat", err.lower())

    def test_reserved_upgrades_to_published_on_record_topic(self):
        th.reserve_topic("Netflix Streaming Rise", source="manual")
        entry = record_topic(
            "Netflix Streaming Rise",
            title="Netflix: The Streaming Revolution",
            video_id="n1",
            source="pipeline",
        )
        self.assertEqual(entry["status"], th.STATUS_PUBLISHED)
        self.assertEqual(entry["video_id"], "n1")
        published = th.load_topic_registry(status=th.STATUS_PUBLISHED)
        self.assertEqual(len(published), 1)
        reserved = th.load_topic_registry(status=th.STATUS_RESERVED)
        self.assertEqual(len(reserved), 0)

    def test_ensure_queue_topics_reserved(self):
        state = {"topic_queue": ["Why Blockbuster Failed", "How Tesla Builds Batteries"]}
        n = th.ensure_queue_topics_reserved(state)
        self.assertEqual(n, 2)
        reserved = th.load_topic_registry(status=th.STATUS_RESERVED)
        self.assertEqual(len(reserved), 2)


if __name__ == "__main__":
    unittest.main()
