import unittest
from unittest.mock import patch
from scoring.engine import kelly_bet

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
        # Note: the code returns KELLY_FRACTION as 0.25 in this path
        self.assertEqual(res['kelly_fraction_used'], 0.25)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.10)
    def test_kelly_bet_positive_edge_under_max(self):
        """Test when calculated bet is less than the max cap."""
        # prob = 0.6, decimal_odds = 2.0 (b = 1)
        # kelly_raw = (0.6 * 2 - 1) / 1 = 0.2
        # kelly_adj = 0.2 * 0.25 = 0.05
        # bankroll = 1000 -> bet_size = 50.0
        # max_bet = 1000 * 0.10 = 100.0
        res = kelly_bet(bankroll=1000, prob=0.6, decimal_odds=2.0)
        self.assertEqual(res['bet_size'], 50.0)
        self.assertEqual(res['kelly_raw'], 0.2)
        self.assertEqual(res['kelly_fraction_used'], 0.25)

    @patch('scoring.engine.KELLY_FRACTION', 0.25)
    @patch('scoring.engine.MAX_BET_PCT', 0.02)
    def test_kelly_bet_positive_edge_over_max(self):
        """Test when calculated bet exceeds the max cap."""
        # prob = 0.6, decimal_odds = 2.0 (b = 1)
        # kelly_raw = (0.6 * 2 - 1) / 1 = 0.2
        # kelly_adj = 0.2 * 0.25 = 0.05
        # bankroll = 1000 -> bet_size = 50.0
        # max_bet = 1000 * 0.02 = 20.0 (CAP SHOULD APPLY)
        res = kelly_bet(bankroll=1000, prob=0.6, decimal_odds=2.0)
        self.assertEqual(res['bet_size'], 20.0)
        self.assertEqual(res['kelly_raw'], 0.2)
        self.assertEqual(res['kelly_fraction_used'], 0.25)

import pandas as pd
from scoring.engine import (
    score_market, _liquidity_score, _volume_momentum,
    _price_tension, _spread_efficiency,
    score_all, estimate_edge, kelly_bet, get_top_picks
)

