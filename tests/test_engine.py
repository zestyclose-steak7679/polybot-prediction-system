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

if __name__ == '__main__':
    unittest.main()
