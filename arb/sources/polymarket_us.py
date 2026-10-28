"""Polymarket US (the CFTC-regulated US exchange) public gateway, no login needed.

A game's moneyline is one market with two sides: the "long" side is one team
and the "short" side is the other. bestAsk is what it costs to buy the long
team; buying the short team costs 1 - bestBid.
"""

from __future__ import annotations

from datetime import datetime

from ..fees import FeeModel
from ..leagues import League
from ..models import Quote, Side, SourceGame
from ..teams import norm
from ..timeutil import et_date, parse_iso
from . import dig, to_float

GATEWAY = "https://gateway.polymarket.us"
WEB = "https://polymarket.us"
_PERIOD_WORDS = ("half", "quarter", "period", "inning", "1h", "2h", "1q", "first", "set")


def fetch_leagues(fetcher, max_pages: int = 20) -> list[dict]:
    out = []
    for page in range(max_pages):
        batch = (fetcher.get_json(f"{GATEWAY}/v2/leagues", {"limit": 50, "offset": page * 50}).data
                 or {}).get("leagues") or []
        out.extend(batch)
        if len(batch) < 50:
            break
    return out


def pick_league_slug(leagues: list[dict], league: League) -> str | None:
    by_slug = {(lg.get("slug") or "").lower(): lg for lg in leagues if isinstance(lg, dict)}
    for slug in league.pmus_slugs:
        if slug in by_slug:
            return by_slug[slug]["slug"]
    wanted = {norm(n) for n in league.pmus_names}
    for lg in leagues:
        if not isinstance(lg, dict):
            continue
        if norm(lg.get("name")) in wanted or norm(lg.get("abbreviation")) in wanted:
            return lg.get("slug")
    return None


def fetch_league_events(fetcher, slug: str, max_pages: int = 4) -> list[dict]:
    out = []
    for page in range(max_pages):
        data = fetcher.get_json(f"{GATEWAY}/v2/leagues/{slug}/events",
                                {"limit": 50, "offset": page * 50, "type": "sport"}).data or {}
        batch = data.get("events") or []
        out.extend(batch)
        if len(batch) < 50:
            break
    return out


def fetch_bbo(fetcher, market_slug: str) -> dict:
    return (fetcher.get_json(f"{GATEWAY}/v1/markets/{market_slug}/bbo").data or {}).get("marketData") or {}


def _is_moneyline(market: dict) -> bool:
    # Seen in the wild: sportsMarketType "football_team_full_game_winner",
    # sportsMarketTypeV2 "SPORTS_MARKET_TYPE_MONEYLINE", marketType "moneyline".
    kinds = " ".join(str(market.get(k) or "") for k in
                     ("sportsMarketTypeV2", "sportsMarketType", "marketType")).lower()
    return "moneyline" in kinds or "full_game_winner" in kinds


def _full_game(market: dict) -> bool:
    text = " ".join(str(market.get(k) or "") for k in ("slug", "title", "question")).lower()
    return not any(word in text.replace("-", " ").split() for word in _PERIOD_WORDS)


def _team_for(side: dict, teams: dict) -> dict:
    team = teams.get(side.get("teamId"))
    if team is None and isinstance(side.get("team"), dict):
        team = side["team"]
    return team or {}


def _side_info(side: dict, teams: dict) -> Side:
    team = _team_for(side, teams)
    names = []
    for name in (team.get("alias"), team.get("name"), team.get("safeName"), side.get("description")):
        if name and name not in names:
            names.append(name)
    code = (team.get("abbreviation") or team.get("displayAbbreviation") or "").upper() or None
    return Side(names=names or ["?"], code=code)


