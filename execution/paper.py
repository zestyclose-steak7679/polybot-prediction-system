"""
execution/paper.py
Records paper bets and settles resolved markets.
"""

import logging
from scoring.strategies import Signal
from scoring.engine import kelly_bet
from risk.controls import clamp_bet_size
from data.database import record_paper_bet, get_open_bets, close_bet, get_pnl_summary
from data.markets import fetch_markets
from tracking.clv import check_mid_prices

logger = logging.getLogger(__name__)


def place_paper_bet(signal: Signal, bankroll: float) -> tuple[int | None, float]:
    """
    Record a paper bet from a Signal.
    Returns (bet_id, actual_bet_size).
    """
    decimal_odds = round(1 / signal.price, 4) if signal.price > 0 else 0
    kelly        = kelly_bet(bankroll, signal.confidence, decimal_odds)
    bet_size     = clamp_bet_size(kelly["bet_size"], bankroll)

    if bet_size <= 0:
        return None, 0.0

    bet_id = record_paper_bet(
        market_id    = signal.market_id,
        question     = signal.question,
        strategy_tag = signal.strategy,
        side         = signal.side,
        entry_price  = signal.price,
        bet_size     = bet_size,
        bankroll     = bankroll,
        kelly_raw    = kelly["kelly_raw"],
        edge_est     = signal.edge,
        confidence   = signal.confidence,
        reason       = signal.reason,
    )

    logger.info(
        f"Paper bet #{bet_id} | {signal.strategy} | {signal.side} "
        f"'{signal.question[:50]}' @ {signal.price:.3f} — ${bet_size:.2f}"
    )
    return bet_id, bet_size


def settle_open_bets(bankroll: float) -> float:
    """
    Check open paper bets against current prices.
    Settle if market has resolved (price >= 0.95 or <= 0.05).
    Returns updated bankroll.
    """
    check_mid_prices()

    open_bets = get_open_bets()
    if open_bets.empty:
        return bankroll

    current_markets = fetch_markets()

    for _, bet in open_bets.iterrows():
        if current_markets.empty:
            break

        market_row = current_markets[current_markets["market_id"] == bet["market_id"]]
        if market_row.empty:
            continue

        row           = market_row.iloc[0]
        resolved_yes  = row["yes_price"] >= 0.95
        resolved_no   = row["yes_price"] <= 0.05

        if not (resolved_yes or resolved_no):
            continue

        won = (
            (bet["side"] == "YES" and resolved_yes) or
            (bet["side"] == "NO"  and resolved_no)
        )

        decimal_odds = 1 / bet["entry_price"] if bet["entry_price"] > 0 else 2.0

        if won:
            pnl    = bet["bet_size"] * (decimal_odds - 1)
            result = "win"
            bankroll += bet["bet_size"] * decimal_odds   # stake + profit
        else:
            pnl    = -bet["bet_size"]
            result = "loss"
            # stake already deducted at placement

        current_price = row["yes_price"] if bet["side"] == "YES" else row["no_price"]
        close_bet(bet["id"], current_price, result, pnl)
        logger.info(f"Settled bet #{bet['id']} [{bet['strategy_tag']}]: {result.upper()} | P&L ${pnl:+.2f}")

    return bankroll


def get_stats() -> dict:
    return get_pnl_summary()
