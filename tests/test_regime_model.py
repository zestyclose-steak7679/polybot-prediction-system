import unittest
from models.regime_model import RegimeModel

class TestRegimeModel(unittest.TestCase):
    def setUp(self):
        self.model = RegimeModel()

    def test_rule_predict_illiquid_spike(self):
        # spike > 2.5 -> illiquid_spike
        features = {"vol_spike": 3.0}
        self.assertEqual(self.model._rule_predict(features), "illiquid_spike")

    def test_rule_predict_volatile(self):
        # vol > 0.04 and abs(trend) > 0.015 -> volatile
        features = {"vol_spike": 1.0, "volatility": 0.05, "trend_strength": 0.02}
        self.assertEqual(self.model._rule_predict(features), "volatile")

        features_negative_trend = {"vol_spike": 1.0, "volatility": 0.05, "trend_strength": -0.02}
        self.assertEqual(self.model._rule_predict(features_negative_trend), "volatile")

    def test_rule_predict_trending(self):
        # autocorr > 0.25 -> trending
        features = {"vol_spike": 1.0, "volatility": 0.01, "trend_strength": 0.01, "autocorr": 0.3}
        self.assertEqual(self.model._rule_predict(features), "trending")

    def test_rule_predict_mean_reverting(self):
        # autocorr < -0.20 -> mean_reverting
        features = {"vol_spike": 1.0, "volatility": 0.01, "trend_strength": 0.01, "autocorr": -0.3}
        self.assertEqual(self.model._rule_predict(features), "mean_reverting")

    def test_rule_predict_neutral(self):
        # none of the above -> neutral
        features = {"vol_spike": 1.0, "volatility": 0.01, "trend_strength": 0.01, "autocorr": 0.1}
        self.assertEqual(self.model._rule_predict(features), "neutral")

    def test_rule_predict_empty_features(self):
        # defaults: vol=0, trend=0, autocorr=0, spike=1 -> neutral
        features = {}
        self.assertEqual(self.model._rule_predict(features), "neutral")

if __name__ == '__main__':
    unittest.main()
