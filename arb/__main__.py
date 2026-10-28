"""Command line entry point: `python -m arb`."""

from __future__ import annotations

import argparse
import json
import sys

from .config import DEFAULT_CONFIG, Secrets, load_settings
from .http import Fetcher
from .pipeline import run_scan
from .timeutil import parse_iso, utcnow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arb",
                                     description="Scan for prediction-market / sportsbook arbitrage.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to config.toml")
    parser.add_argument("--out", default="site", help="folder to write data/ into")
    parser.add_argument("--prev", default=None, help="previous run's data folder (keeps history and budget)")
    parser.add_argument("--demo", action="store_true", help="use the bundled sample data (no internet)")
    parser.add_argument("--now", default=None, help="pretend it is this UTC time (ISO 8601)")
    parser.add_argument("--no-alerts", action="store_true", help="don't send push alerts")
    args = parser.parse_args(argv)

    settings = load_settings(args.config)
    secrets = Secrets.from_env()
    if args.demo:
        from .demo import DEMO_LEAGUES, DEMO_NOW, demo_fetcher

        fetcher = demo_fetcher()
        settings.leagues = list(DEMO_LEAGUES)
        secrets = Secrets(odds_api_key="demo")
        now = parse_iso(args.now or DEMO_NOW)
    else:
        fetcher = Fetcher()
        now = parse_iso(args.now) if args.now else utcnow()

    summary = run_scan(settings, fetcher, args.prev, args.out, now, secrets,
                       send=not (args.no_alerts or args.demo))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
