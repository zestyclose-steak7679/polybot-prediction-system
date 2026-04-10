import unittest
from unittest.mock import patch
import numpy as np

from portfolio.risk_manager import apply_risk_constraints

class StubSignal:
    def __init__(self, market_id, strategy):
        self.market_id = market_id
        self.strategy = strategy

class TestRiskManager(unittest.TestCase):

    def test_apply_risk_constraints_empty(self):
        """Test with empty lists."""
        sizes = apply_risk_constraints([], [], 1000.0)
        self.assertEqual(sizes, [])

    def test_apply_risk_constraints_single_within_limits(self):
        """Test single signal within limits."""
        signal = StubSignal("m1", "strategy_a")
        sizes = apply_risk_constraints([signal], [25.0], 1000.0)
        # Bankroll 1000, MAX_BET_PCT = 0.03 -> max size 30.0
        self.assertEqual(sizes, [25.0])

    def test_apply_risk_constraints_max_bet_limit(self):
        """Test single signal exceeding max bet percentage."""
        signal = StubSignal("m1", "strategy_a")
        # 50.0 > 1000 * 0.03 (30.0)
        sizes = apply_risk_constraints([signal], [50.0], 1000.0)
        self.assertEqual(sizes, [30.0])

    def test_apply_risk_constraints_negative_size(self):
        """Test size floored at 0."""
        signal = StubSignal("m1", "strategy_a")
        sizes = apply_risk_constraints([signal], [-10.0], 1000.0)
        self.assertEqual(sizes, [0.0])

    def test_apply_risk_constraints_max_exposure(self):
        """Test portfolio maximum exposure limit."""
        # 15 signals, same strategy but different markets to hit structural fallback
        # With structural fallback for same strategy, corr is 0.35
        # avg_corr = 0.35
        # scale = max(1.0 - 0.35 * 0.4, 0.4) = 0.86
        # adjusted size = 30.0 * 0.86 = 25.8
        # total size = 25.8 * 15 = 387.0
        # max_total = 1000 * 0.30 = 300.0
        # exposure scale = 300.0 / 387.0 = 0.7751938
        # final size = 25.8 * 0.7751938 = 20.0
        signals = [StubSignal(f"m{i}", "strategy_a") for i in range(15)]
        sizes_in = [30.0] * 15

        sizes_out = apply_risk_constraints(signals, sizes_in, 1000.0)

        self.assertEqual(len(sizes_out), 15)
        # Check that total exposure doesn't exceed 300
        self.assertAlmostEqual(sum(sizes_out), 300.0, places=1)
        for s in sizes_out:
            self.assertEqual(s, 20.0)

    @patch('portfolio.risk_manager._empirical_correlation')
    def test_apply_risk_constraints_correlation_adjustment(self, mock_corr):
        """Test with highly correlated signals."""
        # We will mock the correlation matrix to force a specific adjustment
        # 2 signals, highly correlated
        mock_corr.return_value = np.array([
            [1.0, 0.9],
            [0.9, 1.0]
        ])
        signals = [StubSignal("m1", "strategy_a"), StubSignal("m2", "strategy_a")]
        sizes_in = [20.0, 20.0]

        # avg_corr = 0.9
        # scale = max(1.0 - 0.9 * 0.4, 0.4) = 1.0 - 0.36 = 0.64
        # expected size = 20.0 * 0.64 = 12.8

        sizes_out = apply_risk_constraints(signals, sizes_in, 1000.0)

        self.assertEqual(len(sizes_out), 2)
        self.assertEqual(sizes_out, [12.8, 12.8])

    @patch('portfolio.risk_manager._empirical_correlation')
    def test_apply_risk_constraints_rounding(self, mock_corr):
        """Test that outputs are correctly rounded to 2 decimal places."""
        mock_corr.return_value = np.array([[1.0]])
        signal = StubSignal("m1", "strategy_a")
        # 25.123 -> 25.12
        sizes = apply_risk_constraints([signal], [25.123], 1000.0)
        self.assertEqual(sizes, [25.12])

if __name__ == '__main__':
    unittest.main()
