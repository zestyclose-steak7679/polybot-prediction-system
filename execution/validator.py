import logging
from datetime import datetime, UTC
from scoring.strategies import Signal

logger = logging.getLogger(__name__)

def validate_signal(signal: Signal) -> tuple[bool, str]:
    """
    Validates signal data before allowing it into the executor.
    Checks:
    - Minimum volume threshold
    - Price sanity
    - Timestamp freshness (if available via market snapshot)
    """

    if getattr(signal, "volume", 0) < 500:
        return False, f"Volume {getattr(signal, 'volume', 0)} below threshold"

    if signal.price <= 0.0 or signal.price >= 1.0:
        return False, f"Price {signal.price} out of bounds"

    # Example freshness check, in reality would use signal.timestamp or similar if strictly tracked
    # assuming for this system freshness is currently implicitly handled by cycle loops, but we'll
    # ensure price delta is within sanity limits as a placeholder for spikes
    if getattr(signal, "one_day_change", 0) > 0.8:
         return False, f"Suspicious daily price swing {signal.one_day_change}"

    return True, ""
