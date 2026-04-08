import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd

from alpha.evaluator import evaluate_alpha_modules
from alpha.signals import AlphaSignal, build_alpha_signals, diagnose_alpha_signals
from alpha.tracker import resolve_alpha_signals
from data import database, price_history


def _market_row(**overrides):
    row = {
        "market_id": "m1",
        "question": "Test market?",
        "yes_price": 0.48,
        "no_price": 0.57,
        "liquidity": 5000.0,
        "volume": 8000.0,
        "one_day_change": 0.04,
        "end_date": (datetime.now(UTC) + timedelta(hours=12)).isoformat(),
    }
    row.update(overrides)
    return pd.Series(row)


def _history(prices=None, volumes=None):
    prices = prices or [0.40, 0.42, 0.45, 0.47, 0.50, 0.54]
    volumes = volumes or [1000, 1200, 1400, 1600, 2200, 3200]
    return pd.DataFrame({"yes_price": prices, "volume": volumes, "liquidity": [5000] * len(prices)})


class AlphaSignalTests(unittest.TestCase):
    def test_insufficient_history_skips_market(self):
        market = _market_row()
        signals = build_alpha_signals(
            pd.DataFrame([market]),
            {"m1": {"near_resolution": 1}},
            {"m1": "trending"},
            {"m1": _history(prices=[0.4, 0.41, 0.42], volumes=[1000, 1100, 1200])},
        )
        self.assertEqual(signals, [])

    def test_late_drift_signal_direction(self):
        feats = {
            "near_resolution": 1,
            "danger_zone": 0,
            "mom_short": 0.03,
            "mom_medium": 0.06,
            "mom_acceleration": 0.02,
            "vol_spike_ratio": 1.8,
        }
        signals = build_alpha_signals(
            pd.DataFrame([_market_row(yes_price=0.55, no_price=0.45)]),
            {"m1": feats},
            {"m1": "trending"},
            {"m1": _history()},
        )
        names = {(signal.alpha_name, signal.direction) for signal in signals}
        self.assertIn(("late_drift", "YES"), names)

    def test_reversion_gap_signal_direction(self):
        feats = {
            "z_score": 2.3,
            "distance_from_mean": 0.06,
            "vol_spike_ratio": 2.0,
            "mom_acceleration": -0.01,
        }
        signals = build_alpha_signals(
            pd.DataFrame([_market_row(yes_price=0.68, no_price=0.32)]),
            {"m1": feats},
            {"m1": "mean_reverting"},
            {"m1": _history(prices=[0.44, 0.47, 0.51, 0.58, 0.63, 0.68])},
        )
        names = {(signal.alpha_name, signal.direction) for signal in signals}
        self.assertIn(("reversion_gap", "NO"), names)

    def test_spread_pressure_requires_supporting_context(self):
        feats = {"price": 0.39}
        signals = build_alpha_signals(
            pd.DataFrame([_market_row(yes_price=0.39, no_price=0.67, liquidity=3000, volume=1800)]),
            {"m1": feats},
            {"m1": "neutral"},
            {"m1": _history(prices=[0.51, 0.49, 0.46, 0.43, 0.41, 0.39], volumes=[3200, 3000, 2800, 2600, 2400, 1800])},
        )
        self.assertTrue(any(signal.alpha_name == "spread_pressure" for signal in signals))

    def test_diagnostics_capture_failure_reasons(self):
        feats = {
            "near_resolution": 0,
            "danger_zone": 0,
            "mom_short": 0.02,
            "mom_medium": 0.03,
            "mom_acceleration": 0.01,
            "vol_spike_ratio": 1.5,
            "z_score": 0.3,
            "distance_from_mean": 0.01,
        }
        diagnostics = diagnose_alpha_signals(
            pd.DataFrame([_market_row(yes_price=0.51, no_price=0.45, liquidity=25000, volume=1200)]),
            {"m1": feats},
            {"m1": _history()},
        )
        self.assertIn("not_near_resolution", diagnostics["late_drift"]["failure_reasons"])
        self.assertIn("zscore_below_threshold", diagnostics["reversion_gap"]["failure_reasons"])

    def test_evaluator_promotion_thresholds(self):
        rows = pd.DataFrame(
            {
                "alpha_name": ["late_drift"] * 110 + ["spread_pressure"] * 30,
                "resolved_clv": [0.01] * 70 + [-0.002] * 40 + [0.02] * 10 + [-0.03] * 20,
            }
        )
        stats = evaluate_alpha_modules(rows)
        self.assertTrue(stats["late_drift"]["promoted"])
        self.assertFalse(stats["spread_pressure"]["promoted"])


class AlphaPersistenceTests(unittest.TestCase):
    def test_shadow_alpha_logging_and_resolution(self):
        db_path = os.path.join(os.getcwd(), "alpha_test_temp.db")
        recovered_path = os.path.join(os.getcwd(), "alpha_test_temp.recovered.db")
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except PermissionError:
                pass
        if os.path.exists(recovered_path):
            try:
                os.remove(recovered_path)
            except PermissionError:
                pass
        try:
            with patch.object(database, "DB_PATH", db_path), patch.object(price_history, "DB_PATH", db_path):
                database.init_db()
                signal = AlphaSignal(
                    market_id="m1",
                    question="Alpha test?",
                    alpha_name="late_drift",
                    score=0.8,
                    predicted_clv=0.015,
                    direction="YES",
                    reason="test",
                    shadow_only=True,
                    feature_payload={"mom_short": 0.03},
                    regime="trending",
                    entry_price=0.42,
                    passed_live_threshold=True,
                )
                database.log_alpha_signals([signal], cycle_ts="2026-01-01T00:00:00")
                self.assertEqual(len(database.get_recent_alpha_signals()), 1)
                self.assertTrue(database.get_open_bets().empty)

                current_markets = pd.DataFrame(
                    [
                        {
                            "market_id": "m1",
                            "yes_price": 0.48,
                            "no_price": 0.52,
                            "end_date": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                        }
                    ]
                )
                resolved = resolve_alpha_signals(current_markets)
                self.assertEqual(resolved, 1)

                outcomes = database.get_alpha_outcomes()
                self.assertEqual(len(outcomes), 1)
                self.assertAlmostEqual(float(outcomes.iloc[0]["closing_price"]), 0.48, places=5)
                self.assertGreater(float(outcomes.iloc[0]["resolved_clv"]), 0.0)
        finally:
            for path in (db_path, recovered_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except PermissionError:
                        pass


if __name__ == "__main__":
    unittest.main()
