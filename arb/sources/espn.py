"""ESPN's public scoreboard: free schedules plus the DraftKings moneyline it shows.

This feed is unofficial (no key, no published limits), so it is used lightly:
one call per league per day, and failures are simply reported.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from ..leagues import League
from ..models import Quote, Side, SourceGame
from ..odds import american_to_decimal, fmt_american, parse_american
from ..timeutil import et_date, parse_iso
from . import BOOK_HOMEPAGES, BOOK_TITLES, dig

BASE = "https://site.api.espn.com/apis/site/v2/sports"

PROVIDERS = {
    "draftkings": "draftkings",
    "espn bet": "espnbet",
    "espnbet": "espnbet",
    "thescore bet": "espnbet",
    "caesars": "williamhill_us",
    "caesars sportsbook": "williamhill_us",
    "william hill": "williamhill_us",
    "fanduel": "fanduel",
    "betmgm": "betmgm",
}


def fetch_scoreboard(fetcher, league: League, day: date) -> dict:
    params = {"dates": day.strftime("%Y%m%d"), "limit": 500}
    params.update(dict(league.espn_params))
    return fetcher.get_json(f"{BASE}/{league.espn_path}/scoreboard", params).data or {}


def _venue(provider_name: str) -> str:
    key = provider_name.strip().lower()
    return PROVIDERS.get(key) or re.sub(r"[^a-z0-9]+", "", key) or "espn"


def _side(competitor: dict, home: bool) -> Side:
    team = competitor.get("team") or {}
    names = [team.get("displayName"), team.get("shortDisplayName"),
             " ".join(x for x in (team.get("location"), team.get("name")) if x),
             team.get("location"), team.get("name")]
    unique = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return Side(names=unique, code=team.get("abbreviation"), home=home)


def parse_scoreboard(data: dict, league_code: str, fetched_at: datetime) -> list[SourceGame]:
    games = []
    for event in (data or {}).get("events") or []:
        comp = (event.get("competitions") or [{}])[0] or {}
        competitors = comp.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        start = parse_iso(event.get("date") or comp.get("date"))
        state = dig(comp, "status", "type", "state") or dig(event, "status", "type", "state")
        sides = [_side(away, False), _side(home, True)]
        sg = SourceGame(source="espn", league=league_code, sides=sides, start=start,
                        date=et_date(start), status=state,
                        ref={"id": event.get("id"), "name": event.get("shortName")})
        for odds in comp.get("odds") or []:
            provider = dig(odds, "provider", "name") or "ESPN BET"
            home_ml = (parse_american(dig(odds, "moneyline", "home", "close", "odds"))
                       or parse_american(dig(odds, "homeTeamOdds", "moneyLine")))
            away_ml = (parse_american(dig(odds, "moneyline", "away", "close", "odds"))
                       or parse_american(dig(odds, "awayTeamOdds", "moneyLine")))
            if home_ml is None or away_ml is None:
                continue
            venue = _venue(provider)
            title = BOOK_TITLES.get(venue, provider)
            for index, line in ((0, away_ml), (1, home_ml)):
                dec = american_to_decimal(line)
                team = sides[index].names[0] if sides[index].names else (sides[index].code or "")
                sg.quotes.append((index, Quote(
                    venue=venue, venue_title=title, kind="book",
                    label=f"{team} {fmt_american(line)}", price=dec, decimal=dec,
                    american=int(round(line)), url=BOOK_HOMEPAGES.get(venue),
                    updated_at=fetched_at, source="espn", priority=1,
                    ref={"note": "this line is ESPN's copy and can lag the live one"},
                )))
            break  # ESPN lists one provider per game; take the first usable one
        games.append(sg)
    return games
