import unittest
from unittest.mock import patch, MagicMock
import sys

class TestCLVModelFallback(unittest.TestCase):
    def setUp(self):
        # We use patch.dict to safely mock sys.modules for isolation
        self.module_patcher = patch.dict(sys.modules, {
            'numpy': MagicMock(),
            'pandas': MagicMock(),
            'sklearn': MagicMock(),
            'sklearn.ensemble': MagicMock(),
            'config': MagicMock(),
            'data.features': MagicMock(),
        })
        self.module_patcher.start()

        # Patch Path.exists to return False to avoid loading any real model file
        self.path_patcher = patch("pathlib.Path.exists", return_value=False)
        self.path_patcher.start()

        # Import the model within the test to ensure it uses the mocked dependencies
        from models.clv_model import CLVModel
        self.CLVModel = CLVModel

    def tearDown(self):
        self.path_patcher.stop()
        self.module_patcher.stop()

    def test_predict_returns_zero_when_not_trained(self):
        """Verify predict returns 0.0 if is_trained is False."""
        model = self.CLVModel()
        model.is_trained = False
        model.model = None

        result = model.predict({"price": 0.6})
        self.assertEqual(result, 0.0)

    def test_predict_returns_zero_when_model_is_none(self):
        """Verify predict returns 0.0 if model is None even if is_trained is True."""
        model = self.CLVModel()
        model.is_trained = True
        model.model = None

        result = model.predict({"price": 0.6})
        self.assertEqual(result, 0.0)

    def test_predict_returns_zero_on_exception(self):
        """Verify predict returns 0.0 if an exception occurs during prediction."""
        model = self.CLVModel()
        model.is_trained = True
        model.model = MagicMock()
        # Mocking the predict method of the internal model to raise an exception
        model.model.predict.side_effect = Exception("Model error")

        result = model.predict({"price": 0.6})
        self.assertEqual(result, 0.0)

if __name__ == "__main__":
    unittest.main()