class TestEngine(unittest.TestCase):
    # --- Helper Function Tests ---
    def test_liquidity_score(self):
        self.assertEqual(_liquidity_score(-100), 0.0)
        self.assertEqual(_liquidity_score(0), 0.0)
        self.assertAlmostEqual(_liquidity_score(1000), 0.5, places=4)
        self.assertAlmostEqual(_liquidity_score(10**6), 1.0, places=4)
        self.assertAlmostEqual(_liquidity_score(10**7), 1.0, places=4)

    def test_volume_momentum(self):
        self.assertEqual(_volume_momentum(100, 0.0), 0.0)
        self.assertEqual(_volume_momentum(100, 0.10), 0.5)
        self.assertEqual(_volume_momentum(100, -0.10), 0.5)
        self.assertEqual(_volume_momentum(100, 0.20), 1.0)
        self.assertEqual(_volume_momentum(100, -0.30), 1.0)

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
        row = {
            "liquidity": 10**6,
            "volume": 10**7,
            "one_day_change": 0.20,
            "yes_price": 0.5,
            "no_price": 0.5
        }
        score = score_market(row)
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_score_market_min_score(self):
        row = {
            "liquidity": 0,
            "volume": 0,
            "one_day_change": 0.0,
            "yes_price": 1.0,
            "no_price": 0.08
        }
        score = score_market(row)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_score_market_intermediate(self):
        row = {
            "liquidity": 1000,   # 0.5
            "volume": 100000,    # 5/7 = 0.7142857
            "one_day_change": -0.10, # 0.5
            "yes_price": 0.75,   # 0.5
            "no_price": 0.21     # spread = 0.04 -> eff = 0.5
        }
        # total expected = 0.5*0.3 + 0.5*0.25 + 0.5*0.2 + 0.5*0.15 + (5/7)*0.10 = 0.15 + 0.125 + 0.1 + 0.075 + 0.07142857 = 0.52142857
        score = score_market(row)
        self.assertAlmostEqual(score, 0.5214, places=4)

    def test_score_market_negative_liquidity(self):
        row = {
            "liquidity": -100,
            "volume": 10**7,
            "one_day_change": 0.20,
            "yes_price": 0.5,
            "no_price": 0.5
        }
        score = score_market(row)
        self.assertAlmostEqual(score, 0.70, places=4)

    # --- score_all Tests ---
    def test_score_all(self):
        df = pd.DataFrame({
            "market_id": ["A", "B"],
            "liquidity": [0, 10**6],
            "volume": [0, 10**7],
            "one_day_change": [0, 0.20],
            "yes_price": [1.0, 0.5],
            "no_price": [0.08, 0.5]
        })
        scored_df = score_all(df)
        self.assertEqual(len(scored_df), 2)
        # Should be sorted descending by score
        self.assertEqual(scored_df.iloc[0]["market_id"], "B")
        self.assertAlmostEqual(scored_df.iloc[0]["score"], 1.0, places=4)
        self.assertEqual(scored_df.iloc[1]["market_id"], "A")
        self.assertAlmostEqual(scored_df.iloc[1]["score"], 0.0, places=4)

    # --- estimate_edge Tests ---
    def test_estimate_edge(self):
        # yes_price = 0.5, score = 1.0 -> adjustment = 0.06
        # true_prob_yes = 0.56, true_prob_no = 0.56
        # edge_yes = 0.06, edge_no = 0.56 - 0.5 = 0.06
        # Tie goes to YES based on >= operator
        side, prob, edge = estimate_edge(0.5, 1.0)
        self.assertEqual(side, "YES")
        self.assertAlmostEqual(prob, 0.56, places=4)
        self.assertAlmostEqual(edge, 0.06, places=4)

        # yes_price = 0.3, score = 0.5 -> adj = 0.03
        # true_prob_yes = 0.33, true_prob_no = 0.73
        # edge_yes = 0.03, edge_no = 0.73 - 0.7 = 0.03
        side, prob, edge = estimate_edge(0.3, 0.5)
        # Because edge_yes = 0.03, edge_no = 0.03 (actually exactly equal due to floating math, or NO wins depending on precise comparison)
        # In engine: edge_yes = 0.33 - 0.3 = 0.03. edge_no = 0.73 - 0.7 = 0.03
        # if edge_yes >= edge_no -> YES. Wait, float precision might cause edge_yes < edge_no
        # Wait, if yes_price=0.3, 1-yes=0.7. true_prob_yes=0.33, true_prob_no=0.73
        # edge_yes = 0.33 - 0.3 = 0.03. edge_no = 0.73 - 0.7 = 0.03
        # Due to float precision: 0.33 - 0.3 = 0.02999999999999997. 0.73 - 0.7 = 0.030000000000000027
        # So edge_no > edge_yes. Side is NO!
        self.assertEqual(side, "NO")
        self.assertAlmostEqual(prob, 0.73, places=4)
        self.assertAlmostEqual(edge, 0.03, places=4)

    # --- kelly_bet Tests ---
    def test_kelly_bet_positive_edge(self):
        # decimal odds = 2.0 (price 0.5)
        # prob = 0.60
        # b = 1.0
        # kelly_raw = (0.6 * 2.0 - 1) / 1.0 = 0.2
        # max bet = 1000 * 0.03 = 30
        # bet_size = 1000 * 0.2 * 0.25 (KELLY_FRACTION) = 50 -> capped at 30
        res = kelly_bet(1000, 0.6, 2.0)
        self.assertEqual(res["bet_size"], 30.0)
        self.assertEqual(res["kelly_raw"], 0.2)

    def test_kelly_bet_negative_edge(self):
        # decimal odds = 2.0 (price 0.5)
        # prob = 0.40 -> expected value negative
        res = kelly_bet(1000, 0.4, 2.0)
        self.assertEqual(res["bet_size"], 0.0)
        self.assertEqual(res["kelly_raw"], 0.0)

    def test_kelly_bet_small_edge(self):
        # decimal odds = 2.0 (price 0.5)
        # prob = 0.52
        # b = 1.0
        # kelly_raw = (0.52 * 2.0 - 1) = 0.04
        # bet_size = 1000 * 0.04 * 0.25 = 10.0
        res = kelly_bet(1000, 0.52, 2.0)
        self.assertEqual(res["bet_size"], 10.0)
        self.assertEqual(res["kelly_raw"], 0.04)

    # --- get_top_picks Tests ---
    def test_get_top_picks_empty(self):
        self.assertEqual(get_top_picks(pd.DataFrame(), 1000), [])

    def test_get_top_picks(self):
        df = pd.DataFrame({
            "market_id": ["A", "B"],
            "question": ["Q1", "Q2"],
            "tags": ["T1", "T2"],
            "liquidity": [10**6, 0],
            "volume": [10**7, 0],
            "one_day_change": [0.20, 0],
            "yes_price": [0.5, 1.0],
            "no_price": [0.5, 0.08],
            "end_date": ["2025-01-01", "2025-01-01"]
        })
        picks = get_top_picks(df, 1000)
        # Market A: score 1.0 -> edge 0.06 -> threshold met (0.04) -> pick
        # Market B: score 0.0 -> edge 0.0 -> threshold not met (0.04) -> no pick
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["market_id"], "A")
        self.assertAlmostEqual(picks[0]["score"], 1.0, places=4)
        self.assertEqual(picks[0]["side"], "YES")
        # odds = 1/0.5 = 2.0
        self.assertAlmostEqual(picks[0]["decimal_odds"], 2.0)
        self.assertAlmostEqual(picks[0]["edge"], 0.06, places=4)

if __name__ == "__main__":
    unittest.main()
