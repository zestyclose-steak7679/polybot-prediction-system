
import unittest
from unittest.mock import MagicMock, patch
import sys



# Mock numpy, pandas, and config before importing MetaModel
mock_np = MagicMock()

# sys.modules['numpy'] = mock_np
# sys.modules['pandas'] = MagicMock()
# sys.modules['config'] = MagicMock()







# Now import MetaModel
from models.meta_model import MetaModel

class TestMetaModelVectorization(unittest.TestCase):
    def setUp(self):
        import sys
        from unittest.mock import patch, MagicMock
        self.module_patcher = patch.dict(sys.modules, {
            'numpy': MagicMock(),
            'pandas': MagicMock(),
            'config': MagicMock()
        })
        self.module_patcher.start()

        self.mm = MetaModel()
        self.mm.is_trained = True
        self.mm.model = MagicMock()
        self.mm.strategy_names = ["strat1", "strat2", "strat3"]

    def tearDown(self):
        self.module_patcher.stop()

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


        # Check normalized weights via softmax (0.1, 0.2, 0.3)
        # exp(0.1)=1.105, exp(0.2)=1.221, exp(0.3)=1.349 -> sum=3.675
        # strat1 = 1.105 / 3.675 = 0.3006
        import numpy as np
        vals = np.array([0.1, 0.2, 0.3])
        exp_vals = np.exp(vals - np.max(vals))
        expected_softmax = exp_vals / np.sum(exp_vals)

        self.assertAlmostEqual(weights["strat1"], expected_softmax[0])
        self.assertAlmostEqual(weights["strat2"], expected_softmax[1])
        self.assertAlmostEqual(weights["strat3"], expected_softmax[2])


        # Check normalized weights (0.1, 0.2, 0.3 -> sum=0.6 -> 1/6, 2/6, 3/6)
        # weights = softmax([0.1, 0.2, 0.3])
        import numpy as np
        vals = np.array([0.1, 0.2, 0.3])
        exp_vals = np.exp(vals - np.max(vals))
        softmax_vals = exp_vals / np.sum(exp_vals)

        self.assertAlmostEqual(weights["strat1"], softmax_vals[0])
        self.assertAlmostEqual(weights["strat2"], softmax_vals[1])
        self.assertAlmostEqual(weights["strat3"], softmax_vals[2])

        total = 0.1 + 0.2 + 0.3
        self.assertTrue("strat1" in weights)
        self.assertTrue("strat2" in weights)
        self.assertTrue("strat3" in weights)



    def test_predict_weights_exception_fallback(self):
        strategy_names = ["strat1", "strat2"]
        feats = {}

        # Force an exception in predict
        self.mm.model.predict.side_effect = Exception("Predict failed")

        with self.assertRaises(Exception):
            self.mm.predict_weights(feats, strategy_names)

if __name__ == "__main__":
    unittest.main()
