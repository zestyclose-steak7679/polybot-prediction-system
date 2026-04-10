"""portfolio/strategy_weights.py — Sharpe-based dynamic strategy weighting"""
import pandas as pd
import numpy as np
import logging
logger = logging.getLogger(__name__)

MIN_TOTAL_CLOSED_BETS = 20
MIN_CLV_RESOLVED_PER_STRATEGY = 10


def get_strategy_weight_gate(closed_bets: pd.DataFrame, strategy_names: list[str] | None = None) -> dict:
    strategy_names = strategy_names or (
        sorted(closed_bets["strategy_tag"].dropna().unique().tolist())
        if not closed_bets.empty and "strategy_tag" in closed_bets.columns
        else []
    )
    clv_counts = {}
    if not closed_bets.empty and "strategy_tag" in closed_bets.columns:
        clv_counts = (
            closed_bets.groupby("strategy_tag")["clv"]
            .apply(lambda s: int(s.notna().sum()))
            .to_dict()
        )

    missing = {
        name: clv_counts.get(name, 0)
        for name in strategy_names
        if clv_counts.get(name, 0) < MIN_CLV_RESOLVED_PER_STRATEGY
    }
    active = len(closed_bets) >= MIN_TOTAL_CLOSED_BETS and not missing
    reason = None
    if len(closed_bets) < MIN_TOTAL_CLOSED_BETS:
        reason = f"need {MIN_TOTAL_CLOSED_BETS} closed bets, have {len(closed_bets)}"
    elif missing:
        reason = "insufficient CLV samples: " + ", ".join(f"{k}={v}" for k, v in sorted(missing.items()))

    return {
        "active": active,
        "reason": reason,
        "closed_bets": int(len(closed_bets)),
        "clv_counts": clv_counts,
    }

def compute_sharpe_weights(closed_bets: pd.DataFrame, window: int = 50) -> dict:
    """
    Weight each strategy by its rolling CLV Sharpe ratio.
    Strategies with negative Sharpe get 0 weight.
    Falls back to equal weights if data is insufficient.
    """
    if closed_bets.empty or "strategy_tag" not in closed_bets.columns:
        return {}

    weights = {}
    for strat, grp in closed_bets.groupby("strategy_tag"):
        clv = grp["clv"].dropna().tail(window)
        if len(clv) < 5:
            weights[strat] = 0.1   # benefit of the doubt
            continue
        mean = float(clv.mean())
        std  = float(clv.std()) + 1e-6
        sharpe = mean / std
        weights[strat] = max(sharpe, 0.0)

    total = sum(weights.values())
    if total <= 0:
        return {k: 1/len(weights) for k in weights} if weights else {}

    vals = np.array(list(weights.values()))
    exp_vals = np.exp(vals - np.max(vals))
    softmax_vals = exp_vals / np.sum(exp_vals)
    normalised = {k: round(float(v), 4) for k, v in zip(weights.keys(), softmax_vals)}

    logger.info("Strategy weights (Sharpe): " + str(normalised))
    return normalised
