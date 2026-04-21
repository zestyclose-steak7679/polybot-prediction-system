"""
scoring/strategies.py
─────────────────────────────────────────────────────────────
Three competing strategies. Each returns a Signal or None.

These are REALISTIC heuristics that detect specific market
conditions, NOT fake ML with guaranteed accuracy.

Strategy | Logic                            | When it works
─────────────────────────────────────────────────────────────
momentum  | follow 24h price direction       | trending markets
reversal  | fade large moves                 | overreaction / news shock
vol_spike | follow unusual volume            | informed-trader activity
─────────────────────────────────────────────────────────────
"""

from dataclasses import dataclass
from typing import Any, Mapping
import pandas as pd
import numpy as np
import logging
from config import (
    MOMENTUM_THRESHOLD,
    REVERSAL_THRESHOLD,
    VOLUME_SPIKE_RATIO,
    EDGE_THRESHOLD,
    MIN_VOLUME,
)
from utils.logger import get_structured_logger

logger = logging.getLogger(__name__)
struct_logger = get_structured_logger("scoring.strategies")


@dataclass
class Signal:
    strategy:    str
    market_id:   str
    question:    str
    side:        str          # "YES" or "NO"
    price:       float        # price of the side we're betting
    confidence:  float        # 0.0 – 1.0 (our estimated true prob)
    edge:        float        # confidence - price
    reason:      str          # human-readable explanation
    tags:        str
    liquidity:   float
    volume:      float
    one_day_change: float
    end_date:    str
    mode:        str = "SHADOW"


# ── Strategy 1: Momentum ──────────────────────────────────
# Hypothesis: markets that have moved X% in 24h continue short-term.
# Evidence basis: price discovery lag — not all info is priced instantly.
# Failure mode: chasing after a move that's already exhausted.


def momentum_strategy(row: Mapping[str, Any]) -> Signal | None:
    if "one_day_change" not in row or row["one_day_change"] is None:
        return None

    move = row["one_day_change"]   # positive = YES moved up

    if abs(move) < MOMENTUM_THRESHOLD:
        return None

    if move > 0:
        # YES has been rising → bet YES
        side  = "YES"
        price = row["yes_price"]
        # Confidence = market price + small momentum premium
        confidence = min(price + abs(move) * 0.3, 0.95)
    else:
        # YES has been falling → bet NO
        side  = "NO"
        price = row["no_price"]
        confidence = min(price + abs(move) * 0.3, 0.95)

    edge = confidence - price
    if edge < EDGE_THRESHOLD:
        if row.get("one_day_change", 0) > 0.03 and row.get("volume", 0) > MIN_VOLUME:
            confidence = min(price + EDGE_THRESHOLD, 0.95)
            edge = EDGE_THRESHOLD
        else:
            return None

    logger.info(f"SIGNAL_GENERATED: on {row['market_id']} for {side}")
    return Signal(
        strategy     = "momentum",
        market_id    = row["market_id"],
        question     = row["question"],
        side         = side,
        price        = round(price, 4),
        confidence   = round(confidence, 4),
        edge         = round(edge, 4),
        reason       = f"24h move {move*100:+.1f}% — following direction",
        tags         = row["tags"],
        liquidity    = row["liquidity"],
        volume       = row["volume"],
        one_day_change = move,
        end_date     = row["end_date"],
    )


# ── Strategy 2: Reversal ──────────────────────────────────
# Hypothesis: very large moves (>12%) are often overreactions.
# Bet AGAINST the direction after a big spike.
# Evidence basis: mean reversion in prediction markets post-news.
# Failure mode: genuine resolution events (when market IS right).


def reversal_strategy(row: Mapping[str, Any]) -> Signal | None:
    if "one_day_change" not in row or row["one_day_change"] is None:
        return None

    move = row["one_day_change"]

    if abs(move) < REVERSAL_THRESHOLD:
        return None

    # Avoid markets priced very close to resolution (>85% or <15%)
    if row["yes_price"] > 0.85 or row["yes_price"] < 0.15:
        return None

    if move > 0:
        # YES spiked hard → bet NO (fade the spike)
        side  = "NO"
        price = row["no_price"]
        confidence = min(price + abs(move) * 0.25, 0.90)
    else:
        # YES dumped hard → bet YES (fade the dump)
        side  = "YES"
        price = row["yes_price"]
        confidence = min(price + abs(move) * 0.25, 0.90)

    edge = confidence - price
    if edge < EDGE_THRESHOLD:
        return None

    logger.info(f"SIGNAL_GENERATED: on {row['market_id']} for {side}")
    return Signal(
        strategy     = "reversal",
        market_id    = row["market_id"],
        question     = row["question"],
        side         = side,
        price        = round(price, 4),
        confidence   = round(confidence, 4),
        edge         = round(edge, 4),
        reason       = f"Large move {move*100:+.1f}% — fading overreaction",
        tags         = row["tags"],
        liquidity    = row["liquidity"],
        volume       = row["volume"],
        one_day_change = move,
        end_date     = row["end_date"],
    )


