import unittest
from unittest.mock import patch, MagicMock
from models.edge_model import EdgeModel, heuristic_edge
import numpy as np

class TestEdgeModel(unittest.TestCase):
    @patch('models.edge_model.Path.exists', return_value=False)
    def test_predict_prob_untrained_fallback(self, mock_exists):
        """Test that predict_prob falls back to heuristic_edge when not trained."""
        model = EdgeModel()
        self.assertFalse(model.is_trained)
        self.assertIsNone(model.model)

        # We'll construct features that give a deterministic non-zero heuristic edge
        # heuristic_edge does this:
        # if abs(z_score) > 1.5: delta -= sign(z) * min(abs(z) * 0.015, 0.04)
        # 2.0 > 1.5 -> sign(2) * min(2*0.015, 0.04) = 1 * min(0.03, 0.04) = 0.03
        # so delta = -0.03
        from config import MIN_PRICE, MAX_PRICE
        # price = 0.5 -> prob = np.clip(0.5 - 0.03, MIN_PRICE, MAX_PRICE) = 0.47
        feats = {"price": 0.5, "z_score": 2.0}

        prob = model.predict_prob(feats)

        # Verify the probability is exactly what heuristic_edge returns
        expected_delta = heuristic_edge(feats, 0.5)
        expected_prob = float(np.clip(float(0.5 + expected_delta), float(MIN_PRICE), float(MAX_PRICE)))

        self.assertAlmostEqual(prob, expected_prob, places=4)
        self.assertAlmostEqual(prob, 0.47, places=4)

    @patch('models.edge_model.Path.exists', return_value=False)
    def test_predict_prob_exception_fallback(self, mock_exists):
        """Test that predict_prob falls back to heuristic_edge when ML model raises exception."""
        model = EdgeModel()
        # Fake that it's trained and has a mock model
        model.is_trained = True
        model.model = MagicMock()
        # make it raise an exception when predicting
        model.model.predict_proba.side_effect = ValueError("Invalid features")

        # Give it a deterministic feature set
        feats = {"price": 0.6, "z_score": -2.0} # delta should be +0.03

        # This shouldn't raise, it should fall back to heuristic
        prob = model.predict_prob(feats)

        # Calculate expected fallback output
        from config import MIN_PRICE, MAX_PRICE
        expected_delta = heuristic_edge(feats, 0.6)
        expected_prob = float(np.clip(float(0.6 + expected_delta), float(MIN_PRICE), float(MAX_PRICE)))

        self.assertAlmostEqual(prob, expected_prob, places=4)
        self.assertAlmostEqual(prob, 0.63, places=4)

if __name__ == '__main__':
    unittest.main()
