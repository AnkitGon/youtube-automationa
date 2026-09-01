"""Tests for Shorts scheduler."""

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from moduli.shorts.config import ShortsConfig
from moduli.shorts.scheduler import (
    ShortsScheduleDecision,
    compute_shorts_schedule,
    missed_slots_today,
    next_slot_to_produce,
    production_hours_local,
    should_produce_short_now,
    slot_label,
)


class ShortsSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ShortsConfig(
            timezone="Asia/Kolkata",
            production_hours=[10, 15, 20],
            fallback_hours=[12, 16, 20],
            analytics_min_videos=6,
        )

    def test_slot_labels(self):
        self.assertEqual(slot_label(0), "morning")
        self.assertEqual(slot_label(1), "afternoon")
        self.assertEqual(slot_label(2), "evening")

    def test_produce_now_publishes_after_lead(self):
        now = datetime(2026, 3, 15, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
        dec = compute_shorts_schedule(0, now=now, config=self.cfg, producing_now=True)
        self.assertEqual(dec.source, "produce_now")
        self.assertFalse(dec.fallback_used)
        delta = dec.publish_at_utc - now
        self.assertGreaterEqual(delta, timedelta(minutes=19))
        self.assertLessEqual(delta, timedelta(minutes=21))

    def test_fallback_three_slots(self):
        now = datetime(2026, 3, 15, 5, 0, tzinfo=timezone.utc)
        hours = []
        for i in range(3):
            dec = compute_shorts_schedule(i, now=now, config=self.cfg, producing_now=False)
            self.assertIsInstance(dec, ShortsScheduleDecision)
            self.assertTrue(dec.fallback_used)
            local = dec.publish_at_utc.astimezone(ZoneInfo("Asia/Kolkata"))
            hours.append(local.hour)
        self.assertEqual(hours, [12, 16, 20])

    def test_should_produce_morning_slot(self):
        # 04:30 UTC = 10:00 IST
        now = datetime(2026, 3, 15, 4, 30, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        slot = should_produce_short_now(now, config=self.cfg, state=state)
        self.assertEqual(slot, 0)

    def test_should_produce_afternoon_not_morning(self):
        # 09:30 UTC = 15:00 IST, morning already done
        now = datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc)
        state = {
            "enabled": True,
            "runs_today": {"2026-03-15": 1},
            "today_shorts": [{"date": "2026-03-15", "slot": 0}],
        }
        slot = should_produce_short_now(now, config=self.cfg, state=state)
        self.assertEqual(slot, 1)

    def test_should_not_produce_between_slots(self):
        now = datetime(2026, 3, 15, 6, 0, tzinfo=timezone.utc)  # 11:30 IST
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        self.assertIsNone(should_produce_short_now(now, config=self.cfg, state=state))

    def test_missed_morning_when_starting_afternoon(self):
        # 09:30 UTC = 15:00 IST — morning hour passed, no Short produced
        now = datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        self.assertEqual(missed_slots_today(now, config=self.cfg, state=state), [0])
        self.assertEqual(should_produce_short_now(now, config=self.cfg, state=state), 1)

    def test_catch_up_earliest_missed_slot(self):
        # 12:30 UTC = 18:00 IST — morning and afternoon missed
        now = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        pick = next_slot_to_produce(now, config=self.cfg, state=state)
        self.assertEqual(pick, (0, "catch-up"))

    def test_catch_up_advances_after_morning_done(self):
        now = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
        state = {
            "enabled": True,
            "runs_today": {"2026-03-15": 1},
            "today_shorts": [{"date": "2026-03-15", "slot": 0}],
        }
        pick = next_slot_to_produce(now, config=self.cfg, state=state)
        self.assertEqual(pick, (1, "catch-up"))

    def test_evening_still_waits_for_scheduled_hour(self):
        # 11:00 UTC = 16:30 IST — only morning missed, not afternoon yet
        now = datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        pick = next_slot_to_produce(now, config=self.cfg, state=state)
        self.assertEqual(pick, (0, "catch-up"))
        self.assertIsNone(should_produce_short_now(now, config=self.cfg, state=state))

    def test_production_hours_from_config(self):
        hours = production_hours_local(ShortsConfig(production_hours=[9, 14, 19]))
        self.assertEqual(hours, [9, 14, 19])

    def test_analytics_used_with_enough_videos(self):
        now = datetime(2026, 3, 15, 5, 0, tzinfo=timezone.utc)
        activity = {
            "has_data": True,
            "total_views": 1000,
            "buckets": [
                {"hour": 18, "views": 600, "day_of_week": 7},
                {"hour": 14, "views": 400, "day_of_week": 6},
            ],
        }
        dec = compute_shorts_schedule(
            0, now=now, activity=activity, profiles_count=20,
            config=self.cfg, producing_now=False,
        )
        self.assertEqual(dec.source, "analytics")
        local = dec.publish_at_utc.astimezone(ZoneInfo("Asia/Kolkata"))
        self.assertEqual(local.hour, 18)


if __name__ == "__main__":
    unittest.main()
