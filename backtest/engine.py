"""
backtest/engine.py — walk-forward (not train-on-test)
Splits data into rolling windows: train [0→t], test [t→t+w].
Only uses signals generated during the TEST window.
"""
import sqlite3, logging
import pandas as pd
import numpy as np
from alpha.evaluator import evaluate_alpha_modules
from config import DB_PATH, EDGE_THRESHOLD, KELLY_FRACTION, MAX_BET_PCT

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(self, initial_bankroll: float = 1000.0, window_days: int = 7):
        self.initial_bankroll = initial_bankroll
        self.window_days      = window_days

    def load_data(self) -> pd.DataFrame:
        with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
            df = pd.read_sql(
                """SELECT ml.market_id, ml.logged_at, ml.yes_price, ml.liquidity,
                          ml.volume, ml.one_day_change, ml.strategy, ml.signal_edge,
                          ml.regime, pb.result, pb.pnl, pb.clv, pb.bet_size, pb.entry_price
                   FROM market_log ml
                   LEFT JOIN paper_bets pb ON ml.market_id=pb.market_id
                     AND ml.strategy=pb.strategy_tag
                   ORDER BY ml.logged_at ASC""",
                con)
        df["logged_at"] = pd.to_datetime(df["logged_at"])
        return df

    def load_alpha_data(self) -> pd.DataFrame:
        with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
            try:
                return pd.read_sql(
                    "SELECT * FROM alpha_signals WHERE resolved_clv IS NOT NULL ORDER BY cycle_ts ASC",
                    con,
                )
            except Exception:
                return pd.DataFrame()

    def run(self) -> pd.DataFrame:
        df = self.load_data()
        if df.empty:
            logger.warning("No historical data. Run the bot first.")
            return pd.DataFrame()

        total_days = (df["logged_at"].max() - df["logged_at"].min()).days
        if total_days < self.window_days * 2:
            logger.info(f"Not enough history for walk-forward ({total_days} days). Running simple replay.")
            return self._simple_replay(df)

        # Walk-forward windows
        all_records = []
        bankroll    = self.initial_bankroll
        start       = df["logged_at"].min()
        end         = df["logged_at"].max()
        cursor      = start + pd.Timedelta(days=self.window_days)

        while cursor <= end:
            train = df[df["logged_at"] < cursor]
            test  = df[(df["logged_at"] >= cursor) &
                       (df["logged_at"] < cursor + pd.Timedelta(days=self.window_days))]
            cursor += pd.Timedelta(days=self.window_days)

            if test.empty:
                continue

            # Use train window to calibrate edge threshold (simple: median signal_edge)
            if not train.empty and "signal_edge" in train.columns:
                threshold = float(train["signal_edge"].dropna().quantile(0.70))
                threshold = max(threshold, EDGE_THRESHOLD)
            else:
                threshold = EDGE_THRESHOLD

            records, bankroll = self._replay_window(test, bankroll, threshold)
            all_records.extend(records)

        results = pd.DataFrame(all_records)
        if not results.empty:
            self._print_summary(results, "Walk-Forward")
        self._print_alpha_summary("Walk-Forward")
        return results

    def _simple_replay(self, df: pd.DataFrame) -> pd.DataFrame:
        records, _ = self._replay_window(df, self.initial_bankroll, EDGE_THRESHOLD)
        results = pd.DataFrame(records)
        if not results.empty:
            self._print_summary(results, "Simple Replay")
        self._print_alpha_summary("Simple Replay")
        return results

    def _replay_window(self, df, bankroll, threshold) -> tuple[list, float]:
        records = []
        peak    = bankroll

        for row in df.to_dict("records"):
            edge = row.get("signal_edge") or 0
            if edge < threshold:
                continue

            price = row.get("yes_price") or 0.5
            if price <= 0:
                continue

            decimal_odds = 1 / price
            b = decimal_odds - 1
            kelly_raw = max((price * (b+1) - 1) / b, 0) if b > 0 else 0
            bet_size  = min(bankroll * kelly_raw * KELLY_FRACTION, bankroll * MAX_BET_PCT)
            bet_size  = round(bet_size, 2)
            if bet_size <= 0:
                continue

            # Use actual result if recorded, else edge-informed sim
            result = row.get("result")
            if result == "win":
                pnl = bet_size * (decimal_odds - 1)
            elif result == "loss":
                pnl = -bet_size
            else:
                true_p = min(price + edge * 0.4, 0.95)
                won    = np.random.random() < true_p
                pnl    = bet_size * (decimal_odds-1) if won else -bet_size
                result = "win" if won else "loss"

            bankroll += pnl
            peak     = max(peak, bankroll)
            dd       = (peak - bankroll) / peak if peak > 0 else 0

            records.append({
                "date":     str(row.get("logged_at",""))[:10],
                "strategy": row.get("strategy",""),
                "regime":   row.get("regime",""),
                "edge":     round(float(edge),4),
                "bet_size": bet_size,
                "result":   result,
                "pnl":      round(float(pnl),2),
                "bankroll": round(bankroll,2),
                "drawdown": round(dd,4),
                "clv":      row.get("clv"),
            })
        return records, bankroll

    def _print_summary(self, df, label=""):
        if df.empty: return
        pnl      = df["pnl"].sum()
        wr       = (df["result"]=="win").mean()
        max_dd   = df["drawdown"].max()
        final    = df["bankroll"].iloc[-1]
        roi      = (final - self.initial_bankroll) / self.initial_bankroll * 100
        clv_avg  = df["clv"].dropna().mean() if df["clv"].notna().any() else None

        logger.info(f"=== BACKTEST [{label}] ===")
        logger.info(f"Trades: {len(df)} | Win: {wr:.1%} | PnL: ${pnl:.2f} | ROI: {roi:.1f}%")
        logger.info(f"Max DD: {max_dd:.1%} | Final BR: ${final:.2f}" +
                    (f" | CLV: {clv_avg:.5f}" if clv_avg else ""))
        if "strategy" in df.columns:
            logger.info("By strategy: " + str(df.groupby("strategy")["pnl"].sum().round(2).to_dict()))

    def _print_alpha_summary(self, label=""):
        alpha_df = self.load_alpha_data()
        if alpha_df.empty:
            logger.info(f"No alpha shadow history available for {label}.")
            return
        alpha_stats = evaluate_alpha_modules(alpha_df)
        if not alpha_stats:
            logger.info(f"No resolved alpha CLV data available for {label}.")
            return
        leaders = list(alpha_stats.values())[:5]
        logger.info(
            "=== ALPHA SHADOW [%s] === %s",
            label,
            " | ".join(
                f"{alpha['alpha_name']} clv={alpha['avg_clv']:.5f} hit={alpha['positive_rate']:.1%} n={alpha['n']} {alpha['status']}"
                for alpha in leaders
            ),
        )
