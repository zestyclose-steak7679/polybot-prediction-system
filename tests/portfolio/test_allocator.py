import unittest
from unittest.mock import Mock
from portfolio.allocator import allocate, portfolio_summary

class TestAllocator(unittest.TestCase):
    def test_allocate_empty_signals(self):
        """Test that passing an empty list of signals to allocate safely returns []"""
        result = allocate([], 1000.0)
        self.assertEqual(result, [])

    def test_portfolio_summary_empty(self):
        """Test portfolio summary returns correct string when no allocations exist"""
        self.assertEqual(
            portfolio_summary([], 1000.0),
            "No allocations this cycle."
        )

    def test_portfolio_summary_with_allocations(self):
        """Test portfolio summary formatting with multiple allocations"""
        sig1 = Mock()
        sig1.strategy = "momentum"
        sig1.side = "YES"
        sig1.edge = 0.052

        sig2 = Mock()
        sig2.strategy = "reversal"
        sig2.side = "NO"
        sig2.edge = 0.081

        allocations = [
            {"signal": sig1, "bet_size": 25.0},
            {"signal": sig2, "bet_size": 15.0}
        ]

        result = portfolio_summary(allocations, 1000.0)

        expected_lines = [
            "📊 Portfolio: 2 bets | $40.00 (4.0%)",
            "  momentum      YES 5.2% edge → $25.00",
            "  reversal      NO 8.1% edge → $15.00"
        ]
        self.assertEqual(result, "\n".join(expected_lines))

if __name__ == '__main__':
    unittest.main()
