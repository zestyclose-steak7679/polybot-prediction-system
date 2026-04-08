import os
import unittest
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd

import main
from scoring.strategies import Signal
from data import database, price_history
from learning import tracker
from portfolio.strategy_weights import get_strategy_weight_gate
from risk import controls as risk_controls


class FeedbackLoopTests(unittest.TestCase):
    def test_open_position_stats_reports_hold_times_and_stale_count(self):
        db_path = os.path.join(os.getcwd(), "feedback_stats_temp.db")
        for path in (db_path, f"{db_path}-journal"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass

        try:
            with patch.object(database, "DB_PATH", db_path), patch.object(price_history, "DB_PATH", db_path):
                database.init_db()
                first_id = database.record_paper_bet(
                    market_id="m1",
                    question="First open?",
                    strategy_tag="momentum",
                    side="YES",
                    entry_price=0.40,
                    bet_size=20.0,
                    bankroll=1000.0,
                    kelly_raw=0.1,
                    edge_est=0.05,
                    confidence=0.6,
                    reason="test",
                )
                second_id = database.record_paper_bet(
                    market_id="m2",
                    question="Second open?",
                    strategy_tag="reversal",
                    side="NO",
                    entry_price=0.60,
                    bet_size=20.0,
                    bankroll=980.0,
                    kelly_raw=0.1,
                    edge_est=0.05,
                    confidence=0.6,
                    reason="test",
                )

                recent_ts = (datetime.now(UTC) - timedelta(hours=2)).replace(tzinfo=None).isoformat()
                stale_ts = (datetime.now(UTC) - timedelta(hours=8)).replace(tzinfo=None).isoformat()
                with database._conn() as con:
                    con.execute("UPDATE paper_bets SET placed_at=? WHERE id=?", (recent_ts, first_id))
                    con.execute("UPDATE paper_bets SET placed_at=? WHERE id=?", (stale_ts, second_id))
                    con.commit()

                stats = database.get_open_position_stats()
                self.assertEqual(stats["n_open"], 2)
                self.assertGreaterEqual(stats["avg_hold_hours"], 4.0)
                self.assertGreaterEqual(stats["oldest_hold_hours"], 8.0)
                self.assertEqual(stats["stale_count"], 1)
        finally:
            for path in (db_path, f"{db_path}-journal"):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except PermissionError:
                        pass

    def test_strategy_weight_gate_requires_closed_and_clv_samples(self):
        low_closed_gate = get_strategy_weight_gate(
            pd.DataFrame([{"strategy_tag": "momentum", "clv": 0.01}] * 5),
            ["momentum"],
        )
        self.assertFalse(low_closed_gate["active"])
        self.assertIn("need 20 closed bets", low_closed_gate["reason"])

        rows = (
            [{"strategy_tag": "momentum", "clv": 0.01}] * 10
            + [{"strategy_tag": "reversal", "clv": None}] * 10
            + [{"strategy_tag": "volume_spike", "clv": None}] * 10
        )
        gate = get_strategy_weight_gate(pd.DataFrame(rows), ["momentum", "reversal", "volume_spike"])
        self.assertFalse(gate["active"])
        self.assertIn("insufficient CLV samples", gate["reason"])

    def test_pnl_summary_counts_timeout_results(self):
        db_path = os.path.join(os.getcwd(), "feedback_summary_temp.db")
        for path in (db_path, f"{db_path}-journal"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass

        try:
            with (
                patch.object(database, "DB_PATH", db_path),
                patch.object(price_history, "DB_PATH", db_path),
                patch.object(tracker, "DB_PATH", db_path),
            ):
                database.init_db()
                bet_id = database.record_paper_bet(
                    market_id="m-summary",
                    question="Summary timeout?",
                    strategy_tag="momentum",
                    side="YES",
                    entry_price=0.40,
                    bet_size=25.0,
                    bankroll=1000.0,
                    kelly_raw=0.1,
                    edge_est=0.05,
                    confidence=0.7,
                    reason="test",
                )
                database.close_bet(
                    bet_id,
                    exit_price=0.50,
                    closing_price=0.50,
                    result="timeout_win",
                    pnl=6.25,
                    clv=0.5,
                )
                summary = database.get_pnl_summary()
                self.assertEqual(summary["total_bets"], 1)
                self.assertEqual(summary["wins"], 1)
                self.assertEqual(summary["losses"], 0)
                self.assertEqual(summary["clv_resolved_bets"], 1)
        finally:
            for path in (db_path, f"{db_path}-journal"):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except PermissionError:
                        pass

    def test_run_cycle_records_trade_when_below_cap(self):
        db_path = os.path.join(os.getcwd(), "feedback_cycle_temp.db")
        for path in (db_path, f"{db_path}-journal"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass

        market_df = pd.DataFrame(
            [
                {
                    "market_id": "m-cycle",
                    "question": "Cycle trade?",
                    "yes_price": 0.42,
                    "no_price": 0.58,
                    "liquidity": 5000.0,
                    "volume": 9000.0,
                    "one_day_change": 0.06,
                    "end_date": (datetime.now(UTC) + timedelta(hours=12)).isoformat(),
                    "tags": "sports",
                }
            ]
        )
        history = pd.DataFrame(
            {
                "yes_price": [0.35, 0.37, 0.39, 0.40, 0.42],
                "volume": [1000, 1200, 1400, 1800, 2200],
                "liquidity": [5000] * 5,
            }
        )
        signal = Signal(
            strategy="momentum",
            market_id="m-cycle",
            question="Cycle trade?",
            side="YES",
            price=0.42,
            confidence=0.50,
            edge=0.08,
            reason="test signal",
            tags="sports",
            liquidity=5000.0,
            volume=9000.0,
            one_day_change=0.06,
            end_date=(datetime.now(UTC) + timedelta(hours=12)).isoformat(),
        )

        try:
            with (
                patch.object(database, "DB_PATH", db_path),
                patch.object(price_history, "DB_PATH", db_path),
                patch.object(tracker, "DB_PATH", db_path),
            ):
                database.init_db()
                with ExitStack() as stack:
                    stack.enter_context(patch.object(main, "settle_and_compute_clv", return_value=(1000.0, {
                        "closed_count": 0,
                        "timeout_closed_count": 0,
                        "returned_capital": 0.0,
                        "avg_clv_closed": None,
                        "clv_resolved_count": 0,
                    })))
                    stack.enter_context(patch.object(main, "run_all_checks", return_value=(True, ["ok"])))
                    stack.enter_context(patch.object(main, "run_if_due"))
                    stack.enter_context(patch.object(main, "compute_drift_multiplier", return_value=(1.0, {})))
                    stack.enter_context(patch.object(main, "fetch_markets", return_value=market_df))
                    stack.enter_context(patch.object(main, "resolve_alpha_signals", return_value=0))
                    stack.enter_context(patch.object(main, "apply_filters", return_value=market_df))
                    stack.enter_context(patch.object(main, "log_prices"))
                    stack.enter_context(patch.object(main, "purge_old_history"))
                    stack.enter_context(patch.object(main, "get_history", return_value=history))
                    stack.enter_context(patch.object(main, "build_features", return_value={"mom_short": 0.03, "price": 0.42}))
                    stack.enter_context(patch.object(main, "compute_regime_features", return_value={
                        "volatility": 0.02,
                        "trend_strength": 0.01,
                        "autocorr": 0.1,
                        "vol_spike": 1.2,
                        "price_range": 0.07,
                    }))
                    stack.enter_context(patch.object(main.regime_model, "predict", return_value="neutral"))
                    stack.enter_context(patch.object(main.regime_model, "partial_fit"))
                    stack.enter_context(patch.object(main, "collect_alpha_diagnostics", return_value={}))
                    stack.enter_context(patch.object(main, "log_alpha_diagnostics"))
                    stack.enter_context(patch.object(main, "build_alpha_signals", return_value=[]))
                    stack.enter_context(patch.object(main, "log_alpha_signals", return_value=0))
                    stack.enter_context(patch.object(main, "aggregate_alpha_signals", return_value=[]))
                    stack.enter_context(patch.object(main, "evaluate_alpha_modules", return_value={}))
                    stack.enter_context(patch.object(main, "get_alpha_outcomes", return_value=pd.DataFrame()))
                    stack.enter_context(patch.object(main, "get_killed_strategies", return_value=[]))
                    stack.enter_context(patch.object(main, "get_active_strategies", return_value=["momentum"]))
                    stack.enter_context(patch.object(main.router, "select", return_value=["momentum"]))
                    stack.enter_context(patch.object(main, "run_strategies", return_value=[signal]))
                    stack.enter_context(patch.object(main, "allocate", return_value=[{
                        "signal": signal,
                        "bet_size": 20.0,
                        "kelly_raw": 0.10,
                        "decimal_odds": 2.38,
                    }]))
                    stack.enter_context(patch.object(main, "apply_risk_constraints", return_value=[20.0]))
                    stack.enter_context(patch.object(main, "was_recently_alerted", return_value=False))
                    stack.enter_context(patch.object(main, "log_market"))
                    stack.enter_context(patch.object(main, "record_alert"))
                    stack.enter_context(patch.object(main, "save_feature_snapshot"))
                    stack.enter_context(patch.object(main.edge_model, "predict_prob", return_value=0.55))
                    stack.enter_context(patch.object(main.clv_model, "predict", return_value=0.04))
                    stack.enter_context(patch.object(main.meta_model, "predict_weights", return_value={"momentum": 1.0}))
                    stack.enter_context(patch.object(main, "send_pick_alert"))
                    stack.enter_context(patch.object(main, "send_summary"))
                    stack.enter_context(patch.object(main, "save_bankroll"))
                    starting_bankroll = 1000.0
                    ending_bankroll = main.run_cycle(starting_bankroll, startup=False)

                self.assertAlmostEqual(ending_bankroll, 980.0, places=2)
                self.assertEqual(database.get_open_position_stats()["n_open"], 1)
                open_bets = database.get_open_bets()
                self.assertEqual(len(open_bets), 1)
                self.assertEqual(open_bets.iloc[0]["market_id"], "m-cycle")
        finally:
            for path in (db_path, f"{db_path}-journal"):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except PermissionError:
                        pass

    def test_run_cycle_frees_stale_slot_before_risk_halt(self):
        db_path = os.path.join(os.getcwd(), "feedback_stale_cycle_temp.db")
        for path in (db_path, f"{db_path}-journal"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass

        market_df = pd.DataFrame(
            [
                {
                    "market_id": "m-new",
                    "question": "Fresh market?",
                    "yes_price": 0.45,
                    "no_price": 0.55,
                    "liquidity": 6000.0,
                    "volume": 7000.0,
                    "one_day_change": 0.05,
                    "end_date": (datetime.now(UTC) + timedelta(hours=10)).isoformat(),
                    "tags": "sports",
                }
            ]
        )
        history = pd.DataFrame(
            {
                "yes_price": [0.40, 0.41, 0.42, 0.43, 0.45],
                "volume": [1200, 1400, 1600, 1800, 2000],
                "liquidity": [6000] * 5,
            }
        )
        settlement_markets = pd.DataFrame(
            [
                {
                    "market_id": "m-stale-0",
                    "yes_price": 0.52,
                    "no_price": 0.48,
                    "end_date": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                }
            ]
        )

        try:
            with (
                patch.object(database, "DB_PATH", db_path),
                patch.object(price_history, "DB_PATH", db_path),
                patch.object(tracker, "DB_PATH", db_path),
            ):
                database.init_db()
                for i in range(8):
                    bet_id = database.record_paper_bet(
                        market_id=f"m-stale-{i}",
                        question=f"Open {i}?",
                        strategy_tag="momentum",
                        side="YES",
                        entry_price=0.40,
                        bet_size=10.0,
                        bankroll=1000.0,
                        kelly_raw=0.1,
                        edge_est=0.05,
                        confidence=0.6,
                        reason="test",
                    )
                    placed_at = (
                        datetime.now(UTC) - timedelta(hours=7 if i == 0 else 1)
                    ).replace(tzinfo=None).isoformat()
                    with database._conn() as con:
                        con.execute("UPDATE paper_bets SET placed_at=? WHERE id=?", (placed_at, bet_id))
                        con.commit()

                with ExitStack() as stack:
                    stack.enter_context(patch("tracking.clv.fetch_markets", return_value=settlement_markets))
                    stack.enter_context(patch.object(risk_controls, "load_peak", return_value=1000.0))
                    stack.enter_context(patch.object(risk_controls, "save_peak"))
                    stack.enter_context(patch.object(main, "run_if_due"))
                    stack.enter_context(patch.object(main, "compute_drift_multiplier", return_value=(1.0, {})))
                    stack.enter_context(patch.object(main, "fetch_markets", return_value=market_df))
                    stack.enter_context(patch.object(main, "resolve_alpha_signals", return_value=0))
                    stack.enter_context(patch.object(main, "apply_filters", return_value=market_df))
                    stack.enter_context(patch.object(main, "log_prices"))
                    stack.enter_context(patch.object(main, "purge_old_history"))
                    stack.enter_context(patch.object(main, "get_history", return_value=history))
                    stack.enter_context(patch.object(main, "build_features", return_value={"mom_short": 0.02, "price": 0.45}))
                    stack.enter_context(patch.object(main, "compute_regime_features", return_value={
                        "volatility": 0.02,
                        "trend_strength": 0.01,
                        "autocorr": 0.1,
                        "vol_spike": 1.1,
                        "price_range": 0.05,
                    }))
                    stack.enter_context(patch.object(main.regime_model, "predict", return_value="neutral"))
                    stack.enter_context(patch.object(main.regime_model, "partial_fit"))
                    stack.enter_context(patch.object(main, "collect_alpha_diagnostics", return_value={}))
                    stack.enter_context(patch.object(main, "log_alpha_diagnostics"))
                    stack.enter_context(patch.object(main, "build_alpha_signals", return_value=[]))
                    stack.enter_context(patch.object(main, "log_alpha_signals", return_value=0))
                    stack.enter_context(patch.object(main, "aggregate_alpha_signals", return_value=[]))
                    stack.enter_context(patch.object(main, "evaluate_alpha_modules", return_value={}))
                    stack.enter_context(patch.object(main, "get_alpha_outcomes", return_value=pd.DataFrame()))
                    stack.enter_context(patch.object(main, "get_killed_strategies", return_value=[]))
                    stack.enter_context(patch.object(main, "get_active_strategies", return_value=["momentum"]))
                    stack.enter_context(patch.object(main.router, "select", return_value=["momentum"]))
                    stack.enter_context(patch.object(main, "run_strategies", return_value=[]))
                    stack.enter_context(patch.object(main, "allocate", return_value=[]))
                    stack.enter_context(patch.object(main, "apply_risk_constraints", return_value=[]))
                    stack.enter_context(patch.object(main.edge_model, "predict_prob", return_value=0.55))
                    stack.enter_context(patch.object(main.clv_model, "predict", return_value=0.0))
                    stack.enter_context(patch.object(main.meta_model, "predict_weights", return_value={"momentum": 1.0}))
                    stack.enter_context(patch.object(main, "send_summary"))
                    stack.enter_context(patch.object(main, "send_pick_alert"))
                    stack.enter_context(patch.object(main, "save_bankroll"))
                    risk_halt = stack.enter_context(patch.object(main, "send_risk_halt"))
                    main.run_cycle(1000.0, startup=False)

                self.assertFalse(risk_halt.called)
                self.assertEqual(database.get_open_position_stats()["n_open"], 7)
                closed = database.get_closed_bets(limit=20)
                self.assertEqual(len(closed), 1)
                self.assertEqual(closed.iloc[0]["result"], "timeout_win")
        finally:
            for path in (db_path, f"{db_path}-journal"):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except PermissionError:
                        pass


if __name__ == "__main__":
    unittest.main()
