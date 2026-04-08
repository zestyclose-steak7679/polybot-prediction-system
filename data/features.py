"""
data/features.py
─────────────────────────────────────────────────────────────
Builds real features from market data + price history.

Feature groups:
  momentum    — direction and strength of recent moves
  reversion   — distance from recent mean (overextension)
  volume      — volume spike vs expected baseline
  liquidity   — illiquidity flags (easier mispricing)
  time        — proximity to resolution (volatility zone)
  market      — raw market state

These feed the ML model when we have enough outcome data,
or supplement heuristic scoring in the interim.
"""

import numpy as np
import pandas as pd
from datetime import UTC, datetime
import logging

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ── Momentum ──────────────────────────────────────────────

def momentum_features(prices: np.ndarray) -> dict:
    """
    Requires at least 3 price snapshots.
    Returns short/medium/long momentum and ratio.

    Interpretation:
      momentum_short > 0 → recent upward tick
      momentum_ratio > 1 → recent move accelerating (chase risk)
      momentum_ratio < 0 → reversal starting
    """
    if len(prices) < 3:
        return {k: 0.0 for k in [
            "mom_short", "mom_medium", "mom_long", "mom_ratio",
            "mom_acceleration"
        ]}

    short  = float(prices[-1] - prices[-2])
    medium = float(prices[-1] - prices[-3]) if len(prices) >= 3 else short
    long_  = float(prices[-1] - prices[0])

    ratio = short / (abs(long_) + 1e-6)
    accel = float(short - (prices[-2] - prices[-3]))

    return {
        "mom_short":       round(short, 5),
        "mom_medium":      round(medium, 5),
        "mom_long":        round(long_, 5),
        "mom_ratio":       round(ratio, 4),
        "mom_acceleration": round(float(accel), 5),
    }


# ── Mean Reversion ────────────────────────────────────────

def reversion_features(prices: np.ndarray) -> dict:
    """
    Distance from recent mean → overextension → potential snap-back.

    Interpretation:
      distance_from_mean > 0.05 → price well above mean (reversion candidate)
      distance_from_mean < -0.05 → price well below mean
    """
    if len(prices) < 3:
        return {"distance_from_mean": 0.0, "std_dev": 0.0, "z_score": 0.0}

    mean = float(np.mean(prices))
    std  = float(np.std(prices)) + 1e-6
    dist = float(prices[-1] - mean)

    return {
        "distance_from_mean": round(dist, 5),
        "std_dev":            round(std, 5),
        "z_score":            round(dist / std, 3),
    }


# ── Volume ────────────────────────────────────────────────

def volume_features(volumes: np.ndarray) -> dict:
    """
    Volume spike = unusual activity = informed traders.
    spike_ratio > 2 = 2x normal volume → strong signal.
    """
    if len(volumes) < 2:
        return {"vol_spike_ratio": 1.0, "vol_trend": 0.0}

    recent   = float(volumes[-1])
    baseline = float(np.mean(volumes[:-1])) + 1e-6
    ratio    = recent / baseline
    trend    = float(volumes[-1] - volumes[0])

    return {
        "vol_spike_ratio": round(ratio, 3),
        "vol_trend":       round(trend, 2),
    }


# ── Liquidity ─────────────────────────────────────────────

def liquidity_features(liquidity: float) -> dict:
    """
    Low liquidity = easier mispricing, but harder to exit.
    illiquid_flag = 1 when < $10k liquidity.
    """
    return {
        "liquidity_log":   round(np.log10(max(liquidity, 1)), 3),
        "illiquid_flag":   1 if liquidity < 10_000 else 0,
        "very_illiquid":   1 if liquidity < 2_000 else 0,
    }


# ── Time to Resolution ────────────────────────────────────

def time_features(end_date: str) -> dict:
    """
    As resolution approaches:
      - Markets get more volatile (info arrives)
      - Inefficiencies spike 24-48h before close
      - Very close markets (< 6h) → avoid (thin, noisy)
    """
    try:
        if not end_date:
            return {"hours_left": 999.0, "near_resolution": 0, "danger_zone": 0}

        end = datetime.fromisoformat(end_date.replace("Z", "+00:00").split("+")[0])
        now = _utc_now()
        hours = max((end - now).total_seconds() / 3600, 0)

        return {
            "hours_left":      round(hours, 1),
            "near_resolution": 1 if hours < 48 else 0,   # opportunity zone
            "danger_zone":     1 if hours < 6 else 0,    # too noisy
        }
    except Exception:
        return {"hours_left": 999.0, "near_resolution": 0, "danger_zone": 0}


# ── Master builder ────────────────────────────────────────

# Columns the ML model expects (in order)
FEATURE_COLUMNS = [
    "price",
    "mom_short", "mom_medium", "mom_long", "mom_ratio", "mom_acceleration",
    "distance_from_mean", "std_dev", "z_score",
    "vol_spike_ratio", "vol_trend",
    "liquidity_log", "illiquid_flag", "very_illiquid",
    "hours_left", "near_resolution",
    # NOTE: danger_zone excluded — not a feature for betting ON a market
]


def build_features(market_row: pd.Series, history: pd.DataFrame) -> dict | None:
    """
    Build full feature dict for a market.
    Returns None if insufficient data for reliable features.
    Minimum: 3 price snapshots.
    """
    prices  = history["yes_price"].values if not history.empty else np.array([])
    volumes = history["volume"].values    if not history.empty and "volume" in history else np.array([])

    if len(prices) < 3:
        return None   # not enough history yet

    feats = {
        "price": float(market_row["yes_price"]),
    }
    feats.update(momentum_features(prices))
    feats.update(reversion_features(prices))
    feats.update(volume_features(volumes))
    feats.update(liquidity_features(float(market_row.get("liquidity", 0))))
    feats.update(time_features(str(market_row.get("end_date", ""))))

    return feats


def features_to_array(feats: dict) -> np.ndarray:
    """Convert feature dict to numpy array in FEATURE_COLUMNS order."""
    return np.array([feats.get(col, 0.0) for col in FEATURE_COLUMNS], dtype=float)
