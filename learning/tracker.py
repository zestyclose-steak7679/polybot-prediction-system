"""
learning/tracker.py
─────────────────────────────────────────────────────────────
Tracks realized ROI per strategy and disables underperformers.

This is the learning loop:
  place bet → market resolves → record outcome →
  compute ROI per strategy → disable if ROI < threshold →
  only surviving strategies get capital next cycle

Tables used (in database.py):
  paper_bets  — has strategy_tag, result, pnl, bet_size columns
  strategy_stats — derived summary per strategy
"""

import pandas as pd
import sqlite3
import logging
from config import (
    DB_PATH,
    MIN_BETS_TO_EVAL,
    STRATEGY_MIN_ROI,
    ACTIVE_STRATEGIES,
)

logger = logging.getLogger(__name__)

WIN_RESULTS = {"win", "timeout_win"}
LOSS_RESULTS = {"loss", "timeout_loss"}


def _conn():
    return sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:"))


# ── Per-strategy ROI ──────────────────────────────────────

def compute_strategy_roi(strategy: str, last_n: int = 50) -> dict | None:
    """
    Compute ROI for a strategy over its last N closed bets.
    ROI = total_pnl / total_staked

    Returns None if not enough data yet.
    """
    with _conn() as con:
        df = pd.read_sql(
            """SELECT bet_size, pnl, result, clv
               FROM paper_bets
               WHERE strategy_tag = ?
                 AND result != 'open'
               ORDER BY placed_at DESC
               LIMIT ?""",
            con,
            params=(strategy, last_n),
        )

    if len(df) < MIN_BETS_TO_EVAL:
        return None   # not enough data

    total_staked = df["bet_size"].sum()
    total_pnl    = df["pnl"].sum()
    roi          = total_pnl / total_staked if total_staked > 0 else 0.0
    win_rate     = df["result"].isin(WIN_RESULTS).mean()
    clv_series   = df["clv"].dropna()
    positive_clv_rate = float((clv_series > 0).mean()) if not clv_series.empty else None

    return {
        "strategy":    strategy,
        "n_bets":      len(df),
        "total_staked": round(total_staked, 2),
        "total_pnl":   round(total_pnl, 2),
        "roi":         round(roi, 4),
        "win_rate":    round(win_rate, 4),
        "avg_clv":     round(float(clv_series.mean()), 5) if not clv_series.empty else None,
        "positive_clv_rate": round(positive_clv_rate, 4) if positive_clv_rate is not None else None,
        "resolved_clv_n": int(len(clv_series)),
    }


def get_active_strategies() -> list[str]:
    """
    Return list of strategies that are still performing above threshold.
    Always returns at least one strategy (never fully disabled).
    """
    active = []
    disabled = []

    for strategy in ACTIVE_STRATEGIES:
        stats = compute_strategy_roi(strategy)

        if stats is None:
            # Not enough data → keep active (benefit of the doubt)
            active.append(strategy)
            logger.info(f"Strategy '{strategy}': not enough data yet — keeping active")
            continue

        if stats["roi"] >= STRATEGY_MIN_ROI:
            active.append(strategy)
            logger.info(
                f"Strategy '{strategy}': ROI={stats['roi']*100:.1f}% "
                f"({stats['n_bets']} bets) — ACTIVE"
            )
        else:
            disabled.append(strategy)
            logger.warning(
                f"Strategy '{strategy}': ROI={stats['roi']*100:.1f}% "
                f"({stats['n_bets']} bets) — DISABLED (below {STRATEGY_MIN_ROI*100:.0f}%)"
            )

    # Failsafe: if everything disabled, keep the best one anyway
    if not active and disabled:
        best = max(
            disabled,
            key=lambda s: (compute_strategy_roi(s) or {}).get("roi", -999)
        )
        logger.warning(f"All strategies disabled — re-enabling best: {best}")
        active = [best]
    elif not active and not disabled:
        # Fallback if ACTIVE_STRATEGIES is empty or something weird happens
        active = ACTIVE_STRATEGIES[:1] if ACTIVE_STRATEGIES else ["momentum"]

    return active


def get_all_strategy_stats() -> list[dict]:
    """Return stats for all strategies (for summary message)."""
    stats = []
    for strategy in ACTIVE_STRATEGIES:
        s = compute_strategy_roi(strategy)
        if s:
            stats.append(s)
        else:
            stats.append({
                "strategy": strategy,
                "n_bets": 0,
                "roi": None,
                "win_rate": None,
                "avg_clv": None,
                "positive_clv_rate": None,
                "resolved_clv_n": 0,
            })
    return stats
