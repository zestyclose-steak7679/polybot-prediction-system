"""Quantified decision engine for probability estimation and mispricing detection."""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Day 8 - Base Probability Model
def compute_fair_value_probability(row: dict, history: pd.DataFrame) -> dict:
    """
    Computes a base heuristic probability (fair value).
    Inputs: market price, historical price, volume.
    Logs: PROBABILITY_COMPUTED
    """
    market_price = float(row.get("yes_price", 0.5))
    volume = float(row.get("volume", 0.0) or 0.0)

    # Simple heuristic adjustments based on history
    if not history.empty and "yes_price" in history.columns:
        recent_prices = history["yes_price"].tail(5).to_numpy(dtype=float)
        trend = recent_prices[-1] - recent_prices[0] if len(recent_prices) >= 2 else 0.0
    else:
        trend = 0.0

    # Logit-style probability adjustment
    # Normalize volume for a subtle confidence weight
    volume_factor = np.log1p(volume) / 20.0
    adjustment = float(np.clip(trend * volume_factor, -0.05, 0.05))

    model_probability = float(np.clip(market_price + adjustment, 0.01, 0.99))

    result = {
        "market_price_probability": market_price,
        "model_probability": model_probability
    }

    logger.info(f"PROBABILITY_COMPUTED | Market: {row.get('market_id')} | Model Prob: {model_probability:.4f} | Market Prob: {market_price:.4f}")
    return result

# Day 9 - Mispricing Detector (Core Alpha)
def detect_mispricing(prob_data: dict, threshold: float = 0.03) -> dict:
    """
    Computes edge = model_probability - market_probability.
    Classifies signals and flags if edge > threshold.
    Logs: EDGE_DETECTED
    """
    model_prob = prob_data["model_probability"]
    market_prob = prob_data["market_price_probability"]

    edge = model_prob - market_prob
    abs_edge = abs(edge)

    classification = "NONE"
    passed_threshold = False

    if abs_edge > threshold:
        passed_threshold = True
        classification = "LONG" if edge > 0 else "SHORT"
        logger.info(f"EDGE_DETECTED | Edge: {edge:.4f} | Class: {classification} | Model Prob: {model_prob:.4f} | Market Prob: {market_prob:.4f}")

    return {
        "edge": edge,
        "abs_edge": abs_edge,
        "classification": classification,
        "passed_threshold": passed_threshold
    }


from datetime import UTC, datetime

# Global dictionary to track shadow signals (in-memory for now, can be ported to DB later)
_shadow_ledger = []

# Day 10 & 11 - Shadow Mode Activation & Signal Performance Tracking
def track_shadow_signal(market_id: str, edge_data: dict, prob_data: dict, row: dict) -> dict:
    """
    Routes signal to SHADOW mode (no execution).
    Logs: direction, edge, timestamp.
    Stores: edge at entry, market_price_probability, model_probability.
    """
    if not edge_data["passed_threshold"]:
        return {}

    timestamp = datetime.now(UTC).replace(tzinfo=None).isoformat()
    direction = "YES" if edge_data["classification"] == "LONG" else "NO"

    signal_record = {
        "market_id": market_id,
        "timestamp": timestamp,
        "direction": direction,
        "edge": edge_data["edge"],
        "market_price_probability": prob_data["market_price_probability"],
        "model_probability": prob_data["model_probability"],
        "status": "SHADOW_OPEN",
        "entry_price": row.get("yes_price", 0.5) if direction == "YES" else row.get("no_price", 0.5),
        "volume": row.get("volume", 0.0),
        "liquidity": row.get("liquidity", 0.0)
    }

    _shadow_ledger.append(signal_record)
    logger.info(f"SHADOW_SIGNAL_ROUTED | Market: {market_id} | Dir: {direction} | Edge: {edge_data['edge']:.4f} | TS: {timestamp}")

    return signal_record

def evaluate_shadow_performance(current_markets_df: pd.DataFrame):
    """
    For each shadow signal, compute CLV and win/loss if market has resolved or reached CLV capture window.
    Logs: SHADOW_EVALUATION
    """
    if not _shadow_ledger:
        return

    evaluated_count = 0
    for record in _shadow_ledger:
        if record["status"] != "SHADOW_OPEN":
            continue

        market_rows = current_markets_df[current_markets_df["market_id"] == record["market_id"]]
        if market_rows.empty:
            continue

        row = market_rows.iloc[0]
        resolved_yes = row["yes_price"] >= 0.95
        resolved_no = row["yes_price"] <= 0.05

        # Simple evaluation criteria: if resolved or large price movement
        if resolved_yes or resolved_no:
            closing_price = float(row["yes_price"] if record["direction"] == "YES" else row["no_price"])
            entry_price = float(record["entry_price"])

            # CLV = (closing_price - entry_price) * (+1 for YES, -1 for NO implies we handle it differently based on side, but entry price is already side-adjusted)
            clv = closing_price - entry_price
            outcome = "win" if clv > 0 else "loss"

            record["clv"] = clv
            record["outcome"] = outcome
            record["status"] = "SHADOW_CLOSED"

            logger.info(f"SHADOW_EVALUATION | Market: {record['market_id']} | Outcome: {outcome} | CLV: {clv:.4f} | Edge at Entry: {record['edge']:.4f}")
            evaluated_count += 1

    if evaluated_count > 0:
        logger.info(f"Completed shadow evaluation for {evaluated_count} signals.")


