"""Reads config.toml (settings) and environment variables (secrets)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .leagues import LEAGUES

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.toml"


@dataclass
class OddsApiSettings:
    bookmakers: list = field(default_factory=list)
    monthly_credits: int = 500
    reset_day: int = 1
    max_credits_per_day: int = 25
    min_minutes_between_calls: int = 90
    lookahead_hours: int = 36


@dataclass
class AlertSettings:
    venues: list = field(default_factory=list)
    min_margin: float = 0.005
    max_quote_age_minutes: int = 20
    realert_hours: float = 6


@dataclass
class Settings:
    leagues: list = field(default_factory=lambda: list(LEAGUES))
    days_ahead: int = 2
    include_live: bool = False
    min_margin: float = 0.0
    stake: float = 100.0
    near_miss_count: int = 15
    max_quote_age_minutes: int = 240
    timezone: str = "America/Chicago"
    sources: dict = field(default_factory=lambda: {"kalshi": True, "polymarket_us": True,
                                                   "espn": True, "odds_api": True})
    kalshi_taker_rate: float = 0.07
    polymarket_us_taker_rate: float = 0.05
    round_fees_to_cents: bool = True
    odds_api: OddsApiSettings = field(default_factory=OddsApiSettings)
    alerts: AlertSettings = field(default_factory=AlertSettings)

    @property
    def fee_round(self) -> float:
        return 0.01 if self.round_fees_to_cents else 0.0


def load_settings(path: Path | str | None = None) -> Settings:
    path = Path(path) if path else DEFAULT_CONFIG
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    scan, fees = raw.get("scan", {}), raw.get("fees", {})
    s = Settings()
    s.leagues = [code.upper() for code in scan.get("leagues", s.leagues) if code.upper() in LEAGUES]
    s.days_ahead = int(scan.get("days_ahead", s.days_ahead))
    s.include_live = bool(scan.get("include_live", s.include_live))
    s.min_margin = float(scan.get("min_margin", s.min_margin))
    s.stake = float(scan.get("stake", s.stake))
    s.near_miss_count = int(scan.get("near_miss_count", s.near_miss_count))
    s.max_quote_age_minutes = int(scan.get("max_quote_age_minutes", s.max_quote_age_minutes))
    s.timezone = str(scan.get("timezone", s.timezone))
    s.sources.update({k: bool(v) for k, v in raw.get("sources", {}).items()})
    s.kalshi_taker_rate = float(fees.get("kalshi_taker_rate", s.kalshi_taker_rate))
    s.polymarket_us_taker_rate = float(fees.get("polymarket_us_taker_rate", s.polymarket_us_taker_rate))
    s.round_fees_to_cents = bool(fees.get("round_fees_to_cents", s.round_fees_to_cents))
    oa = raw.get("odds_api", {})
    s.odds_api = OddsApiSettings(
        bookmakers=[str(b) for b in oa.get("bookmakers", [])],
        monthly_credits=int(oa.get("monthly_credits", 500)),
        reset_day=int(oa.get("reset_day", 1)),
        max_credits_per_day=int(oa.get("max_credits_per_day", 25)),
        min_minutes_between_calls=int(oa.get("min_minutes_between_calls", 90)),
        lookahead_hours=int(oa.get("lookahead_hours", 36)),
    )
    al = raw.get("alerts", {})
    s.alerts = AlertSettings(
        venues=[str(v) for v in al.get("venues", [])],
        min_margin=float(al.get("min_margin", 0.005)),
        max_quote_age_minutes=int(al.get("max_quote_age_minutes", 20)),
        realert_hours=float(al.get("realert_hours", 6)),
    )
    return s


@dataclass
class Secrets:
    odds_api_key: str = ""
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    discord_webhook: str = ""
    site_url: str = ""

    @classmethod
    def from_env(cls) -> "Secrets":
        env = os.environ
        return cls(
            odds_api_key=env.get("ODDS_API_KEY", "").strip(),
            ntfy_topic=env.get("NTFY_TOPIC", "").strip(),
            ntfy_server=env.get("NTFY_SERVER", "").strip() or "https://ntfy.sh",
            discord_webhook=env.get("DISCORD_WEBHOOK_URL", "").strip(),
            site_url=env.get("SITE_URL", "").strip(),
        )
