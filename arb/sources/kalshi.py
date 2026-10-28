"""Kalshi public market data (no account or API key needed).

Each game is an event with one binary market per team, e.g.
KXNBAGAME-26OCT28BOSNYK-BOS ("Boston wins"). For a team you can buy YES on
its market or NO on the other team's market; both pay $1 if it wins.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from ..fees import FeeModel
from ..models import Quote, Side, SourceGame
from ..timeutil import parse_iso
from . import to_float

BASE = "https://api.elections.kalshi.com/trade-api/v2"
WEB = "https://kalshi.com/markets"

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
_TICKER_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})")
_OPEN = {"active", "open"}


def ticker_date(event_ticker: str) -> date | None:
    match = _TICKER_DATE.search(event_ticker or "")
    if not match:
        return None
    yy, mon, dd = match.groups()
    if mon not in _MONTHS:
        return None
    try:
        return date(2000 + int(yy), _MONTHS[mon], int(dd))
    except ValueError:
        return None


def dollars(market: dict, field: str) -> float | None:
    """Kalshi now sends prices as dollar strings ("0.5600"); older payloads used cents."""
    value = to_float(market.get(f"{field}_dollars"))
    if value is None:
        cents = to_float(market.get(field))
        value = cents / 100.0 if cents is not None else None
    return value


def _usable(price: float | None) -> bool:
    return price is not None and 0.005 <= price <= 0.995


def fetch_series(fetcher, ticker: str) -> dict:
    return (fetcher.get_json(f"{BASE}/series/{ticker}").data or {}).get("series") or {}


def fetch_events(fetcher, series_ticker: str, max_pages: int = 5) -> list[dict]:
    events, cursor = [], None
    for _ in range(max_pages):
        params = {"series_ticker": series_ticker, "status": "open",
                  "with_nested_markets": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = fetcher.get_json(f"{BASE}/events", params).data or {}
        events.extend(data.get("events") or [])
        cursor = data.get("cursor")
        if not cursor:
            break
    return events


def _slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "game"


def _is_tie(market: dict) -> bool:
    code = (market.get("ticker") or "").rsplit("-", 1)[-1].upper()
    label = (market.get("yes_sub_title") or "").strip().lower()
    return code in ("TIE", "DRAW") or label in ("tie", "draw")


def _tradable(market: dict) -> bool:
    if market.get("mve_collection_ticker"):
        return False
    if market.get("market_type") not in (None, "binary"):
        return False
    return (market.get("status") or "active") in _OPEN


def fee_multiplier(series: dict, event: dict) -> float:
    for value in (event.get("fee_multiplier_override"), series.get("fee_multiplier")):
        number = to_float(value)
        if number is not None:
            return number
    return 1.0


def parse_events(events: list[dict], league_code: str, series: dict, taker_rate: float,
                 round_to: float, fetched_at: datetime, ties_possible: bool = False) -> list[SourceGame]:
    games = []
    for event in events or []:
        ticker = event.get("event_ticker") or ""
        markets = [m for m in event.get("markets") or [] if _tradable(m)]
        team_markets = [m for m in markets if not _is_tie(m)]
        if len(team_markets) != 2:
            continue
        fees = FeeModel(taker_rate * fee_multiplier(series, event), round_to)
        series_ticker = event.get("series_ticker") or ticker.split("-")[0]
        url = f"{WEB}/{series_ticker.lower()}/{_slug(series.get('title'))}/{ticker.lower()}"

        sides, labels = [], []
        for market in team_markets:
            code = market["ticker"].rsplit("-", 1)[-1] if "-" in market.get("ticker", "") else None
            label = market.get("yes_sub_title") or market.get("title") or code or "?"
            sides.append(Side(names=[label], code=code))
            labels.append(label)

        # The ticker date is the game date. We don't trust any market timestamp as the
        # start time (they describe expiry/settlement), so matching is by date.
        occurrence = parse_iso(team_markets[0].get("occurrence_datetime"))
        sg = SourceGame(source="kalshi", league=league_code, sides=sides,
                        date=ticker_date(ticker),
                        ref={"event_ticker": ticker, "url": url,
                             "occurrence": occurrence.isoformat() if occurrence else None,
                             "rules": (team_markets[0].get("rules_primary") or "")[:400]})
        if len(markets) != len(team_markets):
            sg.notes.append("Kalshi also lists a tie market for this game.")

        for i, market in enumerate(team_markets):
            other = team_markets[1 - i]
            yes_ask = dollars(market, "yes_ask")
            if _usable(yes_ask):
                sg.quotes.append((i, Quote(
                    venue="kalshi", venue_title="Kalshi", kind="exchange",
                    label=f"YES {labels[i]}", price=yes_ask, decimal=fees.effective_decimal(yes_ask),
                    fee_rate=fees.rate, fee_round=fees.round_to,
                    size=to_float(market.get("yes_ask_size_fp")), url=url,
                    updated_at=fetched_at, source="kalshi", priority=3,
                    ref={"ticker": market.get("ticker"), "side": "yes"},
                )))
            no_ask = dollars(other, "no_ask")
            if _usable(no_ask):
                note = f"Pays if {labels[1 - i]} doesn't win"
                if ties_possible:
                    note += " (a tie also pays)"
                sg.quotes.append((i, Quote(
                    venue="kalshi", venue_title="Kalshi", kind="exchange",
                    label=f"NO {labels[1 - i]}", price=no_ask, decimal=fees.effective_decimal(no_ask),
                    fee_rate=fees.rate, fee_round=fees.round_to,
                    # A NO ask is someone's YES bid, so its size is the YES bid size.
                    size=to_float(other.get("yes_bid_size_fp")), url=url,
                    updated_at=fetched_at, source="kalshi", priority=3,
                    ref={"ticker": other.get("ticker"), "side": "no", "note": note},
                )))
        games.append(sg)
    return games
