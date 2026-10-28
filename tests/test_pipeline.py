import json
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from arb.config import Secrets, load_settings
from arb.demo import DEMO_LEAGUES, DEMO_NOW, demo_fetcher
from arb.pipeline import run_scan
from arb.timeutil import parse_iso


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "site"
        self.settings = load_settings()
        self.settings.leagues = list(DEMO_LEAGUES)
        self.secrets = Secrets(odds_api_key="test", ntfy_topic="arb-test-topic", site_url="https://example.github.io/arb-radar/")
        self.now = parse_iso(DEMO_NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, fetcher=None, prev=None, now=None):
        fetcher = fetcher or demo_fetcher()
        summary = run_scan(self.settings, fetcher, prev, self.out, now or self.now, self.secrets, log=lambda *_: None)
        data = json.loads((self.out / "data" / "latest.json").read_text())
        return summary, data, fetcher

    def test_finds_the_planted_arb(self):
        summary, data, fetcher = self.scan()
        self.assertEqual(summary["arbs"], 1)
        opp = data["opportunities"][0]
        self.assertEqual(opp["title"], "Boston Celtics @ New York Knicks")
        self.assertEqual([leg["venue"] for leg in opp["legs"]], ["kalshi", "draftkings"])
        self.assertAlmostEqual(opp["margin"], 0.0184, places=4)
        self.assertEqual(opp["plan"]["profit"], 1.82)
        self.assertTrue(all(s["ok"] for s in data["sources"]))
        kalshi = next(s for s in data["sources"] if s["id"] == "kalshi")
        self.assertEqual(kalshi["matched"], kalshi["games"])        # every Kalshi game lined up
        self.assertFalse(any("apiKey=test" in url for url in fetcher.seen))

    def test_alert_sent_once_then_deduplicated(self):
        _, data, fetcher = self.scan()
        self.assertEqual(len(fetcher.posts), 1)
        url, payload = fetcher.posts[0]
        self.assertEqual(url, "https://ntfy.sh/")
        self.assertEqual(payload["topic"], "arb-test-topic")
        self.assertIn("+1.84%", payload["title"])
        self.assertIn("101 contracts", payload["message"])
        prev = Path(self.tmp.name) / "prev"
        (self.out / "data").rename(prev)
        _, _, fetcher2 = self.scan(prev=prev, now=self.now + timedelta(minutes=15))
        self.assertEqual(fetcher2.posts, [])

    def test_alert_venues_respected(self):
        self.settings.alerts.venues = ["kalshi", "polymarket_us"]       # e.g. under 21: no sportsbooks
        _, data, fetcher = self.scan()
        self.assertEqual(fetcher.posts, [])
        self.assertEqual(len(data["opportunities"]), 1)               # still shown on the dashboard

    def test_budget_and_cache_carry_over(self):
        self.scan()
        prev = Path(self.tmp.name) / "prev"
        (self.out / "data").rename(prev)
        _, data, fetcher = self.scan(prev=prev, now=self.now + timedelta(minutes=20))
        self.assertFalse(any("the-odds-api" in url for url in fetcher.seen))   # too soon to spend a credit
        self.assertEqual(data["odds_api"]["decisions"]["NBA"], "refreshed 20 min ago")
        sportsbooks = {q["venue"] for g in data["games"] for q in g["quotes"]}
        self.assertIn("fanduel", sportsbooks)                          # cached odds still shown
        history = json.loads((self.out / "data" / "history.json").read_text())
        self.assertEqual(history["items"][0]["scans"], 2)

    def test_source_failure_is_reported_not_fatal(self):
        fetcher = demo_fetcher()
        fetcher.routes = [r for r in fetcher.routes if "kalshi" not in r[0].pattern]
        _, data, fetcher = self.scan(fetcher=fetcher)
        kalshi = next(s for s in data["sources"] if s["id"] == "kalshi")
        self.assertFalse(kalshi["ok"])
        self.assertTrue(kalshi["errors"])
        # The Odds API's relayed Kalshi price still shows the arb, flagged as indicative...
        leg = data["opportunities"][0]["legs"][0]
        self.assertEqual((leg["venue"], leg["source"], leg.get("indicative")), ("kalshi", "odds_api", True))
        # ...but an unconfirmed price never triggers a push alert.
        self.assertEqual(fetcher.posts, [])

    def test_started_games_are_excluded(self):
        _, data, _ = self.scan(now=parse_iso("2026-10-28T23:45:00Z"))
        titles = {g["title"] for g in data["games"]}
        self.assertNotIn("Boston Celtics @ New York Knicks", titles)
        self.assertIn("Los Angeles Lakers @ Golden State Warriors", titles)

    def test_odds_api_rejecting_extras_falls_back(self):
        from arb.http import HttpError
        fetcher = demo_fetcher()
        rejected = (re.compile(r"the-odds-api\.com/.*includeLinks=true"), HttpError("HTTP 422", 422), None)
        fetcher.routes.insert(0, rejected)
        _, data, fetcher = self.scan(fetcher=fetcher)
        state = json.loads((self.out / "data" / "state.json").read_text())
        self.assertTrue(state["odds_api_plain"])
        venues = {q["venue"] for g in data["games"] for q in g["quotes"]}
        self.assertIn("fanduel", venues)
        self.assertFalse(any("includeLinks" not in u and "kalshi%2Cpolymarket_us" in u for u in fetcher.seen))
        self.assertEqual(data["odds_api"]["decisions"]["NBA"], "refreshed now")

    def test_polymarket_league_found_without_league_list(self):
        fetcher = demo_fetcher()
        fetcher.routes.insert(0, (re.compile(r"gateway\.polymarket\.us/v2/leagues\?"), {"leagues": []}, None))
        _, data, fetcher = self.scan(fetcher=fetcher)
        self.assertTrue(any("/v2/leagues/nba/events" in url for url in fetcher.seen))
        venues = {q["venue"] for g in data["games"] if g["league"] == "NBA" for q in g["quotes"]}
        self.assertIn("polymarket_us", venues)
        status = next(s for s in data["sources"] if s["id"] == "polymarket_us")
        self.assertEqual(status["errors"], [])          # leagues it doesn't carry aren't errors

    def test_games_outside_the_window_are_ignored(self):
        _, data, _ = self.scan(now=parse_iso("2026-10-20T15:00:00Z"))
        self.assertEqual(data["games"], [])
        kalshi = next(s for s in data["sources"] if s["id"] == "kalshi")
        self.assertEqual(kalshi["games"], 0)

    def test_espn_lines_carry_a_lag_warning(self):
        self.secrets.odds_api_key = ""          # DraftKings then comes only from ESPN
        _, data, _ = self.scan()
        warnings = data["opportunities"][0]["warnings"]
        self.assertTrue(any("ESPN's copy" in w for w in warnings))

    def test_no_odds_key_still_works(self):
        self.secrets.odds_api_key = ""
        _, data, fetcher = self.scan()
        self.assertFalse(any("the-odds-api" in url for url in fetcher.seen))
        self.assertEqual(len(data["opportunities"]), 1)                # ESPN's DraftKings line is enough
        self.assertIn("ODDS_API_KEY", next(s for s in data["sources"] if s["id"] == "odds_api")["note"])


if __name__ == "__main__":
    unittest.main()
