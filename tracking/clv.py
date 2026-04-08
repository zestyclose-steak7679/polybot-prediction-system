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
from data.markets import fetch_markets

logger = logging.getLogger(__name__)
CLV_CAPTURE_HOURS = 48   # only capture closing price within 48h of resolution


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def compute_clv(entry_price: float, closing_price: float) -> float | None:
    if not entry_price or not closing_price or entry_price <= 0 or closing_price <= 0:
        return None
    closing_price = max(closing_price, 0.01)
    return round((1 / entry_price) - (1 / closing_price), 5)


def _hours_to_resolution(end_date_str: str) -> float:
    try:
        end = datetime.fromisoformat(str(end_date_str).replace("Z","").split("+")[0])
        return max((end - _utc_now()).total_seconds() / 3600, 0.0)
    except Exception:
        return 999.0


def _hours_open(placed_at_str: str) -> float:
    try:
        opened = datetime.fromisoformat(str(placed_at_str).replace("Z", "").split("+")[0])
        return max((_utc_now() - opened).total_seconds() / 3600, 0.0)
    except Exception:
        return 0.0


def settle_and_compute_clv(bankroll: float) -> tuple[float, dict]:
    open_bets = get_open_bets()
    if open_bets.empty:
        return bankroll, {
            "closed_count": 0,
            "timeout_closed_count": 0,
            "returned_capital": 0.0,
            "avg_clv_closed": None,
            "clv_resolved_count": 0,
        }

    current_markets = fetch_markets()
    closed_count = 0
    timeout_closed_count = 0
    returned_capital = 0.0
    resolved_clvs: list[float] = []

    for _, bet in open_bets.iterrows():
        if current_markets.empty:
            break

        market_row = current_markets[current_markets["market_id"] == bet["market_id"]]
        if market_row.empty:
            continue

        row = market_row.iloc[0]
        resolved_yes = row["yes_price"] >= 0.95
        resolved_no  = row["yes_price"] <= 0.05
        current_price = row["yes_price"] if bet["side"] == "YES" else row["no_price"]
        hours_left = _hours_to_resolution(row.get("end_date",""))
        hours_open = _hours_open(bet.get("placed_at", ""))
        stale_position = hours_open >= MAX_POSITION_AGE_HOURS

        # CLV: only capture near resolution window (not early lifecycle noise)
        clv = None
        if hours_left <= CLV_CAPTURE_HOURS or stale_position:
            clv = compute_clv(bet["entry_price"], current_price)
        elif not (resolved_yes or resolved_no):
            continue  # too early to settle or get meaningful CLV

        if stale_position and not (resolved_yes or resolved_no):
            shares = bet["bet_size"] / bet["entry_price"] if bet["entry_price"] > 0 else 0.0
            proceeds = shares * current_price
            pnl = proceeds - bet["bet_size"]
            result = "timeout_win" if pnl >= 0 else "timeout_loss"
            bankroll += proceeds
            returned_capital += proceeds
            closed_count += 1
            timeout_closed_count += 1
            if clv is not None:
                resolved_clvs.append(clv)
            close_bet(bet["id"], current_price, current_price, result, pnl, clv)
            logger.info(
                "Timed exit #%s [%s]: %s after %.1fh | P&L=%+.2f CLV=%s",
                bet["id"],
                bet["strategy_tag"],
                result.upper(),
                hours_open,
                pnl,
                clv,
            )
            continue

        if not (resolved_yes or resolved_no):
            # Still open but in CLV window — update closing snapshot without settling
            # We don't close here, just log the CLV candidate
            # (will settle next cycle when resolved)
            continue

        won = (bet["side"]=="YES" and resolved_yes) or (bet["side"]=="NO" and resolved_no)
        decimal_odds = 1 / bet["entry_price"] if bet["entry_price"] > 0 else 2.0

        if won:
            pnl = bet["bet_size"] * (decimal_odds - 1)
            result = "win"
            bankroll += bet["bet_size"] * decimal_odds
            returned_capital += bet["bet_size"] * decimal_odds
        else:
            pnl = -bet["bet_size"]
            result = "loss"

        closed_count += 1
        if clv is not None:
            resolved_clvs.append(clv)
        close_bet(bet["id"], current_price, current_price, result, pnl, clv)
        logger.info(
            f"Settled #{bet['id']} [{bet['strategy_tag']}]: "
            f"{result.upper()} P&L=${pnl:+.2f} CLV={clv}"
        )

    avg_clv_closed = round(float(pd.Series(resolved_clvs).mean()), 5) if resolved_clvs else None
    return bankroll, {
        "closed_count": closed_count,
        "timeout_closed_count": timeout_closed_count,
        "returned_capital": round(returned_capital, 2),
        "avg_clv_closed": avg_clv_closed,
        "clv_resolved_count": len(resolved_clvs),
    }


def clv_report() -> dict:
    df = get_closed_bets()
    clv_data = df["clv"].dropna() if not df.empty else pd.Series()
    if clv_data.empty:
        return {"n":0,"avg_clv":None,"positive_rate":None,"clv_sharpe":None,"strategy_clv":{}}

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
