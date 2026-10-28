"""The Odds API (free plan: 500 credits a month).

One h2h call for one sport costs 1 credit per 10 bookmakers requested, so the
default list of 10 books costs exactly 1 credit. The budget module decides
when a call is worth spending.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..fees import FeeModel
from ..models import Quote, Side, SourceGame
from ..odds import decimal_to_american, fmt_american
from ..timeutil import et_date, parse_iso
from . import BOOK_HOMEPAGES, BOOK_TITLES, to_float

BASE = "https://api.the-odds-api.com/v4"

# The Odds API also relays some exchanges; their prices come in as decimal odds.
EXCHANGES = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US"}


def credit_cost(bookmakers: list[str], markets: int = 1) -> int:
    groups = max(1, -(-len(bookmakers) // 10)) if bookmakers else 1
    return groups * markets


def fetch_odds(fetcher, api_key: str, sport_key: str, bookmakers: list[str], now: datetime,
               hours_ahead: int, include_live: bool, include_links: bool = True):
    params = {
        "apiKey": api_key, "regions": "us", "markets": "h2h",
        "oddsFormat": "decimal", "dateFormat": "iso",
        "commenceTimeTo": (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not include_live:
        params["commenceTimeFrom"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if bookmakers:
        params["bookmakers"] = ",".join(bookmakers)
    if include_links:
        params["includeLinks"] = "true"
    response = fetcher.get_json(f"{BASE}/sports/{sport_key}/odds", params)
    return response.data or [], response.headers


def parse_odds(events: list[dict], league_code: str, exchange_fees: dict[str, FeeModel],
               fetched_at: datetime) -> list[SourceGame]:
    games = []
    for event in events or []:
        home, away = event.get("home_team"), event.get("away_team")
        if not home or not away:
            continue
        start = parse_iso(event.get("commence_time"))
        sides = [Side(names=[away], home=False), Side(names=[home], home=True)]
        sg = SourceGame(source="odds_api", league=league_code, sides=sides, start=start,
                        date=et_date(start), ref={"id": event.get("id")})
        for book in event.get("bookmakers") or []:
            key = book.get("key") or ""
            market = next((m for m in book.get("markets") or [] if m.get("key") == "h2h"), None)
            if not market:
                continue
            updated = parse_iso(market.get("last_update") or book.get("last_update")) or fetched_at
            for outcome in market.get("outcomes") or []:
                name = outcome.get("name")
                price = to_float(outcome.get("price"))
                index = 0 if name == away else 1 if name == home else None
                if index is None or price is None or price <= 1.0:
                    continue
                link = outcome.get("link") or market.get("link") or book.get("link") or BOOK_HOMEPAGES.get(key)
                if key in EXCHANGES:
                    fees = exchange_fees.get(key, FeeModel())
                    implied = 1.0 / price
                    sg.quotes.append((index, Quote(
                        venue=key, venue_title=EXCHANGES[key], kind="exchange",
                        label=f"YES {name}", price=round(implied, 4),
                        decimal=fees.effective_decimal(implied), fee_rate=fees.rate,
                        fee_round=fees.round_to, url=link, updated_at=updated,
                        source="odds_api", indicative=True, priority=1,
                    )))
                else:
                    american = decimal_to_american(price)
                    sg.quotes.append((index, Quote(
                        venue=key, venue_title=BOOK_TITLES.get(key) or book.get("title") or key,
                        kind="book", label=f"{name} {fmt_american(american)}", price=price,
                        decimal=price, american=american, url=link, updated_at=updated,
                        source="odds_api", priority=2,
                    )))
        games.append(sg)
    return games
