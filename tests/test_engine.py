import unittest
from unittest.mock import patch
from scoring.engine import kelly_bet, get_top_picks, score_market, _spread_efficiency, _price_tension
import pandas as pd
import numpy as np

class TestKellyBet(unittest.TestCase):

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_b_less_than_zero(self):
        """Test when odds are <= 1.0, b <= 0, resulting in 0 bet."""
        # decimal_odds = 0.5 -> b = -0.5
        res = kelly_bet(bankroll=1000, prob=0.6, decimal_odds=0.5)
        self.assertEqual(res['bet_size'], 0)
        self.assertEqual(res['kelly_raw'], 0)
        self.assertEqual(res['kelly_fraction_used'], 0)

        # decimal_odds = 1.0 -> b = 0
        res2 = kelly_bet(bankroll=1000, prob=0.6, decimal_odds=1.0)
        self.assertEqual(res2['bet_size'], 0)
        self.assertEqual(res2['kelly_raw'], 0)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_negative_edge(self):
        """Test when expected value is negative, kelly_raw <= 0, resulting in 0 bet."""
        # prob = 0.4, decimal_odds = 2.0 (b = 1)
        # expected value = 0.4 * 2 - 1 = -0.2 (negative edge)
        res = kelly_bet(bankroll=1000, prob=0.4, decimal_odds=2.0)
        self.assertEqual(res['bet_size'], 0)
        self.assertEqual(res['kelly_raw'], 0)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_positive_edge_no_cap(self):
        """Test positive edge where the Kelly bet size does not exceed MAX_BET_PCT."""
        # prob = 0.6, decimal_odds = 2.0 (b = 1)
        # kelly_raw = (0.6 * 2 - 1) / 1 = 0.2
        # max_bet = 1000 * 0.05 = 50
        # kelly_adj = 0.2 * 0.25 = 0.05
        # bet_size = 1000 * 0.05 = 50
        # Let's adjust values so it doesn't hit cap
        # prob = 0.6, decimal_odds = 1.5 (b = 0.5)
        # kelly_raw = (0.6 * 1.5 - 1) / 0.5 = (0.9 - 1)/0.5 = -0.2 -> 0
        # Let's use odds = 3.0 (b = 2.0)
        # prob = 0.4, decimal_odds = 3.0 (b = 2.0)
        # kelly_raw = (0.4 * 3.0 - 1) / 2.0 = 0.2 / 2.0 = 0.1
        # kelly_adj = 0.1 * 0.25 = 0.025
        # bet_size = 1000 * 0.025 = 25.0
        res = kelly_bet(bankroll=1000, prob=0.4, decimal_odds=3.0)
        self.assertEqual(res['bet_size'], 25.0)
        self.assertEqual(res['kelly_raw'], 0.1)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_positive_edge_with_cap(self):
        """Test positive edge where the Kelly bet size exceeds MAX_BET_PCT and is capped."""
        # prob = 0.8, decimal_odds = 2.0 (b = 1)
        # kelly_raw = (0.8 * 2 - 1) / 1 = 0.6
        # kelly_adj = 0.6 * 0.25 = 0.15
        # bet_size = 1000 * 0.15 = 150 -> capped at 1000 * 0.05 = 50
        res = kelly_bet(bankroll=1000, prob=0.8, decimal_odds=2.0)
        self.assertEqual(res['bet_size'], 50.0)
        self.assertEqual(res['kelly_raw'], 0.6)

