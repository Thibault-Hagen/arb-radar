import unittest

from arb.teams import resolve, similarity


class ResolveTests(unittest.TestCase):
    def check(self, league, expected, names, code=None):
        self.assertEqual(resolve(league, names, code), expected, f"{league} {names} {code}")

    def test_kalshi_style_labels(self):
        self.check("NBA", "NBA:NYK", ["New York K"], "NYK")
        self.check("NBA", "NBA:LAL", ["Los Angeles L"])
        self.check("NBA", "NBA:LAC", ["Los Angeles C"])
        self.check("NFL", "NFL:NYG", ["New York G"])
        self.check("NFL", "NFL:NYJ", ["New York J"])
        self.check("NHL", "NHL:NYR", ["New York R"])
        self.check("MLB", "MLB:CWS", ["Chicago WS"])
        self.check("MLB", "MLB:CHC", ["Chicago C"])

    def test_espn_abbreviations(self):
        self.check("NBA", "NBA:GSW", ["Golden State Warriors"], "GS")
        self.check("NBA", "NBA:UTA", [], "UTAH")
        self.check("NBA", "NBA:NOP", [], "NO")
        self.check("NHL", "NHL:NJD", [], "NJ")
        self.check("NHL", "NHL:LAK", [], "LA")
        self.check("NFL", "NFL:LAR", [], "LA")
        self.check("NFL", "NFL:WAS", [], "WSH")
        self.check("MLB", "MLB:ATH", ["Athletics"], "ATH")

    def test_full_and_nick_names(self):
        self.check("NBA", "NBA:BOS", ["Celtics"])
        self.check("NBA", "NBA:PHI", ["Philadelphia 76ers"])
        self.check("NBA", "NBA:PHI", ["Sixers"])
        self.check("NHL", "NHL:MTL", ["Montréal Canadiens"])
        self.check("NHL", "NHL:UTA", ["Utah Mammoth"])
        self.check("NHL", "NHL:STL", ["St. Louis Blues"])
        self.check("MLB", "MLB:ATH", ["Oakland Athletics"])
        self.check("NBA", "NBA:GSW", ["Golden State"])

    def test_ambiguous_returns_none(self):
        self.check("NBA", None, ["Los Angeles"])
        self.check("NFL", None, ["New York"])
        self.check("MLB", None, ["Chicago"])
        self.check("NBA", None, ["LA"])

    def test_college_similarity(self):
        self.assertEqual(similarity("Ohio St.", "Ohio State"), 1.0)
        self.assertEqual(similarity("Ohio", "Ohio"), 1.0)
        self.assertLess(similarity("Ohio", "Ohio State"), 0.85)
        self.assertGreater(similarity("Miami (OH)", "Miami (OH) RedHawks"), 0.8)
        self.assertLess(similarity("Miami (OH)", "Miami Hurricanes"), 0.6)
        self.assertEqual(similarity("St. John's", "Saint John's"), 1.0)


if __name__ == "__main__":
    unittest.main()
