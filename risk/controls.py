"""
risk/controls.py
Hard risk rules. These override everything else.

Rule 1: drawdown halt
  If bankroll drops 20% from peak, stop all betting.

Rule 2: open position limit
  Max N concurrent open paper bets.

Rule 3: per-bet cap
  No single bet exceeds MAX_BET_PCT of current bankroll.
"""

import logging
from pathlib import Path

from config import MAX_BET_PCT, MAX_DRAWDOWN_PCT, MAX_OPEN_BETS
from data.database import get_open_position_stats

logger = logging.getLogger(__name__)

PEAK_FILE = "peak_bankroll.txt"


def load_peak(current_bankroll: float) -> float:
    try:
        peak = float(Path(PEAK_FILE).read_text().strip())
        return max(peak, current_bankroll)
    except Exception:
        return current_bankroll


def save_peak(peak: float):
    Path(PEAK_FILE).write_text(str(round(peak, 2)))


def update_peak(bankroll: float) -> float:
    peak = load_peak(bankroll)
    if bankroll >= peak:
        save_peak(bankroll)
    return peak


def check_drawdown(bankroll: float) -> tuple[bool, str]:
    """Returns (ok, reason)."""
    peak = load_peak(bankroll)
    drawdown = (peak - bankroll) / peak if peak > 0 else 0.0

    if drawdown >= MAX_DRAWDOWN_PCT:
        msg = (
            f"DRAWDOWN HALT: {drawdown*100:.1f}% drawdown "
            f"(peak ${peak:.2f} -> current ${bankroll:.2f}). "
            f"Threshold: {MAX_DRAWDOWN_PCT*100:.0f}%"
        )
        logger.warning(msg)
        return False, msg

    return True, f"Drawdown {drawdown*100:.1f}% | within limit"


def check_open_positions() -> tuple[bool, str]:
    """Returns (ok, reason). ok=False means too many open bets."""
    stats = get_open_position_stats()
    n_open = stats["n_open"]
    avg_hold_hours = stats["avg_hold_hours"]
    stale_count = stats["stale_count"]

    if n_open >= MAX_OPEN_BETS:
        msg = (
            f"Max open bets reached ({n_open}/{MAX_OPEN_BETS}) "
            f"| avg hold {avg_hold_hours:.1f}h | stale {stale_count} | skipping new signals"
        )
        logger.info(msg)
        return False, msg

    return True, f"Open bets: {n_open}/{MAX_OPEN_BETS} | avg hold {avg_hold_hours:.1f}h | stale {stale_count}"


def clamp_bet_size(bet_size: float, bankroll: float) -> float:
    """Hard cap on bet size regardless of Kelly output."""
    max_allowed = bankroll * MAX_BET_PCT
    clamped = min(bet_size, max_allowed)
    if clamped < bet_size:
        logger.info(f"Bet clamped: ${bet_size:.2f} -> ${clamped:.2f} (max {MAX_BET_PCT*100:.0f}%)")
    return round(clamped, 2)


def run_all_checks(bankroll: float) -> tuple[bool, list[str]]:
    """
    Run all risk checks.
    Returns (all_ok, list_of_messages).
    If all_ok is False, do not place bets.
    """
    messages = []
    try:
        ok, msg = check_drawdown(bankroll)
        messages.append(msg)
        if not ok:
            return False, messages

        ok, msg = check_open_positions()
        messages.append(msg)
        if not ok:
            return False, messages

        return True, messages
    except Exception as e:
        logger.error(f"Error running risk checks: {e}")
        return False, [f"Risk checks failed with error: {e}"]
