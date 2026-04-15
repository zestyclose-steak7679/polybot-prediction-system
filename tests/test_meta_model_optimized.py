
import unittest
from unittest.mock import MagicMock, patch
import sys

# Now import MetaModel
from models.meta_model import MetaModel

class TestMetaModelVectorization(unittest.TestCase):
    def setUp(self):
        self.mm = MetaModel()
        self.mm.is_trained = True
        self.mm.model = MagicMock()
        self.mm.strategy_names = ["strat1", "strat2", "strat3"]

    def test_predict_weights_vectorization(self):
        strategy_names = ["strat1", "strat2", "strat3"]
        feats = {
            "edge_est": 0.2,
            "confidence": 0.8,
            "price": 0.5,
            "liquidity": 5000,
            "volume": 2000,
            "one_day_change": 0.05
        }

        # Mock model.predict to return some values
        self.mm.is_trained = True
        self.mm.model.predict.return_value = [0.1, 0.2, 0.3]

        weights = self.mm.predict_weights(feats, strategy_names)

        # Check that predict was called once (vectorized)
        self.mm.model.predict.assert_called_once()

        # Check output structure
        self.assertIsInstance(weights, dict)
        self.assertEqual(len(weights), 3)
        self.assertIn("strat1", weights)
        self.assertIn("strat2", weights)
        self.assertIn("strat3", weights)

        # Check properties
        self.assertTrue(abs(sum(weights.values()) - 1.0) < 1e-6)
        for w in weights.values():
            self.assertTrue(0 <= w <= 1.0)

        # Check explicit output mapping matches real numpy logic
        import numpy as np
        vals = np.array([0.1, 0.2, 0.3])
        exp_vals = np.exp(vals - np.max(vals))
        expected_softmax = exp_vals / np.sum(exp_vals)

        self.assertAlmostEqual(weights["strat1"], expected_softmax[0])
        self.assertAlmostEqual(weights["strat2"], expected_softmax[1])
        self.assertAlmostEqual(weights["strat3"], expected_softmax[2])

    def test_predict_weights_exception_fallback(self):
        strategy_names = ["strat1", "strat2"]
        feats = {}

        # Force an exception in predict
        self.mm.model.predict.side_effect = Exception("Predict failed")

        with self.assertRaises(Exception):
            self.mm.predict_weights(feats, strategy_names)

if __name__ == "__main__":
    unittest.main()