class TestEngine(unittest.TestCase):

    # --- _price_tension Tests ---
    def test_price_tension(self):
        self.assertAlmostEqual(_price_tension(0.5), 1.0, places=4)
        self.assertAlmostEqual(_price_tension(0.0), 0.0, places=4)
        self.assertAlmostEqual(_price_tension(1.0), 0.0, places=4)
        self.assertAlmostEqual(_price_tension(0.25), 0.5, places=4)
        self.assertAlmostEqual(_price_tension(0.75), 0.5, places=4)

    def test_spread_efficiency(self):
        # spread = |1.0 - yes - no|
        self.assertAlmostEqual(_spread_efficiency(0.5, 0.5), 1.0, places=4) # spread = 0
        self.assertAlmostEqual(_spread_efficiency(0.5, 0.46), 0.5, places=4) # spread = 0.04
        self.assertAlmostEqual(_spread_efficiency(0.5, 0.42), 0.0, places=4) # spread = 0.08
        self.assertAlmostEqual(_spread_efficiency(0.5, 0.40), 0.0, places=4) # spread = 0.10 > 0.08

    # --- score_market Tests ---
    def test_score_market_max_score(self):
        row = pd.Series([10**6, 10**7, 0.20, 0.5, 0.5], index=["liquidity", "volume", "one_day_change", "yes_price", "no_price"])
        score = score_market(row)
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_score_market_min_score(self):
        row = pd.Series([0, 0, 0.0, 1.0, 0.08], index=["liquidity", "volume", "one_day_change", "yes_price", "no_price"])
        score = score_market(row)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_score_market_intermediate(self):
        row = pd.Series([1000, 100000, -0.10, 0.75, 0.21], index=["liquidity", "volume", "one_day_change", "yes_price", "no_price"])

        # weights = {"liquidity":0.30, "momentum":0.25, "tension":0.20, "efficiency":0.15, "volume_raw":0.10}

        # total expected = 0.5*0.3 + 0.5*0.25 + 0.5*0.2 + 0.5*0.15 + (5/7)*0.10 = 0.15 + 0.125 + 0.1 + 0.075 + 0.07142857 = 0.52142857
        score = score_market(row)
        self.assertAlmostEqual(score, 0.5214, places=4)

    def test_score_market_negative_liquidity(self):
        row = pd.Series([-100, 10**7, 0.20, 0.5, 0.5], index=["liquidity", "volume", "one_day_change", "yes_price", "no_price"])
        score = score_market(row)
        # liq score should be 0.
        self.assertAlmostEqual(score, 0.7, places=4)

    # --- score_all Tests ---
    def test_score_all(self):

        data = {
            "market_id": ["A", "B"],
            "liquidity": [0, 10**6],
            "volume": [0, 10**7],
            "one_day_change": [0, 0.20],
            "yes_price": [1.0, 0.5],
            "no_price": [0.08, 0.5]
        }
        df = pd.DataFrame(data)
        scored_df = score_all(df)
        self.assertEqual(len(scored_df), 2)
        # Should be sorted descending by score
        self.assertEqual(scored_df.iloc[0]["market_id"], "B")
        self.assertAlmostEqual(scored_df.iloc[0]["score"], 1.0, places=4)
        self.assertEqual(scored_df.iloc[1]["market_id"], "A")
        self.assertAlmostEqual(scored_df.iloc[1]["score"], 0.0, places=4)

        df = pd.DataFrame([["A", 0, 0, 0, 1.0, 0.08], ["B", 10**6, 10**7, 0.20, 0.5, 0.5]], columns=["market_id", "liquidity", "volume", "one_day_change", "yes_price", "no_price"])
        scored = __import__('scoring').engine.score_all(df)
        self.assertEqual(list(scored["market_id"]), ["B", "A"]) # B should score higher than A
        self.assertAlmostEqual(scored.iloc[0]["score"], 1.0, places=4)
        self.assertAlmostEqual(scored.iloc[1]["score"], 0.0, places=4)


    # --- estimate_edge Tests ---
    def test_estimate_edge_yes(self):
        from scoring.engine import estimate_edge
        # score = 1.0 -> adjustment = 0.06
        # yes_price = 0.4
        # true_prob_yes = 0.46 -> edge_yes = 0.06
        # true_prob_no = 0.66 -> edge_no = 0.06
        side, prob, edge = estimate_edge(0.4, 1.0)
        self.assertEqual(side, "YES")
        self.assertAlmostEqual(prob, 0.46, places=4)
        self.assertAlmostEqual(edge, 0.06, places=4)

    def test_estimate_edge_no(self):
        from scoring.engine import estimate_edge
        # score = 1.0 -> adjustment = 0.06
        # yes_price = 0.8
        # true_prob_yes = 0.86 -> edge_yes = 0.06
        # true_prob_no = 0.26 -> edge_no = 0.06
        side, prob, edge = estimate_edge(0.8, 1.0)
        self.assertEqual(side, "YES") # YES defaults on tie

    # --- kelly_bet Tests ---
    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_zero_odds(self):
        res = kelly_bet(1000, 0.5, 0.0)
        self.assertEqual(res["bet_size"], 0.0)
        self.assertEqual(res["kelly_raw"], 0.0)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_positive_edge(self):
        # b = 2.0 - 1 = 1.0
        # prob = 0.6
        # kelly_raw = (0.6 * 2.0 - 1) / 1.0 = 0.2
        # kelly_adj = 0.2 * 0.25 = 0.05
        # size = 1000 * 0.05 = 50.0
        res = kelly_bet(1000, 0.6, 2.0)
        self.assertEqual(res["bet_size"], 50.0)
        self.assertEqual(res["kelly_raw"], 0.2)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_capped(self):
        # b = 3.0 - 1 = 2.0
        # prob = 0.8
        # kelly_raw = (0.8 * 3.0 - 1) / 2.0 = 1.4 / 2.0 = 0.7
        # kelly_adj = 0.7 * 0.25 = 0.175
        # size = 1000 * 0.175 = 175.0 (capped at 50)
        res = kelly_bet(1000, 0.8, 3.0)
        self.assertEqual(res["bet_size"], 50.0)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_negative_edge(self):
        # b = 2.0 - 1 = 1.0
        # prob = 0.4
        # kelly_raw = (0.4 * 2.0 - 1) = -0.2 -> 0.0
        res = kelly_bet(1000, 0.4, 2.0)
        self.assertEqual(res["bet_size"], 0.0)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.05)
    def test_kelly_bet_small_edge(self):
        # b = 2.0 - 1 = 1.0
        # prob = 0.52
        # kelly_raw = (0.52 * 2.0 - 1) = 0.04
        # kelly_adj = 0.04 * 0.25 = 0.01
        # size = 10.0
        res = kelly_bet(1000, 0.52, 2.0)
        self.assertEqual(res["bet_size"], 10.0)
        self.assertEqual(res["kelly_raw"], 0.04)

    # --- get_top_picks Tests ---
    def test_get_top_picks_empty(self):
        self.assertEqual(get_top_picks(pd.DataFrame(), 1000), [])

    def test_get_top_picks(self):

        data = {
            "market_id": ["A", "B"],
            "question": ["Q1", "Q2"],
            "tags": ["T1", "T2"],
            "liquidity": [10**6, 0],
            "volume": [10**7, 0],
            "one_day_change": [0.20, 0],
            "yes_price": [0.5, 1.0],
            "no_price": [0.5, 0.08],
            "end_date": ["2025-01-01", "2025-01-01"]
        }
        df = pd.DataFrame(data)

        df = pd.DataFrame([["A", "Q1", "T1", 10**6, 10**7, 0.20, 0.5, 0.5, "2025-01-01"], ["B", "Q2", "T2", 0, 0, 0, 1.0, 0.08, "2025-01-01"]], columns=["market_id", "question", "tags", "liquidity", "volume", "one_day_change", "yes_price", "no_price", "end_date"])

        picks = get_top_picks(df, 1000)
        self.assertTrue(len(picks) > 0)
        self.assertEqual(picks[0]["market_id"], "A")
