"""Odds format conversions."""

from __future__ import annotations


def american_to_decimal(american: float) -> float:
    value = float(american)
    if value >= 100:
        return 1.0 + value / 100.0
    if value <= -100:
        return 1.0 + 100.0 / abs(value)
    raise ValueError(f"not valid American odds: {american!r}")


def decimal_to_american(decimal_odds: float) -> int:
    d = float(decimal_odds)
    if d <= 1.0:
        raise ValueError(f"decimal odds must be above 1.0: {decimal_odds!r}")
    if d >= 2.0:
        return int(round((d - 1.0) * 100))
    return int(round(-100.0 / (d - 1.0)))


def parse_american(value) -> float | None:
    """Accepts -150, '+125', '-110', 'EVEN', 'EV'. Returns None if unusable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().upper().replace("−", "-")
        if text in ("EVEN", "EV", "PK"):
            return 100.0
        try:
            number = float(text.replace("+", ""))
        except ValueError:
            return None
    if number >= 100 or number <= -100:
        return number
    return None


def fmt_american(value: float) -> str:
    number = int(round(value))
    return f"+{number}" if number > 0 else str(number)
