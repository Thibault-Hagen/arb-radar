"""Lines up the same game across sources.

Pro games match on (league, US-Eastern date, both canonical teams).
College games match on date plus fuzzy names for both teams at once, which
keeps "Ohio" from being confused with "Ohio State".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from . import teams as T
from .leagues import LEAGUES
from .models import Game, SourceGame, Team
from .timeutil import et_date

# Which feed's start time we trust most.
START_PRIORITY = {"espn": 4, "odds_api": 3, "polymarket_us": 2, "kalshi": 1}

CREATED, MATCHED, SKIPPED = "created", "matched", "skipped"


class GameBook:
    def __init__(self):
        self.games: list[Game] = []
        self._by_day: dict[tuple, list[Game]] = defaultdict(list)

    # ------------------------------------------------------------------ public
    def add(self, sg: SourceGame) -> tuple[Game | None, str]:
        if sg.date is None and sg.start is not None:
            sg.date = et_date(sg.start)
        if sg.date is None or len(sg.sides) != 2 or sg.league not in LEAGUES:
            return None, SKIPPED
        league = LEAGUES[sg.league]
        if league.college:
            game, mapping, verdict = self._match_college(sg)
        else:
            game, mapping, verdict = self._match_pro(sg)
        if verdict == SKIPPED:
            return None, SKIPPED
        status = MATCHED
        if game is None:
            game, mapping = self._create(sg), [0, 1]
            status = CREATED
        self._merge(game, sg, mapping)
        return game, status

    # ---------------------------------------------------------------- matching
    def _candidates(self, league: str, day, spread: int = 0) -> list[Game]:
        out = []
        for delta in range(-spread, spread + 1):
            out.extend(self._by_day.get((league, day + timedelta(days=delta)), []))
        return out

    @staticmethod
    def _close_in_time(game: Game, sg: SourceGame, hours: float = 6.0) -> bool:
        if game.start is None or sg.start is None:
            return True
        return abs((game.start - sg.start).total_seconds()) <= hours * 3600

    def _match_pro(self, sg: SourceGame):
        keys = [T.resolve(sg.league, s.names, s.code) for s in sg.sides]
        if keys[0] and keys[0] == keys[1]:
            return None, None, SKIPPED

        if keys[0] and keys[1]:
            wanted = {keys[0], keys[1]}
            same_day = [g for g in self._candidates(sg.league, sg.date)
                        if g.team_keys == wanted and self._close_in_time(g, sg)]
            if len(same_day) > 1:   # double-header: pick by start time, else give up
                timed = [g for g in same_day if g.start and sg.start]
                if not timed:
                    return None, None, SKIPPED
                same_day = [min(timed, key=lambda g: abs((g.start - sg.start).total_seconds()))]
            if len(same_day) == 1:
                game = same_day[0]
                return game, self._map_by_keys(game, keys), MATCHED
            # A source may date a late game by UTC; accept a neighbouring day if unambiguous.
            nearby = [g for g in self._candidates(sg.league, sg.date, spread=1)
                      if g.team_keys == wanted and g.date != sg.date]
            if len(nearby) == 1:
                game = nearby[0]
                if sg.start is not None and game.start is not None:
                    ok = self._close_in_time(game, sg)
                else:
                    ok = self._date_only_neighbour(game, sg)
                if ok:
                    return game, self._map_by_keys(game, keys), MATCHED
            return None, None, CREATED

        # One side resolved: if only one game that day has that team, take it.
        known = [i for i, k in enumerate(keys) if k]
        if len(known) == 1:
            i = known[0]
            hits = [g for g in self._candidates(sg.league, sg.date) if keys[i] in g.team_keys]
            if len(hits) == 1:
                game = hits[0]
                gi = next(n for n, t in enumerate(game.teams) if t.key == keys[i])
                other = game.teams[1 - gi]
                score = max((T.similarity(a, b) for a in sg.sides[1 - i].names for b in other.names),
                            default=0.0)
                if score >= 0.35:
                    mapping = [0, 0]
                    mapping[i], mapping[1 - i] = gi, 1 - gi
                    return game, mapping, MATCHED
        return None, None, CREATED

    @staticmethod
    def _date_only_neighbour(game: Game, sg: SourceGame) -> bool:
        """Kalshi tickers carry a date but no start time. They sometimes file a game under
        the day before (college games whose kickoff isn't set yet) or under the UTC date of
        a late game. Accept only those two cases, never a game on the previous day."""
        if game.date == sg.date + timedelta(days=1):
            return True
        return game.start is not None and game.start.date() == sg.date

    @staticmethod
    def _map_by_keys(game: Game, keys) -> list[int]:
        index = {t.key: n for n, t in enumerate(game.teams)}
        return [index[keys[0]], index[keys[1]]]

    @staticmethod
    def _side_score(side, team: Team) -> float:
        if side.code and team.short and T.norm(side.code) == T.norm(team.short):
            return 1.0
        return max((T.similarity(a, b) for a in side.names for b in team.names), default=0.0)

    def _match_college(self, sg: SourceGame):
        scored = []
        for game in self._candidates(sg.league, sg.date, spread=1):
            penalty = 0.0
            if game.date != sg.date:
                if game.start and sg.start:
                    if not self._close_in_time(game, sg):
                        continue
                elif sg.start is None and self._date_only_neighbour(game, sg):
                    penalty = 0.05          # a same-day game with these names wins
                else:
                    continue
            s00 = self._side_score(sg.sides[0], game.teams[0])
            s11 = self._side_score(sg.sides[1], game.teams[1])
            s01 = self._side_score(sg.sides[0], game.teams[1])
            s10 = self._side_score(sg.sides[1], game.teams[0])
            straight = (s00 + s11) / 2 if min(s00, s11) >= 0.55 else 0.0
            crossed = (s01 + s10) / 2 if min(s01, s10) >= 0.55 else 0.0
            if max(straight, crossed) > 0:
                mapping = [0, 1] if straight >= crossed else [1, 0]
                scored.append((max(straight, crossed) - penalty, game, mapping))
        if not scored:
            return None, None, CREATED
        scored.sort(key=lambda x: x[0], reverse=True)
        best, game, mapping = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best >= 0.70 and best - runner_up >= 0.08:
            return game, mapping, MATCHED
        return None, None, CREATED

    # --------------------------------------------------------------- building
    def _create(self, sg: SourceGame) -> Game:
        league = LEAGUES[sg.league]
        teams = []
        for side in sg.sides:
            key = None if league.college else T.resolve(sg.league, side.names, side.code)
            if key:
                name, short = T.display(key)
                names = T.all_names(key)
            else:
                label = side.names[0] if side.names else (side.code or "?")
                prefix = sg.league if league.college else f"{sg.league}:raw"
                key = f"{prefix}:{T.college_norm(label)}"
                name, short, names = label, side.code or label, []
            teams.append(Team(key=key, name=name, short=short, names=list(names)))
        if teams[0].key == teams[1].key:            # never collapse two sides into one team
            teams[1].key += ":2"
        game = Game(league=sg.league, date=sg.date, teams=teams)
        self.games.append(game)
        self._by_day[(sg.league, sg.date)].append(game)
        return game

    @staticmethod
    def _merge(game: Game, sg: SourceGame, mapping: list[int]) -> None:
        if sg.start is not None:
            if game.start is None or START_PRIORITY.get(sg.source, 0) > START_PRIORITY.get(game.start_source or "", 0):
                game.start, game.start_source = sg.start, sg.source
        for i, side in enumerate(sg.sides):
            team = game.teams[mapping[i]]
            for name in side.names + ([side.code] if side.code else []):
                if name and name not in team.names:
                    team.names.append(name)
            if side.home is True and game.home_index is None:
                game.home_index = mapping[i]
        if sg.status and (game.status is None or sg.source == "espn"):
            game.status = sg.status
        for side_index, quote in sg.quotes:
            game.quotes[mapping[side_index]].append(quote)
        game.sources.add(sg.source)
        for key, value in sg.ref.items():
            game.refs.setdefault(f"{sg.source}_{key}", value)
        for note in sg.notes:
            if note not in game.notes:
                game.notes.append(note)
