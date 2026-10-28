import unittest
from datetime import date, datetime, timedelta, timezone

from arb.budget import OddsBudget, period_bounds

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
SOON = NOW + timedelta(hours=8)


class PeriodTests(unittest.TestCase):
    def test_calendar_month(self):
        self.assertEqual(period_bounds(date(2026, 10, 28), 1), (date(2026, 10, 1), date(2026, 11, 1)))
        self.assertEqual(period_bounds(date(2026, 12, 5), 1), (date(2026, 12, 1), date(2027, 1, 1)))

    def test_mid_month_reset(self):
        self.assertEqual(period_bounds(date(2026, 10, 10), 15), (date(2026, 9, 15), date(2026, 10, 15)))
        self.assertEqual(period_bounds(date(2026, 1, 3), 15), (date(2025, 12, 15), date(2026, 1, 15)))


class BudgetTests(unittest.TestCase):
    def test_spreads_credits_over_remaining_days(self):
        budget = OddsBudget({"remaining": 40, "period_start": "2026-10-01"}, max_per_day=25)
        self.assertEqual(budget.allowance_today(NOW), 10)          # 40 credits / 4 days left

    def test_daily_cap_and_interval(self):
        state = {}
        budget = OddsBudget(state, max_per_day=2, min_minutes=90)
        self.assertTrue(budget.decide("basketball_nba", NOW, SOON, 36)[0])
        budget.record("basketball_nba", NOW, {"x-requests-remaining": "499", "x-requests-last": "1"})
        ok, reason = budget.decide("basketball_nba", NOW + timedelta(minutes=30), SOON, 36)
        self.assertFalse(ok)
        self.assertIn("min ago", reason)
        self.assertTrue(budget.decide("icehockey_nhl", NOW, SOON, 36)[0])
        budget.record("icehockey_nhl", NOW, {"x-requests-last": "1"})
        ok, reason = budget.decide("baseball_mlb", NOW, SOON, 36)
        self.assertFalse(ok)
        self.assertIn("allowance", reason)
        self.assertEqual(state["remaining"], 498)

    def test_skips_when_no_games_soon(self):
        budget = OddsBudget({})
        self.assertFalse(budget.decide("basketball_nba", NOW, None, 36)[0])
        self.assertFalse(budget.decide("basketball_nba", NOW, NOW + timedelta(hours=50), 36)[0])

    def test_faster_refresh_near_game_time(self):
        budget = OddsBudget({}, min_minutes=90)
        budget.record("basketball_nba", NOW, {})
        later = NOW + timedelta(minutes=50)
        self.assertTrue(budget.decide("basketball_nba", later, later + timedelta(minutes=60), 36)[0])

    def test_new_period_forgets_old_remaining(self):
        state = {"remaining": 3, "period_start": "2026-09-01"}
        budget = OddsBudget(state)
        self.assertEqual(budget.allowance_today(NOW), 25)
        self.assertEqual(state["period_start"], "2026-10-01")


if __name__ == "__main__":
    unittest.main()
