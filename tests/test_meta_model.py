import unittest
from models.meta_model import MetaModel

class TestMetaModel(unittest.TestCase):
    def setUp(self):
        # We explicitly ensure model is untrained for these tests
        # so it doesn't accidentally load models/meta_model.pkl from disk
        self.meta_model = MetaModel()
        self.meta_model.is_trained = False
        self.meta_model.model = None

    def test_predict_weights_empty_strategies(self):
        """Test predict_weights with an empty strategy_names list."""
        result = self.meta_model.predict_weights({}, [])
        self.assertEqual(result, {})

    def test_predict_weights_multiple_strategies_untrained(self):
        """Test predict_weights with multiple strategies for an untrained model."""
        strategies = ["strategy1", "strategy2", "strategy3", "strategy4"]
        result = self.meta_model.predict_weights({}, strategies)

        # Should fall back to equal weights
        expected_weight = 1.0 / len(strategies)
        expected_result = {s: expected_weight for s in strategies}

        self.assertEqual(result, expected_result)

    def test_predict_weights_single_strategy_untrained(self):
        """Test predict_weights with a single strategy for an untrained model."""
        strategies = ["strategy1"]
        result = self.meta_model.predict_weights({}, strategies)

        # Should fall back to equal weights (1.0 for a single strategy)
        expected_weight = 1.0 / len(strategies)
        expected_result = {s: expected_weight for s in strategies}

        self.assertEqual(result, expected_result)

if __name__ == '__main__':
    unittest.main()