def parse_events(events: list[dict], league_code: str, taker_rate: float, round_to: float,
                 fetched_at: datetime) -> list[SourceGame]:
    fees = FeeModel(taker_rate, round_to)
    games = []
    for event in events or []:
        if not isinstance(event, dict) or event.get("ended") or event.get("closed") or event.get("archived"):
            continue
        teams = {t.get("id"): t for t in event.get("teams") or [] if isinstance(t, dict)}
        markets = [m for m in event.get("markets") or [] if isinstance(m, dict)]
        moneylines = [m for m in markets if _is_moneyline(m) and _full_game(m)]
        if not moneylines:
            moneylines = [m for m in markets if len(m.get("marketSides") or []) == 2 and _full_game(m)
                          and all(s.get("teamId") or s.get("team") for s in m["marketSides"])]
        if not moneylines:
            continue
        market = moneylines[0]
        if market.get("closed") is True or market.get("active") is False:
            continue
        raw_sides = market.get("marketSides") or []
        if len(raw_sides) != 2:
            continue
        long_side = next((s for s in raw_sides if s.get("long") is True), raw_sides[0])
        short_side = raw_sides[1] if long_side is raw_sides[0] else raw_sides[0]
        sides = [_side_info(long_side, teams), _side_info(short_side, teams)]

        start = parse_iso(event.get("startTime") or event.get("startDate") or market.get("gameStartTime"))
        event_slug = event.get("slug") or ""
        market_slug = market.get("slug") or ""
        url = f"{WEB}/event/{event_slug}" if event_slug else f"{WEB}/market/{market_slug}"
        sg = SourceGame(source="polymarket_us", league=league_code, sides=sides, start=start,
                        date=et_date(start), status="in" if event.get("live") else None,
                        ref={"event_slug": event_slug, "market_slug": market_slug, "url": url})

        bid = to_float(market.get("bestBidQuote"))
        ask = to_float(market.get("bestAskQuote"))
        prices = [(ask, False), ((1.0 - bid) if bid is not None else None, False)]
        # No order-book quote in the listing: fall back to the displayed side price,
        # flagged as indicative until the best-bid/offer refresh confirms it.
        for n, side in enumerate((long_side, short_side)):
            if prices[n][0] is None:
                fallback = to_float(side.get("quote")) or to_float(side.get("price"))
                prices[n] = (fallback, True)
        for n in (0, 1):
            price, indicative = prices[n]
            if price is None or not 0.005 <= price <= 0.995:
                continue
            raw_side = long_side if n == 0 else short_side
            sg.quotes.append((n, Quote(
                venue="polymarket_us", venue_title="Polymarket US", kind="exchange",
                label=raw_side.get("description") or sides[n].names[0],
                price=round(price, 4), decimal=fees.effective_decimal(price),
                fee_rate=fees.rate, fee_round=fees.round_to, url=url, updated_at=fetched_at,
                source="polymarket_us", indicative=indicative, priority=3,
                ref={"market_slug": market_slug, "position": "long" if n == 0 else "short"},
            )))
        games.append(sg)
    return games


def apply_bbo(quotes: list[Quote], bbo: dict, fetched_at: datetime) -> list[Quote]:
    """Replace listing prices with fresh best bid/offer. Returns the quotes to keep."""
    state = (bbo.get("state") or "MARKET_STATE_OPEN").upper()
    if "OPEN" not in state:
        return []
    bid = to_float(dig(bbo, "bestBid"))
    ask = to_float(dig(bbo, "bestAsk"))
    kept = []
    for quote in quotes:
        fees = FeeModel(quote.fee_rate, quote.fee_round)
        if quote.ref.get("position") == "long":
            price, size = ask, to_float(bbo.get("askShares"))
        else:
            price = (1.0 - bid) if bid is not None else None
            size = to_float(bbo.get("bidShares"))
        if price is None or not 0.005 <= price <= 0.995:
            continue
        quote.price = round(price, 4)
        quote.decimal = fees.effective_decimal(price)
        quote.size = size
        quote.indicative = False
        quote.updated_at = fetched_at
        kept.append(quote)
    return kept
