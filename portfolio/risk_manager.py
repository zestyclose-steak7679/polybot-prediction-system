"""
portfolio/risk_manager.py — empirical correlation + hard limits
"""
import numpy as np
import pandas as pd
import logging
from config import MAX_BET_PCT
logger = logging.getLogger(__name__)

MAX_EXPOSURE = 0.30
MAX_PER_SIDE = 0.10


def _empirical_correlation(signals: list) -> np.ndarray:
    """
    Build correlation matrix from historical trade outcomes.
    Falls back to structural correlation if insufficient data.
    """
    n = len(signals)
    if n <= 1:
        return np.eye(n)

    try:
        from data.database import get_closed_bets
        df = get_closed_bets(limit=300)
        if df.empty or "strategy_tag" not in df.columns or "placed_at" not in df.columns:
            raise ValueError("no data")

        # Pivot to get per-strategy PnL series
        df["placed_at"] = pd.to_datetime(df["placed_at"])
        pivoted = df.pivot_table(
            index=df["placed_at"].dt.date,
            columns="strategy_tag",
            values="pnl",
            aggfunc="sum"
        ).fillna(0)

        strat_names = [s.strategy for s in signals]
        available   = [s for s in strat_names if s in pivoted.columns]

        if len(available) < 2:
            raise ValueError("not enough strategies")

        corr = pivoted[available].corr().values
        # Map back to full n×n matrix
        full = np.full((n,n), 0.2)
        np.fill_diagonal(full, 1.0)
        name_idx = {s: i for i,s in enumerate(strat_names)}
        for i, si in enumerate(available):
            for j, sj in enumerate(available):
                fi = name_idx.get(si, -1)
                fj = name_idx.get(sj, -1)
                if fi >= 0 and fj >= 0:
                    full[fi][fj] = float(corr[i][j]) if not np.isnan(corr[i][j]) else 0.2
        return full

    except Exception:
        # Structural fallback
        corr = np.full((n, n), 0.20)
        np.fill_diagonal(corr, 1.0)
        for i in range(n):
            for j in range(n):
                if i == j: continue
                if signals[i].market_id == signals[j].market_id:
                    corr[i][j] = 0.85   # same event = high correlation
                elif signals[i].strategy == signals[j].strategy:
                    corr[i][j] = 0.35
        return corr


def adjust_for_correlation(signals: list, sizes: list) -> list:
    if len(signals) <= 1:
        return sizes
    corr = _empirical_correlation(signals)
    adjusted = []
    for i in range(len(signals)):
        # Penalty = sum of off-diagonal correlations for this position
        off_diag_sum = sum(corr[i][j] for j in range(len(signals)) if j != i)
        avg_corr = off_diag_sum / max(len(signals) - 1, 1)
        scale = max(1.0 - avg_corr * 0.4, 0.4)
        adjusted.append(sizes[i] * scale)
    return adjusted


def enforce_limits(sizes: list, bankroll: float) -> list:
    total = sum(sizes)
    max_total = bankroll * MAX_EXPOSURE
    if total > max_total:
        scale = max_total / total
        sizes = [s * scale for s in sizes]
    return [min(s, bankroll * MAX_BET_PCT) for s in sizes]


def apply_risk_constraints(signals: list, sizes: list, bankroll: float) -> list:
    sizes = adjust_for_correlation(signals, sizes)
    sizes = enforce_limits(sizes, bankroll)
    sizes = [round(max(s, 0), 2) for s in sizes]
    logger.info(f"Risk-adjusted: {sum(1 for s in sizes if s>0)} bets | ${sum(sizes):.2f}")
    return sizes
