"""Data sources. Each module fetches raw JSON and turns it into SourceGame objects."""

from __future__ import annotations


def to_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        value = value.get("value")
        if value is None:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def dig(obj, *path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


# Where to send someone to place a sportsbook bet (generic pages, no tracking).
BOOK_HOMEPAGES = {
    "draftkings": "https://sportsbook.draftkings.com/",
    "fanduel": "https://sportsbook.fanduel.com/",
    "betmgm": "https://sports.betmgm.com/",
    "williamhill_us": "https://www.caesars.com/sportsbook-and-casino",
    "betrivers": "https://www.betrivers.com/",
    "fanatics": "https://sportsbook.fanatics.com/",
    "espnbet": "https://thescore.bet/",
    "hardrockbet": "https://www.hardrock.bet/",
    "betparx": "https://www.betparx.com/",
    "ballybet": "https://www.ballybet.com/",
}

BOOK_TITLES = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "betrivers": "BetRivers",
    "fanatics": "Fanatics",
    "espnbet": "theScore Bet",
    "hardrockbet": "Hard Rock Bet",
    "betparx": "betPARX",
    "ballybet": "Bally Bet",
}