# Day 12 & 13 & 14 - Signal Scoring System, Edge Validation, Partial Activation
def score_and_activate_signals(current_markets_df: pd.DataFrame) -> list:
    """
    Scores signals based on edge, volume, and volatility.
    Filters consistently negative signals.
    Promotes top X% to ACTIVE, keeps rest in SHADOW.
    Logs: SIGNAL_SCORED, EDGE_VALIDATED, SIGNAL_ACTIVATED
    """
    open_signals = [rec for rec in _shadow_ledger if rec["status"] == "SHADOW_OPEN"]
    if not open_signals:
        return []

    # Calculate historical win rate / avg CLV for validation (Day 13)
    closed_signals = [rec for rec in _shadow_ledger if rec["status"] == "SHADOW_CLOSED" and "clv" in rec]

    if closed_signals:
        avg_clv = sum(r["clv"] for r in closed_signals) / len(closed_signals)
        win_rate = sum(1 for r in closed_signals if r["outcome"] == "win") / len(closed_signals)
        logger.info(f"EDGE_VALIDATED | Shadow Avg CLV: {avg_clv:.4f} | Win Rate: {win_rate:.1%}")

        # If overall performance is terrible, increase threshold dynamically
        if avg_clv < -0.05:
            logger.warning("EDGE_VALIDATED | Consistently negative signals detected. Adjusting threshold dynamically.")
            min_confidence_edge = 0.05
        else:
            min_confidence_edge = 0.03
    else:
        min_confidence_edge = 0.03 # Default

    # Day 12 - Scoring
    scored_signals = []
    for record in open_signals:
        edge = abs(record["edge"])
        volume = record["volume"]

        # Volatility proxy: price range or just simple proxy from edge variance
        # In absence of full volatility data here, we use a simple normalization of volume and edge
        vol_score = np.log1p(volume) / 20.0
        edge_score = min(edge / 0.10, 1.0)

        # f(edge, volume, volatility)
        score = 0.7 * edge_score + 0.3 * vol_score
        record["score"] = score
        logger.info(f"SIGNAL_SCORED | Market: {record['market_id']} | Score: {score:.4f} | Edge: {record['edge']:.4f}")

        # Day 13 - Edge Validation filtering
        if edge >= min_confidence_edge and score > 0.4:
            scored_signals.append(record)

    # Day 14 - Partial Activation
    scored_signals.sort(key=lambda x: x["score"], reverse=True)

    # Promote top 20%
    promotion_count = max(1, int(len(scored_signals) * 0.2))

    activated = []
    for i, record in enumerate(scored_signals):
        if i < promotion_count:
            record["flag"] = "ACTIVE"
            activated.append(record)
            logger.info(f"SIGNAL_ACTIVATED | Market: {record['market_id']} | Score: {record['score']:.4f}")
        else:
            record["flag"] = "SHADOW"

    return activated

def run_quant_pipeline(feature_ready_df: pd.DataFrame, feature_map: dict, history_map: dict):
    """
    Main entry point for the quant engine pipeline.
    """
    logger.info("Starting quant engine pipeline...")

    # 1. Evaluate existing shadow signals (Day 11)
    evaluate_shadow_performance(feature_ready_df)

    # 2. Generate new signals (Day 8 & 9 & 10)
    for row in feature_ready_df.to_dict("records"):
        market_id = row["market_id"]
        history = history_map.get(market_id, pd.DataFrame())

        prob_data = compute_fair_value_probability(row, history)
        edge_data = detect_mispricing(prob_data)

        if edge_data["passed_threshold"]:
            track_shadow_signal(market_id, edge_data, prob_data, row)

    # 3. Score, Validate, and Activate (Day 12, 13, 14)
    activate_signals = score_and_activate_signals(feature_ready_df)

    if activate_signals:
        logger.info(f"Quant pipeline complete. {len(activate_signals)} signals activated.")
