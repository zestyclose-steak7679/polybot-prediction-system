import logging
from config import MAX_BET_PCT

logger = logging.getLogger(__name__)

def calculate_position_size(edge: float, confidence: float, bankroll: float) -> float:
    """
    Day 15: Position Sizing Engine
    Base sizing rule: size ∝ edge × confidence
    """
    raw_size = bankroll * edge * confidence

    # Cap: max % per trade
    max_cap = bankroll * MAX_BET_PCT
    size = min(raw_size, max_cap)
    size = round(max(0.0, size), 2)

    logger.info(f"SIGNAL_SIZED: edge={edge:.3f}, conf={confidence:.2f}, bankroll=${bankroll:.2f} -> size=${size:.2f}")
    return size
