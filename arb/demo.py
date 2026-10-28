"""Sample data wiring for `python -m arb --demo` and the tests (no internet needed)."""

from __future__ import annotations

from .config import ROOT
from .http import FixtureFetcher

FIXTURES = ROOT / "tests" / "fixtures"
DEMO_NOW = "2026-10-28T15:00:00Z"
DEMO_LEAGUES = ("NBA", "NHL", "NCAAF")

ODDS_HEADERS = {"x-requests-remaining": "497", "x-requests-used": "3", "x-requests-last": "1"}

ROUTES = [
    (r"espn\.com/.*/basketball/nba/scoreboard\?.*dates=20261028", "espn_nba_20261028.json", None),
    (r"espn\.com/.*/hockey/nhl/scoreboard\?.*dates=20261028", "espn_nhl_20261028.json", None),
    (r"espn\.com/.*/football/college-football/scoreboard\?.*dates=20261029", "espn_ncaaf_20261029.json", None),
    (r"espn\.com/.*/scoreboard", {"events": []}, None),
    (r"kalshi\.com/trade-api/v2/series/KXNBAGAME", "kalshi_series_nba.json", None),
    (r"kalshi\.com/trade-api/v2/series/KXNHLGAME", "kalshi_series_nhl.json", None),
    (r"kalshi\.com/trade-api/v2/series/KXNCAAFGAME", "kalshi_series_ncaaf.json", None),
    (r"kalshi\.com/trade-api/v2/series/", {"series": {}}, None),
    (r"kalshi\.com/trade-api/v2/events\?.*series_ticker=KXNBAGAME", "kalshi_events_nba.json", None),
    (r"kalshi\.com/trade-api/v2/events\?.*series_ticker=KXNHLGAME", "kalshi_events_nhl.json", None),
    (r"kalshi\.com/trade-api/v2/events\?.*series_ticker=KXNCAAFGAME", "kalshi_events_ncaaf.json", None),
    (r"kalshi\.com/trade-api/v2/events", {"events": [], "cursor": ""}, None),
    (r"gateway\.polymarket\.us/v2/leagues\?", "pmus_leagues.json", None),
    (r"gateway\.polymarket\.us/v2/leagues/nba/events", "pmus_events_nba.json", None),
    (r"gateway\.polymarket\.us/v2/leagues/[^/]+/events", {"events": []}, None),
    (r"gateway\.polymarket\.us/v1/markets/aec-nba-bos-nyk-2026-10-28/bbo", "pmus_bbo_bos_nyk.json", None),
    (r"gateway\.polymarket\.us/v1/markets/aec-nba-lal-gsw-2026-10-28/bbo", "pmus_bbo_lal_gsw.json", None),
    (r"the-odds-api\.com/v4/sports/basketball_nba/odds", "odds_api_nba.json", ODDS_HEADERS),
    (r"the-odds-api\.com/v4/sports/[^/]+/odds", [], ODDS_HEADERS),
]


def demo_fetcher() -> FixtureFetcher:
    return FixtureFetcher(FIXTURES, ROUTES)
