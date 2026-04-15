import logging
from enum import Enum
from execution.paper import place_paper_bet
import json
from datetime import datetime, UTC
from alerts.telegram import send_execution_alert
from execution.validator import validate_signal

logger = logging.getLogger(__name__)

def log_structured(module: str, event: str, market_id: str, status: str, details: dict):
    """
    Writes a structured JSON log to logs/execution.log
    """
    log_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "module": module,
        "event": event,
        "market_id": market_id,
        "status": status,
        "details": details
    }

    with open("logs/execution.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")


class ExecutionState(Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"

def execute_trade(signal, bet_size: float, bankroll: float, alloc: dict, current_state: ExecutionState = ExecutionState.VALIDATED) -> dict:
    """
    Executes a paper bet, wrapped in a try/catch.
    Enforces that execution only happens if state is VALIDATED.
    """
    log_structured("execution.executor", "EXECUTION_STARTED", signal.market_id, current_state.value, {"bet_size": bet_size})

    signal_dict = {
        **signal.__dict__,
        "bet_size": bet_size
    }

    if current_state != ExecutionState.VALIDATED:
        reason = f"Invalid state for execution: {current_state.value}"
        log_structured("execution.executor", "EXECUTION_BLOCKED", signal.market_id, "SKIPPED", {"reason": reason})
        alert_success = send_execution_alert(signal_dict, "SKIPPED", reason)
        if not alert_success:
            logger.error("Failed to send Telegram execution alert for market_id=%s", signal.market_id)
        return {
            "status": "failed",
            "reason": reason,
            "bet_id": None,
            "bet_size": 0.0
        }

    import time

    max_retries = 3
    timeout = 5  # Currently conceptual since place_paper_bet is synchronous local logic

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            # Here we wrap the logic; in a real network call, timeout=5 would be passed to requests.post etc.
            bet_id, actual_size = place_paper_bet(signal, bankroll)
            current_state = ExecutionState.EXECUTED
            log_structured("execution.executor", "EXECUTION_COMPLETED", signal.market_id, current_state.value, {"bet_size": actual_size, "attempt": attempt, "bet_id": bet_id})

            signal_dict["bet_size"] = actual_size
            alert_success = send_execution_alert(signal_dict, "SUCCESS", f"Trade executed on attempt {attempt}")
            if not alert_success:
                logger.error("Failed to send Telegram execution alert for market_id=%s", signal.market_id)

            return {
                "status": "success",
                "reason": "",
                "bet_id": bet_id,
                "bet_size": actual_size
            }
        except Exception as e:
            last_error = e
            log_structured("execution.executor", "RETRY_ATTEMPT", signal.market_id, "RETRYING", {"attempt": attempt, "max_retries": max_retries, "error": str(e)})
            if attempt < max_retries:
                time.sleep(1)

    current_state = ExecutionState.FAILED
    log_structured("execution.executor", "EXECUTION_FAILED", signal.market_id, current_state.value, {"error": str(last_error), "attempts": max_retries})

    alert_success = send_execution_alert(signal_dict, "FAILURE", str(last_error))
    if not alert_success:
        logger.error("Failed to send Telegram execution alert for market_id=%s", signal.market_id)

    return {
        "status": "failed",
        "reason": str(last_error),
        "bet_id": None,
        "bet_size": 0.0
    }
