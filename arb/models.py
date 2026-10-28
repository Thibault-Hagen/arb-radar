"""Shared data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .timeutil import iso

PM = "pm"      # prediction market (exchange contract that pays $1)
BOOK = "book"  # sportsbook bet


@dataclass
class Quote:
    """One price you could take right now for one side of a game."""

    venue: str                  # "kalshi", "polymarket_us", "draftkings", ...
    venue_title: str            # "Kalshi", "DraftKings", ...
    kind: str                   # "exchange" or "book"
    label: str                  # what you'd buy, e.g. "YES Boston" or "Knicks +125"
    price: float                # exchange: $ per contract (0-1); book: decimal odds
    decimal: float              # $ back per $1 spent if it wins, fees included
    fee_rate: float = 0.0
    fee_round: float = 0.0
    american: int | None = None
    size: float | None = None   # contracts available at this price (exchanges)
    url: str | None = None
    updated_at: datetime | None = None
    source: str = ""            # which feed it came from
    indicative: bool = False    # not a firm order-book price; never alerted on
    priority: int = 0           # tie-breaker when two feeds quote the same venue
    ref: dict = field(default_factory=dict)

    @property
    def group(self) -> str:
        return PM if self.kind == "exchange" else BOOK

    def to_dict(self, side: int) -> dict:
        out = {
            "side": side,
            "venue": self.venue,
            "venue_title": self.venue_title,
            "kind": self.kind,
            "label": self.label,
            "price": round(self.price, 4),
            "decimal": round(self.decimal, 5),
            "updated_at": iso(self.updated_at),
            "source": self.source,
        }
        if self.kind == "exchange":
            out["fee_rate"] = round(self.fee_rate, 5)
            out["fee_round"] = self.fee_round
        if self.american is not None:
            out["american"] = self.american
        if self.size is not None:
            out["size"] = round(self.size, 2)
        if self.url:
            out["url"] = self.url
        if self.indicative:
            out["indicative"] = True
        if self.ref.get("note"):
            out["note"] = self.ref["note"]
        return out


@dataclass
class Side:
    """How one source describes one team in a game."""

    names: list[str]
    code: str | None = None
    home: bool | None = None


@dataclass
class SourceGame:
    """A game as one source sees it, before matching across sources."""

    source: str
    league: str
    sides: list[Side]
    quotes: list[tuple[int, Quote]] = field(default_factory=list)
    start: datetime | None = None
    date: date | None = None
    status: str | None = None   # "pre", "in", "post" or None if unknown
    ref: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class Team:
    key: str
    name: str
    short: str
    names: list[str] = field(default_factory=list)


@dataclass
class Game:
    """One real game with every source's quotes attached."""

    league: str
    date: date
    teams: list[Team]
    start: datetime | None = None
    start_source: str | None = None
    home_index: int | None = None
    status: str | None = None
    quotes: dict[int, list[Quote]] = field(default_factory=lambda: {0: [], 1: []})
    sources: set[str] = field(default_factory=set)
    refs: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        teams = "|".join(sorted(t.key for t in self.teams))
        return f"{self.league}:{self.date.isoformat()}:{teams}"

    @property
    def team_keys(self) -> set[str]:
        return {t.key for t in self.teams}

    @property
    def title(self) -> str:
        a, b = self.teams
        if self.home_index == 1:
            return f"{a.name} @ {b.name}"
        if self.home_index == 0:
            return f"{b.name} @ {a.name}"
        return f"{a.name} vs {b.name}"
