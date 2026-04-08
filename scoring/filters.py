"""
scoring/filters.py
Hard filters — markets that fail these are dropped before scoring.
"""

import pandas as pd
import logging
from config import MIN_LIQUIDITY, MIN_VOLUME, MIN_PRICE, MAX_PRICE

logger = logging.getLogger(__name__)


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop markets that are:
      - Below min liquidity / volume
      - Priced too close to 0 or 1 (near-resolved, no edge possible)
      - Already closed / inactive
    """
    if df.empty:
        return df

    before = len(df)

    df = df[df["liquidity"] >= MIN_LIQUIDITY]
    df = df[df["volume"]    >= MIN_VOLUME]
    df = df[df["yes_price"] >= MIN_PRICE]
    df = df[df["yes_price"] <= MAX_PRICE]
    df = df[df["active"] == True]   # noqa: E712
    df = df[df["closed"] == False]  # noqa: E712

    after = len(df)
    logger.info(f"Filters: {before} → {after} markets")
    return df.reset_index(drop=True)
