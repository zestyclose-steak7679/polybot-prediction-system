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

    # Check for missing columns
    required_cols = ["liquidity", "volume", "yes_price", "active", "closed", "market_id", "question", "one_day_change"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.error(f"Missing columns in market data: {missing}")
        return pd.DataFrame()

    df = df[df["liquidity"] >= MIN_LIQUIDITY]
    df = df[df["volume"]    >= MIN_VOLUME]
    df = df[df["yes_price"] >= MIN_PRICE]
    df = df[df["yes_price"] <= MAX_PRICE]
    df = df[df["active"] == True]   # noqa: E712
    df = df[df["closed"] == False]  # noqa: E712

    after = len(df)
    logger.info(f"Filters: {before} → {after} markets (dropped {before - after} markets due to filters)")
    return df.reset_index(drop=True)


def apply_diversity_filter(df: pd.DataFrame, target_n: int = 100) -> pd.DataFrame:
    """Ensure category diversity in market selection."""
    if df.empty or "tags" not in df.columns:
        return df.head(target_n)

    sports = df[df["tags"].str.contains("sports|cricket|football|nba|nfl|ipl", case=False, na=False)]
    politics = df[df["tags"].str.contains("politics|elections", case=False, na=False)]
    crypto = df[df["tags"].str.contains("crypto|bitcoin|ethereum", case=False, na=False)]
    other = df[~df.index.isin(sports.index) & ~df.index.isin(politics.index) & ~df.index.isin(crypto.index)]

    selected = pd.concat([
        sports.head(30),
        politics.head(20),
        crypto.head(20),
        other.head(30)
    ]).drop_duplicates(subset=["market_id"]).head(target_n)

    return selected if len(selected) >= 10 else df.head(target_n)
