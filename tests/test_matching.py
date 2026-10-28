import unittest
from datetime import date, datetime, timezone

from arb.matching import CREATED, MATCHED, SKIPPED, GameBook
from arb.models import Side, SourceGame


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def espn_game(league, away, home, start, away_code=None, home_code=None):
    return SourceGame(source="espn", league=league, start=start,
                      sides=[Side([away], away_code, home=False), Side([home], home_code, home=True)])


def kalshi_game(league, labels, codes, day):
    return SourceGame(source="kalshi", league=league, date=day,
                      sides=[Side([labels[0]], codes[0]), Side([labels[1]], codes[1])])


class ProMatching(unittest.TestCase):
    def test_late_game_matches_on_eastern_date(self):
        book = GameBook()
        book.add(espn_game("NBA", "Los Angeles Lakers", "Golden State Warriors", utc(2026, 10, 29, 2, 0), "LAL", "GS"))
        game, verdict = book.add(kalshi_game("NBA", ["Los Angeles L", "Golden State"], ["LAL", "GSW"], date(2026, 10, 28)))
        self.assertEqual(verdict, MATCHED)
        self.assertEqual(game.title, "Los Angeles Lakers @ Golden State Warriors")

    def test_utc_dated_source_still_matches(self):
        book = GameBook()
        book.add(espn_game("NBA", "Los Angeles Lakers", "Golden State Warriors", utc(2026, 10, 29, 2, 0), "LAL", "GS"))
        _, verdict = book.add(kalshi_game("NBA", ["Los Angeles L", "Golden State"], ["LAL", "GSW"], date(2026, 10, 29)))
        self.assertEqual(verdict, MATCHED)

    def test_back_to_back_series_keeps_dates_apart(self):
        book = GameBook()
        g1, _ = book.add(espn_game("MLB", "New York Yankees", "Los Angeles Dodgers", utc(2026, 10, 28, 0, 8), "NYY", "LAD"))
        g2, _ = book.add(espn_game("MLB", "New York Yankees", "Los Angeles Dodgers", utc(2026, 10, 29, 0, 8), "NYY", "LAD"))
        self.assertIsNot(g1, g2)
        game, verdict = book.add(kalshi_game("MLB", ["New York Y", "Los Angeles D"], ["NYY", "LAD"], date(2026, 10, 28)))
        self.assertEqual(verdict, MATCHED)
        self.assertIs(game, g2)   # 8:08 PM ET on Oct 28 is 00:08 UTC on Oct 29

    def test_ticker_dated_the_day_before_matches(self):
        book = GameBook()
        game, _ = book.add(espn_game("NFL", "Carolina Panthers", "Green Bay Packers", utc(2026, 11, 1, 17), "CAR", "GB"))
        found, verdict = book.add(kalshi_game("NFL", ["Carolina", "Green Bay"], ["CAR", "GB"], date(2026, 10, 31)))
        self.assertEqual(verdict, MATCHED)
        self.assertIs(found, game)

    def test_ticker_dated_the_day_after_does_not_match(self):
        book = GameBook()
        book.add(espn_game("MLB", "New York Yankees", "Los Angeles Dodgers", utc(2026, 10, 28, 23), "NYY", "LAD"))
        _, verdict = book.add(kalshi_game("MLB", ["New York Y", "Los Angeles D"], ["NYY", "LAD"], date(2026, 10, 29)))
        self.assertEqual(verdict, CREATED)

    def test_side_order_is_mapped(self):
        book = GameBook()
        game, _ = book.add(espn_game("NHL", "New York Rangers", "Boston Bruins", utc(2026, 10, 28, 23), "NYR", "BOS"))
        sg = kalshi_game("NHL", ["Boston", "New York R"], ["BOS", "NYR"], date(2026, 10, 28))
        from arb.models import Quote
        sg.quotes.append((0, Quote("kalshi", "Kalshi", "exchange", "YES Boston", 0.55, 1.75)))
        book.add(sg)
        self.assertEqual([q.label for q in game.quotes[1]], ["YES Boston"])   # Bruins are side 1

    def test_half_resolved_label_uses_the_known_team(self):
        book = GameBook()
        game, _ = book.add(espn_game("NBA", "Boston Celtics", "New York Knicks", utc(2026, 10, 28, 23, 30), "BOS", "NY"))
        sg = SourceGame(source="polymarket_us", league="NBA", start=utc(2026, 10, 28, 23, 30),
                        sides=[Side(["Celtics"], "BOS"), Side(["NY Knickerbockers"], None)])
        found, verdict = book.add(sg)
        self.assertEqual(verdict, MATCHED)
        self.assertIs(found, game)

    def test_same_team_twice_is_skipped(self):
        book = GameBook()
        _, verdict = book.add(kalshi_game("NBA", ["Boston", "Celtics"], ["BOS", "BOS"], date(2026, 10, 28)))
        self.assertEqual(verdict, SKIPPED)


class CollegeMatching(unittest.TestCase):
    def setUp(self):
        self.book = GameBook()
        self.ohio, _ = self.book.add(SourceGame(
            source="espn", league="NCAAF", start=utc(2026, 10, 29, 23, 30),
            sides=[Side(["Ohio Bobcats", "Ohio"], "OHIO", False), Side(["Miami (OH) RedHawks", "Miami (OH)"], "M-OH", True)]))
        self.osu, _ = self.book.add(SourceGame(
            source="espn", league="NCAAF", start=utc(2026, 10, 30, 0, 0),
            sides=[Side(["Ohio State Buckeyes", "Ohio State"], "OSU", False),
                   Side(["Penn State Nittany Lions", "Penn State"], "PSU", True)]))

    def test_ohio_is_not_ohio_state(self):
        game, verdict = self.book.add(kalshi_game("NCAAF", ["Ohio", "Miami (OH)"], ["OHIO", "MOH"], date(2026, 10, 29)))
        self.assertEqual(verdict, MATCHED)
        self.assertIs(game, self.ohio)
        game, verdict = self.book.add(kalshi_game("NCAAF", ["Ohio St.", "Penn St."], ["OSU", "PSU"], date(2026, 10, 29)))
        self.assertEqual(verdict, MATCHED)
        self.assertIs(game, self.osu)

    def test_saturday_game_filed_under_friday(self):
        saturday, _ = self.book.add(SourceGame(
            source="espn", league="NCAAF", start=utc(2026, 10, 31, 16),
            sides=[Side(["Texas Tech Red Raiders", "Texas Tech"], "TTU", False),
                   Side(["Arizona Wildcats", "Arizona"], "ARIZ", True)]))
        game, verdict = self.book.add(kalshi_game("NCAAF", ["Arizona", "Texas Tech"], ["ARIZ", "TTU"], date(2026, 10, 30)))
        self.assertEqual(verdict, MATCHED)
        self.assertIs(game, saturday)

    def test_unknown_game_is_created(self):
        _, verdict = self.book.add(kalshi_game("NCAAF", ["Toledo", "Kent St."], ["TOL", "KENT"], date(2026, 10, 29)))
        self.assertEqual(verdict, CREATED)


if __name__ == "__main__":
    unittest.main()
