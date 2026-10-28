"""Team names.

Pro leagues use a fixed list so that "New York K", "NYK", "Knicks" and
"New York Knicks" all land on the same team. College teams are matched
fuzzily against the names the schedule sources give us.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


def norm(text) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def college_norm(text) -> str:
    """norm() plus 'St.' handling: 'Ohio St.' -> 'ohio state', 'St. John's' -> 'saint john s'."""
    out = []
    tokens = norm(text).split()
    for i, token in enumerate(tokens):
        if token == "st":
            token = "saint" if i == 0 else "state"
        elif token in ("univ", "university"):
            continue
        out.append(token)
    return " ".join(out)


def similarity(a, b) -> float:
    """0-1 score for two team names; exact matches beat partial ones."""
    a, b = college_norm(a), college_norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    best = SequenceMatcher(None, a, b).ratio()
    sa, sb = set(a.split()), set(b.split())
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if small <= big and len("".join(small)) >= 3:
        best = max(best, 0.6 + 0.4 * len(small) / len(big))
    else:
        best = max(best, len(sa & sb) / len(sa | sb))
    return best


@dataclass(frozen=True)
class ProTeam:
    league: str
    code: str
    city: str
    nick: str
    alts: tuple = ()
    extras: tuple = ()

    @property
    def key(self) -> str:
        return f"{self.league}:{self.code}"

    @property
    def name(self) -> str:
        return f"{self.city} {self.nick}" if self.city else self.nick


def _t(league, code, city, nick, alts=(), extras=()):
    return ProTeam(league, code, city, nick, tuple(alts), tuple(extras))


