import unittest
from datetime import date, datetime, timedelta, timezone

from arb.engine import best_combo, find_opportunities, margin_of, stake_plan, usable_quotes
from arb.fees import FeeModel
from arb.models import Game, Quote, Team
from arb.odds import american_to_decimal, decimal_to_american, parse_american

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
KALSHI = FeeModel(0.07, 0.01)


def exchange(venue, price, fees=KALSHI, **kw):
    return Quote(venue=venue, venue_title=venue.title(), kind="exchange", label=f"YES {venue}",
                 price=price, decimal=fees.effective_decimal(price), fee_rate=fees.rate,
                 fee_round=fees.round_to, updated_at=NOW, priority=3, **kw)


def book(venue, decimal_odds, **kw):
    return Quote(venue=venue, venue_title=venue.title(), kind="book", label=f"{venue}",
                 price=decimal_odds, decimal=decimal_odds, updated_at=NOW, priority=2, **kw)


def game(quotes0, quotes1, league="NBA", start=NOW + timedelta(hours=8)):
    g = Game(league=league, date=date(2026, 10, 28), start=start,
             teams=[Team("NBA:BOS", "Boston Celtics", "BOS"), Team("NBA:NYK", "New York Knicks", "NYK")])
    g.quotes = {0: list(quotes0), 1: list(quotes1)}
    return g


class OddsTests(unittest.TestCase):
    def test_conversions(self):
        self.assertAlmostEqual(american_to_decimal(-150), 1.6667, places=4)
        self.assertAlmostEqual(american_to_decimal(125), 2.25)
        self.assertEqual(decimal_to_american(2.25), 125)
        self.assertEqual(decimal_to_american(1.6667), -150)
        self.assertEqual(parse_american("+125"), 125)
        self.assertEqual(parse_american("EVEN"), 100)
        self.assertIsNone(parse_american("5.5"))
        self.assertIsNone(parse_american(None))


class FeeTests(unittest.TestCase):
    def test_kalshi_published_examples(self):
        # Kalshi fee schedule: 100 contracts at 55c cost $1.74; the 50c maximum is $1.75.
        self.assertAlmostEqual(KALSHI.order_fee(100, 0.55), 1.74)
        self.assertAlmostEqual(KALSHI.order_fee(100, 0.50), 1.75)
        self.assertAlmostEqual(KALSHI.order_fee(1, 0.50), 0.02)   # rounded up to the cent

    def test_polymarket_us_sports(self):
        self.assertAlmostEqual(FeeModel(0.05, 0.01).order_fee(100, 0.50), 1.25)

    def test_effective_decimal_includes_fee(self):
        self.assertAlmostEqual(1 / KALSHI.effective_decimal(0.52), 0.52 + 0.07 * 0.52 * 0.48)


class EngineTests(unittest.TestCase):
    def test_margin(self):
        self.assertAlmostEqual(margin_of([2.0, 2.0]), 0.0)
        self.assertLess(margin_of([1.91, 1.91]), 0)        # standard -110/-110 vig
        self.assertGreater(margin_of([2.1, 2.05]), 0)

    def test_stake_plan_equalises_payouts(self):
        plan = stake_plan([exchange("kalshi", 0.52), book("draftkings", 2.25)], 100)
        kalshi_leg, book_leg = plan["legs"]
        self.assertEqual(kalshi_leg["contracts"], 101)
        self.assertAlmostEqual(kalshi_leg["fee"], 1.77)           # 0.07*101*.52*.48 = 1.7647 -> 1.77
        self.assertAlmostEqual(kalshi_leg["cost"], 54.29)
        self.assertAlmostEqual(book_leg["bet"], 44.89)
        self.assertAlmostEqual(plan["payout"], 101.0)
        self.assertAlmostEqual(plan["profit"], 1.82)

    def test_best_combo_prefers_cross_venue(self):
        per_side = {0: [exchange("kalshi", 0.52), book("fanduel", 1.65)],
                    1: [book("draftkings", 2.25), exchange("kalshi", 0.49)]}
        margin, legs, kind = best_combo(per_side)
        self.assertEqual([q.venue for q in legs], ["kalshi", "draftkings"])
        self.assertEqual(kind, "pm-book")
        self.assertAlmostEqual(margin, 0.0184, places=4)

    def test_same_venue_only_when_it_is_an_arb(self):
        per_side = {0: [exchange("kalshi", 0.47)], 1: [exchange("kalshi", 0.48), book("fanduel", 1.5)]}
        margin, legs, _ = best_combo(per_side)
        self.assertEqual([q.venue for q in legs], ["kalshi", "kalshi"])
        self.assertGreater(margin, 0)

    def test_pair_filter(self):
        per_side = {0: [exchange("kalshi", 0.52), exchange("polymarket_us", 0.55)],
                    1: [book("draftkings", 2.25), exchange("polymarket_us", 0.48)]}
        _, legs, kind = best_combo(per_side, pair="pm-pm")
        self.assertEqual(kind, "pm-pm")
        self.assertEqual([q.venue for q in legs], ["kalshi", "polymarket_us"])

    def test_dedupes_same_venue_preferring_direct_feed(self):
        relayed = exchange("kalshi", 0.50, source="odds_api", indicative=True)
        relayed.priority = 1
        direct = exchange("kalshi", 0.52, source="kalshi")
        per_side = usable_quotes(game([relayed, direct], [book("draftkings", 2.25)]), NOW)
        self.assertEqual(len(per_side[0]), 1)
        self.assertIs(per_side[0][0], direct)

    def test_stale_quotes_dropped(self):
        old = book("fanduel", 2.6)
        old.updated_at = NOW - timedelta(hours=5)
        g = game([exchange("kalshi", 0.52)], [old, book("draftkings", 2.25)])
        per_side = usable_quotes(g, NOW, max_age=timedelta(hours=4))
        self.assertEqual([q.venue for q in per_side[1]], ["draftkings"])

    def test_find_opportunities_splits_arbs_and_misses(self):
        arb_game = game([exchange("kalshi", 0.52)], [book("draftkings", 2.25)])
        miss_game = game([exchange("kalshi", 0.60)], [book("draftkings", 1.9)])
        arbs, misses = find_opportunities([arb_game, miss_game], NOW, 100, 0.0, 10)
        self.assertEqual(len(arbs), 1)
        self.assertEqual(len(misses), 1)
        self.assertGreater(arbs[0].margin, 0)

    def test_nfl_warning(self):
        g = game([exchange("kalshi", 0.52)], [book("draftkings", 2.25)], league="NFL")
        arbs, _ = find_opportunities([g], NOW, 100, 0.0, 10)
        self.assertTrue(any("tie" in w for w in arbs[0].warnings))

    def test_thin_liquidity_warning(self):
        g = game([exchange("kalshi", 0.52, size=20)], [book("draftkings", 2.25)])
        arbs, _ = find_opportunities([g], NOW, 100, 0.0, 10)
        self.assertTrue(any("Only 20 contracts" in w for w in arbs[0].warnings))


if __name__ == "__main__":
    unittest.main()
