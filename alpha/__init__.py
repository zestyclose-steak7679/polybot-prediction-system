"""Alpha shadow layer for public-API market inefficiency research."""

from .evaluator import (
    ALPHA_MIN_PROMOTION_SAMPLES,
    ALPHA_POSITIVE_RATE_THRESHOLD,
    evaluate_alpha_modules,
)
from .signals import AlphaSignal, aggregate_alpha_signals, build_alpha_signals
from .tracker import resolve_alpha_signals

__all__ = [
    "ALPHA_MIN_PROMOTION_SAMPLES",
    "ALPHA_POSITIVE_RATE_THRESHOLD",
    "AlphaSignal",
    "aggregate_alpha_signals",
    "build_alpha_signals",
    "evaluate_alpha_modules",
    "resolve_alpha_signals",
]
