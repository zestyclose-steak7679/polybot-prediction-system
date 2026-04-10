import unittest
import numpy as np
from data.features import momentum_features

class TestFeatures(unittest.TestCase):
    def test_momentum_features_insufficient_data(self):
        # Expected response when there are less than 3 price snapshots
        expected = {
            "mom_short": 0.0,
            "mom_medium": 0.0,
            "mom_long": 0.0,
            "mom_ratio": 0.0,
            "mom_acceleration": 0.0
        }

        # Test with 0 prices
        self.assertEqual(momentum_features(np.array([])), expected)

        # Test with 1 price
        self.assertEqual(momentum_features(np.array([0.5])), expected)

        # Test with 2 prices
        self.assertEqual(momentum_features(np.array([0.5, 0.6])), expected)

if __name__ == '__main__':
    unittest.main()
