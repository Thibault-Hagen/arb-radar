import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from arb.fees import FeeModel
from arb.leagues import LEAGUES
from arb.sources import espn, kalshi, odds_api, polymarket_us

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FIX / name).read_text())


class EspnTests(unittest.TestCase):
    def test_moneyline_close_odds(self):
        games = espn.parse_scoreboard(load("espn_nba_20261028.json"), "NBA", NOW)
        self.assertEqual(len(games), 2)
        bos_nyk = games[0]
        self.assertEqual(bos_nyk.sides[0].code, "BOS")        # away first
        self.assertTrue(bos_nyk.sides[1].home)
        prices = {(i, q.venue): q.american for i, q in bos_nyk.quotes}
        self.assertEqual(prices, {(0, "draftkings"): -150, (1, "draftkings"): 125})

    def test_team_odds_fallback_and_status(self):
        games = espn.parse_scoreboard(load("espn_nhl_20261028.json"), "NHL", NOW)
        self.assertEqual(games[0].quotes[0][1].american, 105)
        self.assertEqual(games[1].status, "post")


class KalshiTests(unittest.TestCase):
    def setUp(self):
        self.games = kalshi.parse_events(load("kalshi_events_nba.json")["events"], "NBA",
                                         load("kalshi_series_nba.json")["series"], 0.07, 0.01, NOW)

    def test_ticker_date(self):
        self.assertEqual(kalshi.ticker_date("KXNBAGAME-26OCT28BOSNYK").isoformat(), "2026-10-28")
        self.assertIsNone(kalshi.ticker_date("KXNBAGAME-BAD"))

    def test_closed_events_skipped(self):
        self.assertEqual(len(self.games), 2)

    def test_yes_and_no_quotes(self):
        game = self.games[0]
        self.assertEqual([s.code for s in game.sides], ["BOS", "NYK"])
        boston = sorted((q for i, q in game.quotes if i == 0), key=lambda q: q.price)
        self.assertEqual([(q.label, q.price) for q in boston], [("YES Boston", 0.52), ("NO New York K", 0.53)])
        self.assertEqual(boston[0].size, 350.0)
        self.assertEqual(boston[1].size, 410.0)                 # NO ask size = the other YES bid size
        self.assertIn("kxnbagame-26oct28bosnyk", boston[0].url)

    def test_fee_multiplier(self):
        series = {"fee_multiplier": 0.5}
        games = kalshi.parse_events(load("kalshi_events_nba.json")["events"], "MLB", series, 0.07, 0.01, NOW)
        self.assertAlmostEqual(games[0].quotes[0][1].fee_rate, 0.035)
        self.assertEqual(kalshi.fee_multiplier({"fee_multiplier": 1}, {"fee_multiplier_override": 0.25}), 0.25)

    def test_cent_fields_fallback(self):
        self.assertEqual(kalshi.dollars({"yes_ask": 37}, "yes_ask"), 0.37)


class PolymarketUSTests(unittest.TestCase):
    def test_league_slug(self):
        leagues = load("pmus_leagues.json")["leagues"]
        self.assertEqual(polymarket_us.pick_league_slug(leagues, LEAGUES["NBA"]), "nba")
        self.assertEqual(polymarket_us.pick_league_slug(leagues, LEAGUES["NCAAF"]), "cfb")
        self.assertIsNone(polymarket_us.pick_league_slug(leagues, LEAGUES["NCAAB"]))

    def test_moneyline_long_and_short(self):
        games = polymarket_us.parse_events(load("pmus_events_nba.json")["events"], "NBA", 0.05, 0.01, NOW)
        self.assertEqual(len(games), 2)
        game = games[0]
        self.assertEqual(game.sides[0].code, "BOS")
        prices = {i: q.price for i, q in game.quotes}
        self.assertEqual(prices, {0: 0.55, 1: 0.47})              # short side = 1 - best bid
        self.assertEqual(game.date.isoformat(), "2026-10-28")

    def test_moneyline_detection(self):
        detect = polymarket_us._is_moneyline
        self.assertTrue(detect({"sportsMarketType": "football_team_full_game_winner"}))
        self.assertTrue(detect({"sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"}))
        self.assertTrue(detect({"marketType": "moneyline"}))
        self.assertFalse(detect({"sportsMarketType": "basketball_team_full_game_spread",
                                 "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}))

    def test_bbo_refresh(self):
        game = polymarket_us.parse_events(load("pmus_events_nba.json")["events"], "NBA", 0.05, 0.01, NOW)[0]
        quotes = [q for _, q in game.quotes]
        kept = polymarket_us.apply_bbo(quotes, load("pmus_bbo_bos_nyk.json")["marketData"], NOW)
        self.assertEqual({q.ref["position"]: q.price for q in kept}, {"long": 0.55, "short": 0.48})
        self.assertEqual({q.ref["position"]: q.size for q in kept}, {"long": 1200.0, "short": 800.0})
        self.assertEqual(polymarket_us.apply_bbo(quotes, {"state": "MARKET_STATE_HALTED"}, NOW), [])

    def test_fallback_price_is_indicative(self):
        event = load("pmus_events_nba.json")["events"][0]
        market = next(m for m in event["markets"] if m["slug"].startswith("aec-"))
        market.pop("bestBidQuote")
        market.pop("bestAskQuote")
        game = polymarket_us.parse_events([event], "NBA", 0.05, 0.01, NOW)[0]
        self.assertTrue(all(q.indicative for _, q in game.quotes))


class OddsApiTests(unittest.TestCase):
    def test_parse(self):
        fees = {"kalshi": FeeModel(0.07, 0.01)}
        games = odds_api.parse_odds(load("odds_api_nba.json"), "NBA", fees, NOW)
        self.assertEqual(len(games), 2)
        quotes = {(i, q.venue): q for i, q in games[0].quotes}
        self.assertEqual(quotes[(1, "draftkings")].decimal, 2.25)
        self.assertEqual(quotes[(1, "draftkings")].american, 125)
        self.assertTrue(quotes[(0, "kalshi")].indicative)          # relayed exchange price
        self.assertEqual(quotes[(0, "kalshi")].kind, "exchange")
        self.assertIn("draftkings.com/event", quotes[(1, "draftkings")].url)

    def test_credit_cost(self):
        self.assertEqual(odds_api.credit_cost(["a"] * 10), 1)
        self.assertEqual(odds_api.credit_cost(["a"] * 11), 2)
        self.assertEqual(odds_api.credit_cost([]), 1)


if __name__ == "__main__":
    unittest.main()
