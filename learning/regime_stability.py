"""
learning/regime_stability.py
Prevents rapid regime switching by requiring 3 consecutive cycles
in new regime before committing to it.
"""
from pathlib import Path
import json, logging
logger = logging.getLogger(__name__)

STABILITY_FILE    = "regime_state.json"
CONFIRM_CYCLES    = 3   # cycles in new regime before switching


def _load() -> dict:
    try:
        return json.loads(Path(STABILITY_FILE).read_text())
    except Exception:
        return {"confirmed": "neutral", "candidate": None, "count": 0}


def _save(state: dict):
    Path(STABILITY_FILE).write_text(json.dumps(state))


def get_stable_regime(raw_regime: str) -> str:
    """
    Returns confirmed regime.
    Only switches after CONFIRM_CYCLES consecutive signals of same regime.
    """
    state = _load()

    if raw_regime == state["confirmed"]:
        state["candidate"] = None
        state["count"]     = 0
    elif raw_regime == state["candidate"]:
        state["count"] += 1
        if state["count"] >= CONFIRM_CYCLES:
            logger.info(f"Regime confirmed: {state['confirmed']} → {raw_regime}")
            state["confirmed"] = raw_regime
            state["candidate"] = None
            state["count"]     = 0
    else:
        state["candidate"] = raw_regime
        state["count"]     = 1

    _save(state)
    return state["confirmed"]