# ── Strategy 3: Volume Spike ──────────────────────────────
# Hypothesis: volume >> what liquidity would predict = informed traders.
# Follow the informed traders.
# Evidence basis: volume as a proxy for information arrival.
# Failure mode: volume from bots or market makers, not informative.


def volume_spike_strategy(row: Mapping[str, Any]) -> Signal | None:
    if "liquidity" not in row or "volume" not in row:
        return None

    liquidity = row["liquidity"]
    volume    = row["volume"]

    if liquidity <= 0:
        return None

    # Expected volume is roughly proportional to liquidity
    # (this is a rough proxy — real calibration comes with data)
    expected_volume = liquidity * 1.5 + 1e-6
    ratio = volume / expected_volume

    if ratio < VOLUME_SPIKE_RATIO:
        return None

    # Avoid near-resolved markets (no edge possible)
    yes_price = row.get("yes_price", 0.5)
    if yes_price < 0.12 or yes_price > 0.88:
        return None

    # With a volume spike, follow the price direction
    move  = row["one_day_change"]
    if move >= 0:
        side  = "YES"
        price = row["yes_price"]
    else:
        side  = "NO"
        price = row["no_price"]

    # Confidence: more volume → higher confidence adjustment
    vol_boost  = min(np.log10(ratio) * 0.06, 0.08)
    confidence = min(price + vol_boost, 0.92)

    # Reduce confidence for low-tension markets
    tension = 1.0 - abs(yes_price - 0.5) * 2
    if tension < 0.4:  # price outside 0.20-0.80 range
        confidence = min(confidence, 0.65)
        edge = confidence - price
        if edge < EDGE_THRESHOLD:
            return None

    edge       = confidence - price

    if edge < EDGE_THRESHOLD:
        if row.get("one_day_change", 0) > 0.03 and row.get("volume", 0) > MIN_VOLUME:
            confidence = min(price + EDGE_THRESHOLD, 0.95)
            edge = EDGE_THRESHOLD
        else:
            return None

    logger.info(f"SIGNAL_GENERATED: on {row['market_id']} for {side}")
    return Signal(
        strategy     = "volume_spike",
        market_id    = row["market_id"],
        question     = row["question"],
        side         = side,
        price        = round(price, 4),
        confidence   = round(confidence, 4),
        edge         = round(edge, 4),
        reason       = f"Volume {ratio:.1f}x expected — informed activity detected",
        tags         = row["tags"],
        liquidity    = row["liquidity"],
        volume       = row["volume"],
        one_day_change = move,
        end_date     = row["end_date"],
    )


# ── Run all strategies on a DataFrame ─────────────────────

STRATEGY_MAP = {
    "momentum":    momentum_strategy,
    "reversal":    reversal_strategy,
    "volume_spike": volume_spike_strategy,
}


def run_strategies(df: pd.DataFrame, active: list[str]) -> list[Signal]:
    """
    Run all active strategies across all markets.
    Returns a flat list of Signals, deduplicated by (market_id, side).
    """
    signals = []
    seen    = set()   # (market_id, side) pairs to avoid duplicate alerts

    for row in df.to_dict('records'):
        for name in active:
            fn = STRATEGY_MAP.get(name)
            if fn is None:
                continue
            try:
                sig = fn(row)
            except Exception as e:
                logger.debug(f"Strategy {name} error on {row.get('market_id')}: {e}")
                continue

            if sig is None:
                continue

            key = (sig.market_id, sig.side)
            if key in seen:
                continue

            seen.add(key)
            signals.append(sig)

    # Sort by edge descending
    signals.sort(key=lambda s: s.edge, reverse=True)
    logger.info(f"Strategies produced {len(signals)} signals")
    for sig in signals:
        struct_logger.info("signal_generation", sig.market_id, "success", {"strategy": sig.strategy, "side": sig.side, "edge": sig.edge})
    return signals
