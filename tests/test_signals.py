import unittest
import pandas as pd
from alpha.signals import _safe_price_range

class TestSafePriceRange(unittest.TestCase):
    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = _safe_price_range(df)
        self.assertEqual(result, 0.0)

    def test_none_input(self):
        result = _safe_price_range(None)
        self.assertEqual(result, 0.0)

    def test_safe_price_range_valid(self):
        df = pd.DataFrame({'yes_price': [0.1, 0.5, 0.9]})
        result = _safe_price_range(df)
        self.assertAlmostEqual(result, 0.8, places=5)

    def test_safe_price_range_negative(self):
        # Even though prices aren't negative, we test if it returns max(..., 0.0)
        # Actually max - min is positive, but let's test a case where it works.
        df = pd.DataFrame({'yes_price': [0.5, 0.5]})
        result = _safe_price_range(df)
        self.assertEqual(result, 0.0)

if __name__ == '__main__':
    unittest.main()
