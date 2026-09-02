"""Tests for Shorts scheduler."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from moduli.shorts.config import ShortsConfig
from moduli.shorts.period_scheduler import resolve_daily_slot_plan
from moduli.shorts.scheduler import (
    ShortsScheduleDecision,
    compute_shorts_schedule,
    describe_manual_publish,
    next_manual_slot_index,
    next_slot_to_produce,
    next_upcoming_planned_slot,
    production_hours_local,
    should_produce_short_now,
    skipped_slots_today,
    slot_label,
)


class ShortsSchedulerTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, {"SHORTS_DYNAMIC_SCHEDULE": "0"}, clear=False)
        self._env_patch.start()
        self.cfg = ShortsConfig(
            timezone="Asia/Kolkata",
            production_hours=[10, 15, 20],
            fallback_hours=[10, 15, 20],
            analytics_min_videos=6,
        )

    def tearDown(self):
        self._env_patch.stop()

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
        self.assertEqual(hours, [10, 15, 20])

    def test_should_produce_morning_slot(self):
        now = datetime(2026, 3, 15, 4, 30, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        slot = should_produce_short_now(now, config=self.cfg, state=state)
        self.assertEqual(slot, 0)

    def test_should_produce_afternoon_not_morning(self):
        now = datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc)
        state = {
            "enabled": True,
            "runs_today": {"2026-03-15": 1},
            "today_shorts": [{"date": "2026-03-15", "slot": 0}],
        }
        slot = should_produce_short_now(now, config=self.cfg, state=state)
        self.assertEqual(slot, 1)

    def test_should_not_produce_between_slots(self):
        now = datetime(2026, 3, 15, 6, 0, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        self.assertIsNone(should_produce_short_now(now, config=self.cfg, state=state))

    def test_missed_morning_is_skipped_not_caught_up(self):
        # 09:30 UTC = 15:00 IST — morning passed, afternoon runs now (no morning catch-up)
        now = datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        self.assertEqual(skipped_slots_today(now, config=self.cfg, state=state), [0])
        self.assertEqual(next_slot_to_produce(now, config=self.cfg, state=state), (1, "scheduled"))
        self.assertEqual(should_produce_short_now(now, config=self.cfg, state=state), 1)

    def test_no_catch_up_when_multiple_windows_missed(self):
        # 12:30 UTC = 18:00 IST — morning and afternoon missed
        now = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        self.assertEqual(skipped_slots_today(now, config=self.cfg, state=state), [0, 1])
        pick = next_slot_to_produce(now, config=self.cfg, state=state)
        self.assertIsNone(pick)

    def test_start_at_afternoon_hour_only_runs_afternoon(self):
        now = datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        pick = next_slot_to_produce(now, config=self.cfg, state=state)
        self.assertEqual(pick, (1, "scheduled"))

    def test_evening_waits_for_scheduled_hour(self):
        now = datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        self.assertIsNone(next_slot_to_produce(now, config=self.cfg, state=state))

    def test_production_hours_from_config(self):
        hours = production_hours_local(ShortsConfig(production_hours=[9, 14, 19]))
        self.assertEqual(hours, [9, 14, 19])

    def test_manual_slot_picks_first_incomplete(self):
        state = {
            "today_shorts": [{"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "slot": 0}],
        }
        self.assertEqual(next_manual_slot_index(state, config=self.cfg), 1)

    def test_manual_slot_after_quota_uses_next_index(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state = {
            "runs_today": {today: 3},
            "today_shorts": [
                {"date": today, "slot": 0},
                {"date": today, "slot": 1},
                {"date": today, "slot": 2},
            ],
        }
        self.assertEqual(next_manual_slot_index(state, config=self.cfg), 3)

    def test_manual_publish_next_uses_upcoming_window(self):
        # 08:00 UTC = 13:30 IST — next window is afternoon 15:00
        now = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        state = {"enabled": True, "runs_today": {}, "today_shorts": []}
        upcoming = next_upcoming_planned_slot(config=self.cfg, state=state, now_utc=now)
        self.assertEqual(upcoming, (1, datetime(2026, 3, 15, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))))
        label = describe_manual_publish(
            "next", slot_index=0, config=self.cfg, state=state, now_utc=now,
        )
        self.assertIn("15:00", label)
        self.assertIn("afternoon", label)

    def test_analytics_picks_best_hour_per_period(self):
        activity = {
            "has_data": True,
            "total_views": 5000,
            "buckets": [
                {"hour": h, "views": views, "day_of_week": 1}
                for h, views in (
                    (9, 100), (10, 200), (14, 900), (15, 400), (18, 1200), (20, 300),
                )
            ],
        }
        cfg = ShortsConfig(
            timezone="Asia/Kolkata",
            fallback_hours=[10, 15, 20],
            analytics_min_videos=3,
            per_day=3,
        )
        with patch.dict(os.environ, {"SHORTS_DYNAMIC_SCHEDULE": "1"}, clear=False):
            plan = resolve_daily_slot_plan(
                config=cfg,
                activity=activity,
                profiles_count=20,
            )
            self.assertEqual(plan.slots[0].hour, 10)
            self.assertEqual(plan.slots[1].hour, 14)
            self.assertEqual(plan.slots[2].hour, 18)
            self.assertEqual(plan.source, "analytics")

    def test_fallback_when_no_audience_data(self):
        cfg = ShortsConfig(
            timezone="Asia/Kolkata",
            fallback_hours=[10, 15, 20],
            per_day=3,
        )
        with patch.dict(os.environ, {"SHORTS_DYNAMIC_SCHEDULE": "1"}, clear=False):
            plan = resolve_daily_slot_plan(config=cfg, activity=None, profiles_count=0)
        self.assertTrue(plan.fallback_used)
        self.assertEqual([s.hour for s in plan.slots], [10, 15, 20])

    def test_slots_respect_minimum_gap_of_four_hours(self):
        activity = {
            "has_data": True,
            "total_views": 3000,
            "buckets": [
                {"hour": 11, "views": 800, "day_of_week": 1},
                {"hour": 12, "views": 750, "day_of_week": 1},
                {"hour": 13, "views": 700, "day_of_week": 1},
            ],
        }
        cfg = ShortsConfig(fallback_hours=[10, 15, 20], per_day=3)
        with patch.dict(os.environ, {"SHORTS_DYNAMIC_SCHEDULE": "1"}, clear=False):
            plan = resolve_daily_slot_plan(config=cfg, activity=activity, profiles_count=20)
        hours = [s.hour for s in plan.slots]
        for i, a in enumerate(hours):
            for b in hours[i + 1:]:
                diff = abs(a - b)
                self.assertGreaterEqual(min(diff, 24 - diff), 4)

    def test_gap_violation_adjusts_weaker_slot(self):
        activity = {
            "has_data": True,
            "total_views": 8000,
            "buckets": [
                {"hour": h, "views": views, "day_of_week": 1}
                for h, views in (
                    (11, 500), (12, 900), (13, 850), (16, 200), (20, 1000),
                )
            ],
        }
        cfg = ShortsConfig(fallback_hours=[10, 15, 20], per_day=3, analytics_min_videos=1)
        with patch.dict(
            os.environ,
            {"SHORTS_DYNAMIC_SCHEDULE": "1", "SHORTS_MIN_SLOT_GAP_HOURS": "4"},
            clear=False,
        ):
            plan = resolve_daily_slot_plan(config=cfg, activity=activity, profiles_count=20)
        hours = [s.hour for s in plan.slots]
        self.assertEqual(hours[0], 11)
        self.assertEqual(hours[1], 16)
        self.assertEqual(hours[2], 20)
        for i, a in enumerate(hours):
            for b in hours[i + 1:]:
                diff = abs(a - b)
                self.assertGreaterEqual(min(diff, 24 - diff), 4)

    def test_daily_plan_does_not_carry_yesterday(self):
        cfg = ShortsConfig(fallback_hours=[10, 15, 20], per_day=3)
        state = {
            "daily_slot_plan": {
                "date_key": "2026-03-14",
                "slots": [
                    {"slot_index": 0, "label": "morning", "hour": 8, "minute": 0,
                     "period_start": 5, "period_end": 11, "views": 0, "source": "analytics"},
                ],
            }
        }
        now = datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"SHORTS_DYNAMIC_SCHEDULE": "1"}, clear=False):
            plan = resolve_daily_slot_plan(config=cfg, state=state, now_utc=now)
        self.assertEqual(plan.date_key, "2026-03-15")
        self.assertEqual([s.hour for s in plan.slots], [10, 15, 20])


if __name__ == "__main__":
    unittest.main()
