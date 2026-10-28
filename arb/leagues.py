"""Leagues the scanner knows about, and where each one lives on every source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    code: str                 # our short code, e.g. "NBA"
    name: str                 # display name
    espn_path: str            # site.api.espn.com/apis/site/v2/sports/<path>/scoreboard
    espn_params: tuple        # extra scoreboard params, e.g. (("groups", "80"),)
    odds_api_key: str         # The Odds API sport key
    kalshi_series: str        # Kalshi game-winner series ticker
    pmus_slugs: tuple         # likely Polymarket US league slugs, best guess first
    pmus_names: tuple         # names/abbreviations to recognise the league by
    college: bool = False     # no fixed team list, so match names fuzzily
    ties: bool = False        # regulation ties possible (2-way bets push)


LEAGUES: dict[str, League] = {
    lg.code: lg
    for lg in [
        League("NFL", "NFL", "football/nfl", (), "americanfootball_nfl", "KXNFLGAME",
               ("nfl",), ("nfl",), ties=True),
        League("NBA", "NBA", "basketball/nba", (), "basketball_nba", "KXNBAGAME",
               ("nba",), ("nba",)),
        League("NHL", "NHL", "hockey/nhl", (), "icehockey_nhl", "KXNHLGAME",
               ("nhl",), ("nhl",)),
        League("MLB", "MLB", "baseball/mlb", (), "baseball_mlb", "KXMLBGAME",
               ("mlb",), ("mlb",)),
        League("NCAAF", "College Football", "football/college-football", (("groups", "80"),),
               "americanfootball_ncaaf", "KXNCAAFGAME",
               ("cfb", "ncaaf", "college-football"),
               ("college football", "ncaaf", "cfb", "ncaa football"), college=True),
        League("NCAAB", "College Basketball", "basketball/mens-college-basketball",
               (("groups", "50"),), "basketball_ncaab", "KXNCAAMBGAME",
               ("cbb", "ncaab", "college-basketball", "mens-college-basketball"),
               ("college basketball", "ncaab", "cbb", "ncaam", "ncaa basketball"), college=True),
    ]
}
