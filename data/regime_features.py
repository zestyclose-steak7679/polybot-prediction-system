"""data/regime_features.py — extract market microstructure regime signals"""
import numpy as np
import pandas as pd
import logging
logger = logging.getLogger(__name__)

def compute_regime_features(price_series: np.ndarray, volume_series: np.ndarray = None) -> dict:
    """
    Requires at least 5 price points.
    Returns regime features used by RegimeModel.
    """
    if len(price_series) < 5:
        return _empty_regime()

    returns = np.diff(price_series)

    # Volatility: std of recent returns
    volatility = float(np.std(returns[-min(20, len(returns)):]))

    # Trend: mean of recent returns (direction)
    trend_strength = float(np.mean(returns[-min(10, len(returns)):]))

    # Autocorrelation: +ve = trending, -ve = mean-reverting
    if len(returns) >= 4:
        autocorr = float(np.corrcoef(returns[:-1], returns[1:])[0, 1])
    else:
        autocorr = 0.0
    if np.isnan(autocorr):
        autocorr = 0.0

    # Volume spike
    if volume_series is not None and len(volume_series) >= 5:
        vol_spike = float(volume_series[-1] / (np.mean(volume_series[-min(20,len(volume_series)):-1]) + 1e-6))
    else:
        vol_spike = 1.0

    # Price range / normalised volatility
    price_range = float((price_series.max() - price_series.min()) / (np.mean(price_series) + 1e-6))

    return {
        "volatility":      round(volatility, 6),
        "trend_strength":  round(trend_strength, 6),
        "autocorr":        round(autocorr, 4),
        "vol_spike":       round(vol_spike, 3),
        "price_range":     round(price_range, 4),
    }

def _empty_regime():
    return {"volatility":0.0,"trend_strength":0.0,"autocorr":0.0,"vol_spike":1.0,"price_range":0.0}