_PRO = [
    # NFL
    _t("NFL", "ARI", "Arizona", "Cardinals", ["ARZ"]),
    _t("NFL", "ATL", "Atlanta", "Falcons"),
    _t("NFL", "BAL", "Baltimore", "Ravens"),
    _t("NFL", "BUF", "Buffalo", "Bills"),
    _t("NFL", "CAR", "Carolina", "Panthers"),
    _t("NFL", "CHI", "Chicago", "Bears"),
    _t("NFL", "CIN", "Cincinnati", "Bengals"),
    _t("NFL", "CLE", "Cleveland", "Browns"),
    _t("NFL", "DAL", "Dallas", "Cowboys"),
    _t("NFL", "DEN", "Denver", "Broncos"),
    _t("NFL", "DET", "Detroit", "Lions"),
    _t("NFL", "GB", "Green Bay", "Packers", ["GNB"]),
    _t("NFL", "HOU", "Houston", "Texans"),
    _t("NFL", "IND", "Indianapolis", "Colts"),
    _t("NFL", "JAX", "Jacksonville", "Jaguars", ["JAC"], ["jags"]),
    _t("NFL", "KC", "Kansas City", "Chiefs", ["KAN"]),
    _t("NFL", "LV", "Las Vegas", "Raiders", ["LVR", "OAK"]),
    _t("NFL", "LAC", "Los Angeles", "Chargers"),
    _t("NFL", "LAR", "Los Angeles", "Rams", ["LA"]),
    _t("NFL", "MIA", "Miami", "Dolphins"),
    _t("NFL", "MIN", "Minnesota", "Vikings"),
    _t("NFL", "NE", "New England", "Patriots", ["NWE"], ["pats"]),
    _t("NFL", "NO", "New Orleans", "Saints", ["NOR"]),
    _t("NFL", "NYG", "New York", "Giants", [], ["ny giants"]),
    _t("NFL", "NYJ", "New York", "Jets", [], ["ny jets"]),
    _t("NFL", "PHI", "Philadelphia", "Eagles"),
    _t("NFL", "PIT", "Pittsburgh", "Steelers"),
    _t("NFL", "SF", "San Francisco", "49ers", ["SFO"], ["niners"]),
    _t("NFL", "SEA", "Seattle", "Seahawks"),
    _t("NFL", "TB", "Tampa Bay", "Buccaneers", ["TAM"], ["bucs"]),
    _t("NFL", "TEN", "Tennessee", "Titans"),
    _t("NFL", "WAS", "Washington", "Commanders", ["WSH"]),
    # NBA
    _t("NBA", "ATL", "Atlanta", "Hawks"),
    _t("NBA", "BOS", "Boston", "Celtics"),
    _t("NBA", "BKN", "Brooklyn", "Nets", ["BRK", "BK"]),
    _t("NBA", "CHA", "Charlotte", "Hornets", ["CHO"]),
    _t("NBA", "CHI", "Chicago", "Bulls"),
    _t("NBA", "CLE", "Cleveland", "Cavaliers", [], ["cavs"]),
    _t("NBA", "DAL", "Dallas", "Mavericks", [], ["mavs"]),
    _t("NBA", "DEN", "Denver", "Nuggets"),
    _t("NBA", "DET", "Detroit", "Pistons"),
    _t("NBA", "GSW", "Golden State", "Warriors", ["GS"]),
    _t("NBA", "HOU", "Houston", "Rockets"),
    _t("NBA", "IND", "Indiana", "Pacers"),
    _t("NBA", "LAC", "Los Angeles", "Clippers"),
    _t("NBA", "LAL", "Los Angeles", "Lakers"),
    _t("NBA", "MEM", "Memphis", "Grizzlies"),
    _t("NBA", "MIA", "Miami", "Heat"),
    _t("NBA", "MIL", "Milwaukee", "Bucks"),
    _t("NBA", "MIN", "Minnesota", "Timberwolves", [], ["wolves"]),
    _t("NBA", "NOP", "New Orleans", "Pelicans", ["NO", "NOR"], ["pels"]),
    _t("NBA", "NYK", "New York", "Knicks", ["NY"]),
    _t("NBA", "OKC", "Oklahoma City", "Thunder"),
    _t("NBA", "ORL", "Orlando", "Magic"),
    _t("NBA", "PHI", "Philadelphia", "76ers", [], ["sixers"]),
    _t("NBA", "PHX", "Phoenix", "Suns", ["PHO"]),
    _t("NBA", "POR", "Portland", "Trail Blazers", [], ["blazers"]),
    _t("NBA", "SAC", "Sacramento", "Kings"),
    _t("NBA", "SAS", "San Antonio", "Spurs", ["SA"]),
    _t("NBA", "TOR", "Toronto", "Raptors"),
    _t("NBA", "UTA", "Utah", "Jazz", ["UTAH"]),
    _t("NBA", "WAS", "Washington", "Wizards", ["WSH"]),
    # NHL
    _t("NHL", "ANA", "Anaheim", "Ducks"),
    _t("NHL", "BOS", "Boston", "Bruins"),
    _t("NHL", "BUF", "Buffalo", "Sabres"),
    _t("NHL", "CGY", "Calgary", "Flames"),
    _t("NHL", "CAR", "Carolina", "Hurricanes", [], ["canes"]),
    _t("NHL", "CHI", "Chicago", "Blackhawks"),
    _t("NHL", "COL", "Colorado", "Avalanche", [], ["avs"]),
    _t("NHL", "CBJ", "Columbus", "Blue Jackets", ["CLB"]),
    _t("NHL", "DAL", "Dallas", "Stars"),
    _t("NHL", "DET", "Detroit", "Red Wings"),
    _t("NHL", "EDM", "Edmonton", "Oilers"),
    _t("NHL", "FLA", "Florida", "Panthers"),
    _t("NHL", "LAK", "Los Angeles", "Kings", ["LA"]),
    _t("NHL", "MIN", "Minnesota", "Wild"),
    _t("NHL", "MTL", "Montreal", "Canadiens", ["MON"], ["habs"]),
    _t("NHL", "NSH", "Nashville", "Predators", ["NAS"], ["preds"]),
    _t("NHL", "NJD", "New Jersey", "Devils", ["NJ"]),
    _t("NHL", "NYI", "New York", "Islanders", [], ["ny islanders"]),
    _t("NHL", "NYR", "New York", "Rangers", [], ["ny rangers"]),
    _t("NHL", "OTT", "Ottawa", "Senators", [], ["sens"]),
    _t("NHL", "PHI", "Philadelphia", "Flyers"),
    _t("NHL", "PIT", "Pittsburgh", "Penguins", [], ["pens"]),
    _t("NHL", "SJS", "San Jose", "Sharks", ["SJ"]),
    _t("NHL", "SEA", "Seattle", "Kraken"),
    _t("NHL", "STL", "St. Louis", "Blues", [], ["saint louis blues"]),
    _t("NHL", "TBL", "Tampa Bay", "Lightning", ["TB"]),
    _t("NHL", "TOR", "Toronto", "Maple Leafs", [], ["leafs"]),
    _t("NHL", "UTA", "Utah", "Mammoth", ["UTAH"], ["utah hockey club"]),
    _t("NHL", "VAN", "Vancouver", "Canucks"),
    _t("NHL", "VGK", "Vegas", "Golden Knights", ["VEG"], ["las vegas golden knights"]),
    _t("NHL", "WSH", "Washington", "Capitals", ["WAS"], ["caps"]),
    _t("NHL", "WPG", "Winnipeg", "Jets"),
    # MLB
    _t("MLB", "ARI", "Arizona", "Diamondbacks", ["AZ"], ["d backs", "dbacks"]),
    _t("MLB", "ATH", "", "Athletics", ["OAK"],
       ["oakland athletics", "sacramento athletics", "las vegas athletics", "a s"]),
    _t("MLB", "ATL", "Atlanta", "Braves"),
    _t("MLB", "BAL", "Baltimore", "Orioles"),
    _t("MLB", "BOS", "Boston", "Red Sox"),
    _t("MLB", "CHC", "Chicago", "Cubs"),
    _t("MLB", "CWS", "Chicago", "White Sox", ["CHW"], ["chicago ws"]),
    _t("MLB", "CIN", "Cincinnati", "Reds"),
    _t("MLB", "CLE", "Cleveland", "Guardians"),
    _t("MLB", "COL", "Colorado", "Rockies"),
    _t("MLB", "DET", "Detroit", "Tigers"),
    _t("MLB", "HOU", "Houston", "Astros"),
    _t("MLB", "KC", "Kansas City", "Royals", ["KCR"]),
    _t("MLB", "LAA", "Los Angeles", "Angels", ["ANA"], ["anaheim angels"]),
    _t("MLB", "LAD", "Los Angeles", "Dodgers"),
    _t("MLB", "MIA", "Miami", "Marlins", ["FLA"]),
    _t("MLB", "MIL", "Milwaukee", "Brewers"),
    _t("MLB", "MIN", "Minnesota", "Twins"),
    _t("MLB", "NYM", "New York", "Mets", [], ["ny mets"]),
    _t("MLB", "NYY", "New York", "Yankees", [], ["ny yankees"]),
    _t("MLB", "PHI", "Philadelphia", "Phillies"),
    _t("MLB", "PIT", "Pittsburgh", "Pirates"),
    _t("MLB", "SD", "San Diego", "Padres", ["SDP"]),
    _t("MLB", "SF", "San Francisco", "Giants", ["SFG"]),
    _t("MLB", "SEA", "Seattle", "Mariners"),
    _t("MLB", "STL", "St. Louis", "Cardinals", [], ["saint louis cardinals"]),
    _t("MLB", "TB", "Tampa Bay", "Rays", ["TBR"]),
    _t("MLB", "TEX", "Texas", "Rangers"),
    _t("MLB", "TOR", "Toronto", "Blue Jays", [], ["jays"]),
    _t("MLB", "WSH", "Washington", "Nationals", ["WAS", "WSN"], ["nats"]),
]

