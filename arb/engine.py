"""The arbitrage math.

For a two-way game, a bet on each side with all-in decimal odds d1 and d2
locks in a profit when 1/d1 + 1/d2 < 1. With total stake S, spend S/(d1*k)
and S/(d2*k) where k = 1/d1 + 1/d2; either result returns S/k.

Margin = 1/k - 1 is the guaranteed return on the money staked.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .fees import FeeModel
from .leagues import LEAGUES
from .models import BOOK, PM, Game, Quote
from .timeutil import et_date, iso

PAIR_TYPES = {(PM, BOOK): "pm-book", (BOOK, PM): "pm-book", (PM, PM): "pm-pm", (BOOK, BOOK): "book-book"}
_FRESH = timedelta(minutes=45)


def round2(value: float) -> float:
    """Half-up rounding to the cent (the dashboard's JavaScript uses the same rule)."""
    return math.floor(value * 100 + 0.5 + 1e-9) / 100


def margin_of(decimals) -> float:
    total = sum(1.0 / d for d in decimals)
    return 1.0 / total - 1.0


def usable_quotes(game: Game, now: datetime, venues=None, max_age: timedelta | None = None,
                  allow_indicative: bool = True) -> dict[int, list[Quote]]:
    """Best quote per venue for each side, best price first."""
    out = {}
    for side in (0, 1):
        chosen: dict[str, tuple] = {}
        for quote in game.quotes.get(side, []):
            if venues is not None and quote.venue not in venues:
                continue
            if quote.indicative and not allow_indicative:
                continue
            age = (now - quote.updated_at) if quote.updated_at else None
            if max_age is not None and age is not None and age > max_age:
                continue
            rank = (age is None or age <= _FRESH, quote.priority, quote.decimal)
            if quote.venue not in chosen or rank > chosen[quote.venue][0]:
                chosen[quote.venue] = (rank, quote)
        out[side] = sorted((q for _, q in chosen.values()), key=lambda q: q.decimal, reverse=True)
    return out


def best_combo(per_side: dict[int, list[Quote]], pair: str = "any"):
    """(margin, [quote side 0, quote side 1], pair type) for the best pairing, or None.

    Pairs on two different venues are preferred. A pair on one venue (e.g. YES
    on both Kalshi teams) is only returned when it is itself an arb.
    """
    cross = same = None
    for q0 in per_side.get(0, []):
        for q1 in per_side.get(1, []):
            kind = PAIR_TYPES[(q0.group, q1.group)]
            if pair != "any" and kind != pair:
                continue
            option = (margin_of([q0.decimal, q1.decimal]), [q0, q1], kind)
            if q0.venue == q1.venue:
                if same is None or option[0] > same[0]:
                    same = option
            elif cross is None or option[0] > cross[0]:
                cross = option
    if same is not None and same[0] > 0 and (cross is None or same[0] > cross[0]):
        return same
    return cross


def stake_plan(quotes: list[Quote], stake: float) -> dict:
    """Exact amounts for a total stake, with whole contracts and fees rounded to the cent."""
    total_inverse = sum(1.0 / q.decimal for q in quotes)
    target = stake / total_inverse
    has_exchange = any(q.kind == "exchange" for q in quotes)
    payout = math.floor(target) if has_exchange else round2(target)
    rows = []
    for q in quotes:
        if q.kind == "exchange":
            contracts = int(payout)
            fee = FeeModel(q.fee_rate, q.fee_round).order_fee(contracts, q.price)
            rows.append({"contracts": contracts, "fee": round2(fee),
                         "cost": round2(contracts * q.price + fee), "payout": float(contracts)})
        else:
            bet = round2(payout / q.decimal)
            rows.append({"bet": bet, "cost": bet, "payout": round2(bet * q.decimal)})
    spent = round2(sum(r["cost"] for r in rows))
    worst = min((r["payout"] for r in rows), default=0.0)
    profit = round2(worst - spent)
    return {"stake": spent, "payout": round2(worst), "profit": profit,
            "roi": round(profit / spent, 5) if spent else 0.0, "legs": rows}


@dataclass
class Opportunity:
    game: Game
    quotes: list[Quote]
    margin: float
    pair: str
    plan: dict
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        legs = "|".join(f"{i}:{q.venue}:{q.ref.get('side') or q.ref.get('position') or ''}"
                        for i, q in enumerate(self.quotes))
        return hashlib.sha1(f"{self.game.key}|{legs}".encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.key, "game": self.game.key, "league": self.game.league,
            "title": self.game.title, "start": iso(self.game.start), "margin": round(self.margin, 5),
            "pair": self.pair, "plan": self.plan, "warnings": self.warnings,
            "legs": [{"team": self.game.teams[i].name, **q.to_dict(i)} for i, q in enumerate(self.quotes)],
        }


def warnings_for(game: Game, quotes: list[Quote], plan: dict, now: datetime) -> list[str]:
    out = []
    league = LEAGUES.get(game.league)
    if league and league.ties:
        out.append("NFL games can tie: 2-way sportsbook bets are refunded on a tie, "
                   "but a YES contract loses. Check both venues' tie rules.")
    for q, row in zip(quotes, plan["legs"]):
        if q.ref.get("note"):
            out.append(f"{q.venue_title}: {q.ref['note']}.")
        if q.indicative:
            out.append(f"{q.venue_title} price is indicative; confirm it before trading.")
        if q.kind == "exchange" and q.size is not None and row.get("contracts", 0) > q.size:
            out.append(f"Only {int(q.size)} contracts are offered at this {q.venue_title} price.")
    if game.start is not None:
        minutes = (game.start - now).total_seconds() / 60
        if 0 < minutes < 15:
            out.append(f"Starts in {int(minutes)} min; prices may already have moved.")
    return out


def is_upcoming(game: Game, now: datetime, include_live: bool, last_date) -> bool:
    if game.status == "post":
        return False
    if not include_live and game.status == "in":
        return False
    if game.start is not None:
        if not include_live and game.start <= now:
            return False
        return et_date(game.start) <= last_date
    return et_date(now) <= game.date <= last_date


def find_opportunities(games: list[Game], now: datetime, stake: float, min_margin: float,
                       near_miss_count: int, venues=None, max_age: timedelta | None = None,
                       allow_indicative: bool = True, pair: str = "any"):
    arbs, misses = [], []
    for game in games:
        per_side = usable_quotes(game, now, venues, max_age, allow_indicative)
        combo = best_combo(per_side, pair)
        if combo is None:
            continue
        margin, quotes, kind = combo
        plan = stake_plan(quotes, stake)
        opp = Opportunity(game, quotes, margin, kind, plan)
        opp.warnings = warnings_for(game, quotes, plan, now)
        if margin > 0 and margin >= min_margin:
            arbs.append(opp)
        else:
            misses.append(opp)
    arbs.sort(key=lambda o: o.margin, reverse=True)
    misses.sort(key=lambda o: o.margin, reverse=True)
    return arbs, misses[:near_miss_count]
