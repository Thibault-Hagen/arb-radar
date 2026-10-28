"""Spends The Odds API's free credits evenly across the quota period.

Rules, in order:
  * only call a sport that has a game starting within the lookahead window;
  * wait at least `min_minutes` between calls for the same sport (half that when
    a game starts within two hours, when lines move most);
  * never spend more today than (credits left / days left), capped by
    `max_per_day`, so the quota cannot run dry mid-month.
"""

from __future__ import annotations

import calendar
import math
from datetime import date, datetime, timedelta

from .timeutil import iso, parse_iso


def _int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def period_bounds(today: date, reset_day: int) -> tuple[date, date]:
    """(start, next reset) of the monthly quota period containing `today`."""
    def clamp(year, month):
        return date(year, month, min(reset_day, calendar.monthrange(year, month)[1]))

    this_month = clamp(today.year, today.month)
    if today >= this_month:
        year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        return this_month, clamp(year, month)
    year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return clamp(year, month), this_month


class OddsBudget:
    def __init__(self, state: dict, monthly_credits: int = 500, reset_day: int = 1,
                 max_per_day: int = 25, min_minutes: int = 90, cost_per_call: int = 1):
        self.state = state
        self.monthly = monthly_credits
        self.reset_day = max(1, min(28, reset_day))
        self.max_per_day = max_per_day
        self.min_minutes = min_minutes
        self.cost = max(1, cost_per_call)

    def _roll(self, now: datetime) -> tuple[date, date]:
        start, end = period_bounds(now.date(), self.reset_day)
        if self.state.get("period_start") != start.isoformat():
            self.state["period_start"] = start.isoformat()
            self.state["remaining"] = None        # unknown until the API tells us
        if self.state.get("day") != now.date().isoformat():
            self.state["day"] = now.date().isoformat()
            self.state["used_today"] = 0
        return start, end

    def remaining(self) -> int:
        value = self.state.get("remaining")
        return self.monthly if value is None else int(value)

    def allowance_today(self, now: datetime) -> int:
        _, end = self._roll(now)
        days_left = max(1, (end - now.date()).days)
        return max(0, min(self.max_per_day, math.floor(self.remaining() / days_left)))

    def used_today(self, now: datetime) -> int:
        self._roll(now)
        return int(self.state.get("used_today") or 0)

    def decide(self, sport_key: str, now: datetime, next_start: datetime | None,
               lookahead_hours: int) -> tuple[bool, str]:
        if next_start is None:
            return False, "no upcoming games"
        until = next_start - now
        if until > timedelta(hours=lookahead_hours):
            return False, f"next game in {int(until.total_seconds() // 3600)}h"
        gap = self.min_minutes / 2 if until < timedelta(hours=2) else self.min_minutes
        last = parse_iso((self.state.get("last_call") or {}).get(sport_key))
        if last is not None and now - last < timedelta(minutes=gap):
            minutes = int((now - last).total_seconds() // 60)
            return False, f"refreshed {minutes} min ago"
        if self.remaining() < self.cost:
            return False, "monthly credits used up"
        if self.used_today(now) + self.cost > self.allowance_today(now):
            return False, "today's credit allowance is spent"
        return True, "fetching"

    def record(self, sport_key: str, now: datetime, headers: dict) -> None:
        self._roll(now)
        spent = _int(headers.get("x-requests-last"))
        spent = self.cost if spent is None else spent
        self.state["used_today"] = int(self.state.get("used_today") or 0) + spent
        remaining = _int(headers.get("x-requests-remaining"))
        self.state["remaining"] = remaining if remaining is not None else max(0, self.remaining() - spent)
        used = _int(headers.get("x-requests-used"))
        if used is not None:
            self.state["used_in_period"] = used
        self.state.setdefault("last_call", {})[sport_key] = iso(now)

    def summary(self, now: datetime) -> dict:
        return {"remaining": self.remaining(), "used_today": self.used_today(now),
                "allowance_today": self.allowance_today(now), "period_start": self.state.get("period_start")}
