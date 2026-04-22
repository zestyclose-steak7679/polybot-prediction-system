"""strategies/router.py — maps market regime to active strategy set"""

REGIME_STRATEGY_MAP = {
    "trending":       ["momentum"],
    "mean_reverting": ["reversal", "momentum"],
    "volatile":       ["reversal", "volume_spike"],
    "illiquid_spike": ["volume_spike", "momentum"],
    "neutral":        ["momentum", "reversal", "volume_spike"],
}

class StrategyRouter:
    def select(self, regime: str, available: list) -> list:
        """Return subset of available strategy names for this regime."""
        allowed = set(REGIME_STRATEGY_MAP.get(regime, list(REGIME_STRATEGY_MAP["neutral"])))
        selected = [s for s in available if s in allowed]
        # failsafe: never return empty
        return selected if selected else available
