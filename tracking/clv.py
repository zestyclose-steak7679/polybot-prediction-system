"""
tracking/clv.py
CLV = (1/entry_price) - (1/closing_price)
closing_price captured only when market is near resolution
to avoid noisy early-lifecycle prices.
"""
import logging
import pandas as pd
from datetime import UTC, datetime
from config import MAX_POSITION_AGE_HOURS
from data.database import get_open_bets, close_bet, get_closed_bets
from data.markets import fetch_single_market

logger = logging.getLogger(__name__)
CLV_CAPTURE_HOURS = 48   # only capture closing price within 48h of resolution


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def compute_clv(entry_price: float, closing_price: float, direction: int) -> float | None:
    if not entry_price or not closing_price or entry_price <= 0 or closing_price <= 0:
        return None
    return round((closing_price - entry_price) * direction, 5)


def _hours_to_resolution(end_date_str: str) -> float:
    try:
        end = datetime.fromisoformat(str(end_date_str).replace("Z","").split("+")[0])
        return max((end - _utc_now()).total_seconds() / 3600, 0.0)
    except Exception:
        return 999.0


def hours_open(placed_at_str: str) -> float:
    try:
        opened = datetime.fromisoformat(str(placed_at_str).replace("Z", "").split("+")[0])
        return max((_utc_now() - opened).total_seconds() / 3600, 0.0)
    except Exception:
        return 0.0


def settle_and_compute_clv(bankroll: float) -> tuple[float, dict]:
    """
    Called at the START of every cycle.
    Returns updated bankroll + settlement stats dict.
    """
    stats = {
        "closed_count": 0,
        "timeout_closed_count": 0,
        "clv_resolved_count": 0,
        "returned_capital": 0.0,
        "avg_clv_closed": None,
    }

    open_bets = get_open_bets()
    if open_bets.empty:
        return bankroll, stats

    now = datetime.now(UTC).replace(tzinfo=None)
    clv_values = []

    for _, bet in open_bets.iterrows():
        market_id = bet["market_id"]
        entry_price = bet["entry_price"]
        bet_size = bet["bet_size"]
        side = bet["side"]

        # Get current market data
        current = fetch_single_market(market_id)
        if current is None:
            continue

        current_price = current["yes_price"]
        hours_open_val = hours_open(bet.get("placed_at", ""))

        # Determine if market resolved
        is_resolved = (
            current_price >= 0.95 or
            current_price <= 0.05 or
            current.get("closed", False)
        )
        is_stale = hours_open_val >= MAX_POSITION_AGE_HOURS

        if not (is_resolved or is_stale):
            continue  # still live, skip

        # --- Compute result ---
        if side == "YES":
            won = current_price >= 0.95
            direction = 1
            clv = (current_price - entry_price) * direction
        else:
            won = current_price <= 0.05
            direction = -1
            clv = (current_price - entry_price) * direction

        # --- Compute P&L ---
        if won:
            pnl = bet_size * (1.0 / entry_price - 1.0)
        else:
            pnl = -bet_size

        if is_stale and not is_resolved:
            if side == "YES":
                pnl = bet_size * (current_price / entry_price - 1.0)
            else:
                no_entry = 1.0 - entry_price
                no_current = 1.0 - current_price
                pnl = bet_size * (no_current / no_entry - 1.0)

        returned = bet_size + pnl
        bankroll += returned
        stats["returned_capital"] += returned
        clv_values.append(clv)

        result = "win" if won else ("timeout_loss" if is_stale and pnl < 0 else "timeout_win" if is_stale else "loss")

        close_bet(
            bet_id=bet["id"],
            exit_price=current_price,
            closing_price=current_price,
            result=result,
            pnl=round(pnl, 4),
            clv=round(clv, 5),
        )

        stats["closed_count"] += 1
        if is_stale:
            stats["timeout_closed_count"] += 1
        if is_resolved:
            stats["clv_resolved_count"] += 1

        logger.info(
            f"Settled #{bet['id']} [{bet['strategy_tag']}]: "
            f"{result.upper()} P&L=${pnl:+.2f} CLV={clv:.5f}"
        )

    if clv_values:
        stats["avg_clv_closed"] = round(sum(clv_values) / len(clv_values), 5)

    return bankroll, stats


def clv_report() -> dict:
    df = get_closed_bets()
    clv_data = df["clv"].dropna() if not df.empty else pd.Series()
    if clv_data.empty:
        return {"n":0,"avg_clv":0.0,"positive_rate":0.0,"clv_sharpe":0.0,"strategy_clv":{}}

    avg    = float(clv_data.mean())
    std    = float(clv_data.std()) + 1e-9
    pos    = float((clv_data > 0).mean())
    sharpe = round(avg / std, 3)

    strategy_clv = {}
    if "strategy_tag" in df.columns:
        for strat, grp in df.groupby("strategy_tag"):
            c = grp["clv"].dropna()
            if not c.empty:
                strategy_clv[strat] = round(float(c.mean()), 5)

    return {
        "n": len(clv_data), "avg_clv": round(avg,5),
        "positive_rate": round(pos,3), "clv_sharpe": sharpe,
        "strategy_clv": strategy_clv,
    }
