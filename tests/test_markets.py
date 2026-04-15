import unittest
import json
from data.markets import _parse_market

class TestMarkets(unittest.TestCase):
    def test_parse_market_valid(self):
        m = {
            "id": "m123",
            "question": "Will X happen?",
            "slug": "will-x-happen",
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["0.6", "0.4"]),
            "liquidityNum": 1000,
            "volumeNum": 5000,
            "oneDayPriceChange": 0.05,
            "lastTradePrice": 0.6,
            "endDate": "2024-12-31T23:59:59Z",
            "tags": [{"slug": "politics"}, {"slug": "elections"}],
            "active": True,
            "closed": False
        }
        res = _parse_market(m)
        self.assertIsNotNone(res)
        self.assertEqual(res["market_id"], "m123")
        self.assertEqual(res["yes_price"], 0.6)
        self.assertEqual(res["no_price"], 0.4)
        self.assertEqual(res["tags"], "politics,elections")

    def test_parse_market_invalid_json(self):
        m = {
            "outcomes": "invalid json",
            "outcomePrices": json.dumps(["0.6", "0.4"])
        }
        self.assertIsNone(_parse_market(m))

    def test_parse_market_wrong_number_of_outcomes(self):
        m = {
            "outcomes": json.dumps(["Yes", "No", "Maybe"]),
            "outcomePrices": json.dumps(["0.3", "0.3", "0.4"])
        }
        self.assertIsNone(_parse_market(m))

    def test_parse_market_wrong_number_of_prices(self):
        m = {
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["0.6"])
        }
        self.assertIsNone(_parse_market(m))

    def test_parse_market_invalid_price_format(self):
        m = {
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["invalid", "0.4"])
        }
        self.assertIsNone(_parse_market(m))

    def test_parse_market_missing_fields(self):
        # Even with missing optional fields, it should return None if outcomes/prices missing?
        # If missing, it defaults to '[]', so len is 0, which != 2
        self.assertIsNone(_parse_market({}))

if __name__ == '__main__':
    unittest.main()