TEAMS: dict[str, ProTeam] = {t.key: t for t in _PRO}
_BY_LEAGUE: dict[str, list[ProTeam]] = {}
_ALIASES: dict[str, dict[str, set[str]]] = {}
_CODES: dict[str, dict[str, set[str]]] = {}


def _aliases(team: ProTeam) -> set[str]:
    out = {norm(team.nick), norm(team.name)}
    if team.city:
        city = norm(team.city)
        out.add(city)
        out.add(f"{city} {norm(team.nick)[0]}")            # Kalshi style: "new york k"
        if city == "los angeles":
            out |= {f"la {norm(team.nick)}", f"la {norm(team.nick)[0]}"}
    out |= {norm(e) for e in team.extras}
    return {a for a in out if a}


for _team in _PRO:
    _BY_LEAGUE.setdefault(_team.league, []).append(_team)
    aliases = _ALIASES.setdefault(_team.league, {})
    for _alias in _aliases(_team):
        aliases.setdefault(_alias, set()).add(_team.key)
    codes = _CODES.setdefault(_team.league, {})
    for _code in (_team.code, *_team.alts):
        codes.setdefault(norm(_code), set()).add(_team.key)


def is_pro(league: str) -> bool:
    return league in _ALIASES


def resolve(league: str, names, code: str | None = None) -> str | None:
    """Canonical key like 'NBA:NYK' for a pro team, or None if unsure."""
    aliases = _ALIASES.get(league)
    if aliases is None:
        return None
    codes = _CODES[league]
    names = [n for n in (names or []) if n]

    if code:
        hit = codes.get(norm(code))
        if hit and len(hit) == 1:
            return next(iter(hit))
    for name in names:
        key = norm(name)
        hit = aliases.get(key) or codes.get(key)
        if hit and len(hit) == 1:
            return next(iter(hit))

    # Every word of the label appears in exactly one team's full name ("golden state").
    for name in names:
        words = set(norm(name).split())
        if not words:
            continue
        hits = {t.key for t in _BY_LEAGUE[league] if words <= set(norm(t.name).split())}
        if len(hits) == 1:
            return hits.pop()

    # Last resort: close spelling of one unambiguous alias.
    scores: dict[str, float] = {}
    for name in names:
        key = norm(name)
        if len(key) < 4:
            continue
        for alias, teams in aliases.items():
            if len(teams) != 1 or len(alias) < 4:
                continue
            team_key = next(iter(teams))
            score = SequenceMatcher(None, key, alias).ratio()
            if score > scores.get(team_key, 0.0):
                scores[team_key] = score
    if scores:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_key, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if best >= 0.86 and best - second >= 0.06:
            return best_key
    return None


def display(key: str) -> tuple[str, str]:
    """(full name, short code) for a canonical pro key."""
    team = TEAMS.get(key)
    if team is None:
        return key.split(":", 1)[-1], key.split(":", 1)[-1]
    return team.name, team.code


def all_names(key: str) -> list[str]:
    team = TEAMS.get(key)
    if team is None:
        return []
    names = [team.name, team.nick, team.code, *team.alts, *team.extras]
    if team.city:
        names.append(team.city)
    return names
