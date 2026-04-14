"""
portfolio/allocator.py
─────────────────────────────────────────────────────────────
Distributes capital across multiple simultaneous signals
proportional to edge strength.

WHY THIS MATTERS:
  Betting the same fixed % on every signal ignores information.
  A signal with 8% edge deserves 4x more capital than one with 2% edge.

HOW IT WORKS:
  1. Take all signals above threshold
  2. Compute edge weights (signal.edge / total_edge)
  3. Allocate portion of deployable capital proportionally
  4. Apply Kelly as a second check on each allocation
  5. Hard cap per-bet to MAX_BET_PCT

DEPLOYABLE CAPITAL:
  We don't bet the full bankroll — only DEPLOY_PCT of it.
  This leaves buffer for future opportunities and drawdowns.
"""

import numpy as np
import logging
from config import MAX_BET_PCT
from scoring.engine import kelly_bet

logger = logging.getLogger(__name__)

DEPLOY_PCT = 0.30   # deploy at most 30% of bankroll per cycle across all bets


def allocate(signals: list, bankroll: float) -> list:
    """
    Args:
      signals: list of Signal objects (from scoring/strategies.py)
      bankroll: current paper bankroll

    Returns:
      list of dicts with signal + bet_size added
    """
    if not signals:
        return []

    # Only allocate to signals with positive edge
    eligible = [s for s in signals if s.edge > 0]
    if not eligible:
        return []

    total_edge = sum(s.edge for s in eligible)
    deployable = bankroll * DEPLOY_PCT

    allocations = []
    for sig in eligible:
        # Edge-proportional share of deployable capital
        weight          = sig.edge / total_edge
        edge_based_size = deployable * weight

        # Kelly formula: fraction = edge / (1 - price)
        kelly_fraction = sig.edge / (1.0 - sig.price) if sig.price < 1.0 else 0.0
        from config import KELLY_FRACTION
        base_kelly_size = bankroll * kelly_fraction * KELLY_FRACTION

        # Scale Kelly bet by confidence
        kelly_size = base_kelly_size * (0.5 + 0.5 * getattr(sig, "confidence", 0.0))

        decimal_odds = (1.0 / sig.price) - 1.0 if sig.price > 0 else 2.0

        # Take the more conservative of the two
        bet_size = min(edge_based_size, kelly_size)

        # Hard cap
        max_allowed = bankroll * MAX_BET_PCT
        bet_size    = min(bet_size, max_allowed)
        bet_size    = round(max(0.0, bet_size), 2)

        if bet_size <= 0:
            continue

        allocations.append({
            "signal":            sig,
            "bet_size":          bet_size,
            "kelly_raw":         kelly_fraction,
            "decimal_odds":      decimal_odds,
            "edge_weight":       round(weight, 4),
            "portfolio_pct":     round(bet_size / bankroll * 100, 2),
        })

        logger.debug(
            f"Alloc: {sig.strategy} {sig.side} '{sig.question[:40]}' "
            f"edge={sig.edge:.3f} weight={weight:.3f} size=${bet_size:.2f}"
        )

    total_allocated = sum(a["bet_size"] for a in allocations)

    # --- TASK 5: SYSTEM SAFETY CHECKS (Capital Constraint) ---
    if total_allocated > bankroll:
        logger.warning(f"Total allocation (${total_allocated:.2f}) exceeds bankroll (${bankroll:.2f}). Scaling down.")
        scale_factor = bankroll / total_allocated
        for a in allocations:
            a["bet_size"] = round(a["bet_size"] * scale_factor, 2)
        total_allocated = sum(a["bet_size"] for a in allocations)

    logger.info(
        f"Portfolio: {len(allocations)} positions | "
        f"${total_allocated:.2f} deployed ({total_allocated/bankroll*100:.1f}% of bankroll)"
    )
    return allocations


def portfolio_summary(allocations: list, bankroll: float) -> str:
    """Human-readable summary of allocation decisions."""
    if not allocations:
        return "No allocations this cycle."
    total = sum(a["bet_size"] for a in allocations)
    lines = [f"📊 Portfolio: {len(allocations)} bets | ${total:.2f} ({total/bankroll*100:.1f}%)"]
    for a in allocations:
        sig = a["signal"]
        lines.append(
            f"  {sig.strategy:13s} {sig.side} {sig.edge*100:.1f}% edge → ${a['bet_size']:.2f}"
        )
    return "\n".join(lines)
