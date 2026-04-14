import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime, UTC
from pathlib import Path
from data.database import get_closed_bets

logger = logging.getLogger(__name__)

STATE_FILE = Path("adaptation_state.json")

class AdaptationEngine:
    def __init__(self):
        self.state = self._load_state()

    def _load_state(self):
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except Exception:
                pass
        return {
            "segments": {},
            "tuned_params": {
                "edge_threshold": 0.04,
                "size_multiplier": 1.0,
                "risk_limit": 0.03
            },
            "strategy_weights": {}
        }

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def run_cycle_updates(self):
        """Runs the offline analytics, segmentation, feedback, and tuning."""
        df = get_closed_bets(limit=5000)

        # --- TASK 4: ADAPTATION ENGINE STABILITY ---
        # 1. Minimum sample size
        min_sample_size = 30
        if df.empty or len(df) < min_sample_size:
            return

        # 2. Update frequency (only every 20 trades)
        last_update_count = self.state.get("last_update_count", 0)
        if len(df) - last_update_count < 20:
            return
        self.state["last_update_count"] = len(df)

        # --- DAY 22: PERFORMANCE ANALYTICS ENGINE ---
        total_pnl = float(df["pnl"].sum())
        win_rate = float(df["result"].isin(["win", "timeout_win"]).mean())
        avg_clv = float(df["clv"].mean()) if "clv" in df.columns else 0.0

        if "roi" in df.columns and df["roi"].std() > 0:
            sharpe = float(df["roi"].mean() / (df["roi"].std() + 1e-6))
        else:
            sharpe = 0.0

        strat_perf = df.groupby("strategy_tag").agg({
            "pnl": "sum",
            "clv": "mean"
        }).to_dict("index")

        logger.info(f"PERFORMANCE_ANALYZED | PnL: ${total_pnl:.2f} | WinRate: {win_rate:.1%} | CLV: {avg_clv:.4f} | Sharpe: {sharpe:.2f}")

        # --- DAY 23: SIGNAL SEGMENTATION ---
        segments = {}
        if "edge_est" in df.columns and "confidence" in df.columns:
            df["edge_bucket"] = pd.cut(df["edge_est"], bins=[-np.inf, 0.02, 0.05, 0.10, np.inf], labels=["<2%", "2-5%", "5-10%", ">10%"]).astype(str)
            df["conf_bucket"] = pd.cut(df["confidence"], bins=[-np.inf, 0.3, 0.6, np.inf], labels=["low", "med", "high"]).astype(str)

            groups = df.groupby(["edge_bucket", "conf_bucket"])
            for (eb, cb), group in groups:
                if len(group) < 3: continue
                seg_roi = float(group["roi"].mean()) if "roi" in group.columns else 0.0
                seg_clv = float(group["clv"].mean()) if "clv" in group.columns else 0.0

                if seg_roi > 0.05 or seg_clv > 0.02:
                    tag = "STRONG_EDGE"
                elif seg_roi < -0.05 or seg_clv < -0.01:
                    tag = "NO_EDGE"
                else:
                    tag = "WEAK_EDGE"

                segments[f"{eb}_{cb}"] = tag

        self.state["segments"] = segments
        logger.info(f"SIGNAL_SEGMENTED | {len(segments)} segments classified")

        # --- DAY 27: FEEDBACK LOOP ---
        weights = {}
        for strat, perf in strat_perf.items():
            clv = perf.get("clv", 0)
            if pd.isna(clv): clv = 0
            if clv > 0.01:
                weights[strat] = 1.2
            elif clv < -0.01:
                weights[strat] = 0.5
            else:
                weights[strat] = 1.0
        self.state["strategy_weights"] = weights
        logger.info("FEEDBACK_LOOP_UPDATED | Strategy weights adjusted")

        # --- DAY 28: AUTOMATED PARAMETER TUNING ---
        recent_df = df.head(100)
        recent_win_rate = float(recent_df["result"].isin(["win", "timeout_win"]).mean())

        tuned_threshold = self.state["tuned_params"]["edge_threshold"]
        tuned_size_mult = self.state["tuned_params"]["size_multiplier"]

        # 3. Prevent rapid oscillation with dampening (EMA-like)
        target_size_mult = tuned_size_mult
        target_threshold = tuned_threshold

        if recent_win_rate > 0.55:
            target_size_mult = min(tuned_size_mult * 1.05, 1.5)
            target_threshold = max(tuned_threshold * 0.95, 0.02)
        elif recent_win_rate < 0.45:
            target_size_mult = max(tuned_size_mult * 0.90, 0.5)
            target_threshold = min(tuned_threshold * 1.10, 0.08)

        # Apply smoothing (alpha = 0.2)
        alpha = 0.2
        tuned_size_mult = (alpha * target_size_mult) + ((1 - alpha) * tuned_size_mult)
        tuned_threshold = (alpha * target_threshold) + ((1 - alpha) * tuned_threshold)

        self.state["tuned_params"]["edge_threshold"] = round(float(tuned_threshold), 4)
        self.state["tuned_params"]["size_multiplier"] = round(float(tuned_size_mult), 2)

        logger.info(f"PARAMETERS_TUNED | Threshold: {tuned_threshold:.4f} | Size Mult: {tuned_size_mult:.2f}")

        self._save_state()

    # --- DAY 25: REGIME DETECTION ---
    def classify_market_regime(self, volatility, volume, price_move):
        """Classify into LOW_VOL, HIGH_VOL, TRENDING, RANDOM"""
        if volatility > 0.05:
            return "HIGH_VOL"
        elif abs(price_move) > 0.05:
            return "TRENDING"
        elif volatility < 0.02:
            return "LOW_VOL"
        else:
            return "RANDOM"

    # --- DAY 24 & 26: STRATEGY FILTERING & REGIME ADAPTATION ---
    def process_signals(self, signals, feature_map):
        """Applies filters and regime adaptation before execution."""
        filtered_signals = []
        if not signals:
            return filtered_signals

        for sig in signals:
            edge_val = getattr(sig, 'edge', 0.0)
            conf_val = getattr(sig, 'confidence', 0.5)

            edge_bucket = "<2%" if edge_val <= 0.02 else "2-5%" if edge_val <= 0.05 else "5-10%" if edge_val <= 0.10 else ">10%"
            conf_bucket = "low" if conf_val <= 0.3 else "med" if conf_val <= 0.6 else "high"
            seg_key = f"{edge_bucket}_{conf_bucket}"

            segment_tag = self.state["segments"].get(seg_key, "WEAK_EDGE")

            # Day 24: Filter rules
            if segment_tag == "NO_EDGE":
                continue

            strat_weight = self.state["strategy_weights"].get(sig.strategy, 1.0)

            feats = feature_map.get(sig.market_id, {})
            volatility = feats.get("volatility", 0.0)
            volume = feats.get("volume", 0.0)
            price_move = feats.get("trend_strength", 0.0)

            regime = self.classify_market_regime(volatility, volume, price_move)
            sig.adaptive_regime = regime

            # Day 26: Regime-based adaptation
            regime_mult = 1.0
            regime_thresh_adj = 0.0

            if regime == "HIGH_VOL":
                regime_mult = 0.5
                regime_thresh_adj = 0.02
            elif regime == "LOW_VOL":
                regime_thresh_adj = 0.01
            elif regime == "TRENDING":
                regime_mult = 1.5

            sig_threshold = self.state["tuned_params"]["edge_threshold"] + regime_thresh_adj

            if edge_val < sig_threshold:
                continue

            base_mult = self.state["tuned_params"]["size_multiplier"]
            segment_mult = 0.5 if segment_tag == "WEAK_EDGE" else (1.5 if segment_tag == "STRONG_EDGE" else 1.0)

            final_mult = base_mult * segment_mult * regime_mult * strat_weight

            sig.adaptive_multiplier = final_mult
            filtered_signals.append(sig)

        if signals:
            logger.info(f"REGIME_DETECTED | Computed regimes for {len(signals)} signals")
            logger.info(f"STRATEGY_FILTER_APPLIED | Retained {len(filtered_signals)} out of {len(signals)}")
            logger.info(f"REGIME_ADJUSTMENT_APPLIED | Adjusted sizes and thresholds dynamically")

        return filtered_signals

adaptation_engine = AdaptationEngine()
