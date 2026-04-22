import logging
import time
from typing import Optional, Tuple
from utils.logger import get_structured_logger
from alerts.telegram import _send
from data.database import record_paper_bet
from scoring.strategies import Signal
from learning.tracker import compute_strategy_roi
from config import MAX_POSITIONS_PER_STRATEGY

logger = logging.getLogger(__name__)
struct_logger = get_structured_logger("execution.engine")

class ExecutionEngine:
    STATES = {"SIGNAL_RECEIVED", "VALIDATED", "EXECUTED", "FAILED", "SHADOW"}

    def __init__(self, bankroll: float):
        self.bankroll = bankroll

    def _determine_mode(self, strategy: str) -> str:
        """
        Check SHADOW vs ACTIVE mode.
        A signal is ACTIVE if its strategy has positive CLV in shadow mode, else SHADOW.
        """
        stats = compute_strategy_roi(strategy)

        if stats is None:
            struct_logger.info("PROMOTION", "unknown", "skipped", {"strategy": strategy, "reason": "insufficient_data"})
            return "SHADOW"

        avg_clv = stats.get("avg_clv")
        if avg_clv is None:
            struct_logger.info("PROMOTION", "unknown", "skipped", {"strategy": strategy, "reason": "no_clv_data"})
            return "SHADOW"

        if avg_clv <= -0.05:
            struct_logger.info("PROMOTION", "unknown", "skipped", {"strategy": strategy, "reason": "negative_clv", "avg_clv": avg_clv})
            return "SHADOW"

        return "ACTIVE"

    def execute_signal(self, signal: Signal, bet_size: float, kelly_raw: float, decimal_odds: float) -> Tuple[Optional[int], str]:
        market_id = signal.market_id
        struct_logger.info("SIGNAL_RECEIVED", market_id, "pending", {"strategy": signal.strategy, "bet_size": bet_size})

        if bet_size <= 0:
            struct_logger.info("VALIDATED", market_id, "skipped", {"reason": "zero_bet_size"})
            return None, "skipped"

        from data.database import get_open_bets
        open_bets = get_open_bets()
        if not open_bets.empty:
            strategy_count = len(
                open_bets[open_bets["strategy_tag"] == signal.strategy]
            )
            if strategy_count >= MAX_POSITIONS_PER_STRATEGY:
                logger.info(
                    f"STRATEGY_CAP: {signal.strategy} at "
                    f"{strategy_count} positions — skipping"
                )
                return None, "skipped"

        mode = self._determine_mode(signal.strategy)
        struct_logger.info("VALIDATED", market_id, "success", {"mode": mode})

        if mode == "SHADOW":
            signal.mode = "SHADOW"
            logger.info(
                f"SHADOW gate check | strategy: {signal.strategy} | "
                f"edge: {signal.edge} | confidence: {signal.confidence}"
            )
            struct_logger.info("SHADOW", market_id, "logged", {"strategy": signal.strategy})
            try:
                from scoring.engine import confidence_multiplier
                multiplier = confidence_multiplier(signal.confidence)
                adjusted_bet = round(bet_size * multiplier, 2)
                adjusted_bet = min(adjusted_bet, self.bankroll * 0.05)
                adjusted_bet = max(adjusted_bet, self.bankroll * 0.005)
                record_paper_bet(
                    market_id=market_id,
                    question=signal.question,
                    strategy_tag=signal.strategy,
                    side=signal.side,
                    entry_price=signal.price,
                    bet_size=adjusted_bet,
                    bankroll=self.bankroll,
                    kelly_raw=kelly_raw,
                    edge_est=signal.edge,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    mode="SHADOW"
                )
                logger.info(
                    f"SHADOW bet recorded | market: {market_id} | "
                    f"size: {adjusted_bet} | confidence: {signal.confidence}"
                )
            except Exception as e:
                logger.error(
                    f"SHADOW record FAILED | market: {market_id} | error: {e}"
                )
            return None, "shadow"

        # ACTIVE MODE
        signal.mode = "ACTIVE"
        retries = 3
        for attempt in range(1, retries + 1):
            try:
                bet_id = record_paper_bet(
                    market_id=market_id,
                    question=signal.question,
                    strategy_tag=signal.strategy,
                    side=signal.side,
                    entry_price=signal.price,
                    bet_size=bet_size,
                    bankroll=self.bankroll,
                    kelly_raw=kelly_raw,
                    edge_est=signal.edge,
                    confidence=signal.confidence,
                    reason=signal.reason,
                )
                if not bet_id:
                    logger.error(f"PAPER BET FAILED | {market_id} | bet_id={bet_id}")
                    continue

                if bet_id:
                    struct_logger.info("EXECUTED", market_id, "success", {
                        "bet_id": bet_id,
                        "bet_size": bet_size,
                        "price": signal.price,
                        "attempt": attempt
                    })
                    self._notify_outcome(signal, "success", f"Placed ${bet_size:.2f} at {signal.price:.2f}")
                    return bet_id, "success"
            except Exception as e:
                struct_logger.warning("EXECUTION_ATTEMPT", market_id, "failed", {
                    "attempt": attempt,
                    "error": str(e)
                })
                time.sleep(1) # Backoff

        struct_logger.error("FAILED", market_id, "failed", {"reason": "max_retries_exceeded"})
        self._notify_outcome(signal, "failed", "Execution failed after retries")
        return None, "failed"

    def _notify_outcome(self, signal: Signal, status: str, details: str):
        text = (
            f"🚀 <b>Execution Update</b>\n"
            f"Market: {signal.market_id}\n"
            f"Strategy: {signal.strategy}\n"
            f"Status: {status.upper()}\n"
            f"Details: {details}"
        )
        _send(text)
