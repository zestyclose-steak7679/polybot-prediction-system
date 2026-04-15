"""
scoring/filters.py
Hard filters — markets that fail these are dropped before scoring.
"""

import pandas as pd
import logging
from datetime import UTC, datetime
from config import MIN_LIQUIDITY, MIN_VOLUME, MIN_PRICE, MAX_PRICE
from utils.logger import get_structured_logger
from data.price_history import get_history_bulk

logger = logging.getLogger(__name__)
struct_logger = get_structured_logger("scoring.filters")

def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

def _is_stale(end_date_str: str) -> bool:
    if not end_date_str:
        return False
    try:
        dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
        if dt.tzinfo is not None:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt < _utc_now()
    except Exception:
        return False


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

    # Validation Layer
    valid_indices = []

    market_ids = df["market_id"].tolist()
    histories = get_history_bulk(market_ids, last_n=10)

    for idx, row in df.iterrows():
        market_id = row["market_id"]

        # 1. Stale market check
        if _is_stale(row.get("end_date")):
            struct_logger.warning("data_validation", market_id, "skipped", {"reason": "stale_market"})
            continue

        # 2. Price continuity check
        history_df = histories.get(market_id)
        if history_df is not None and not history_df.empty:
            current_price = row["yes_price"]
            prev_price = history_df["yes_price"].iloc[-1]
            price_change = abs(current_price - prev_price)

            if len(history_df) >= 2:
                # Calculate rolling std over available history
                rolling_std = history_df["yes_price"].std()
                if pd.isna(rolling_std):
                    rolling_std = 0.0
            else:
                rolling_std = 0.0

            if price_change > max(0.15, 3 * rolling_std):
                struct_logger.warning("data_validation", market_id, "skipped", {
                    "reason": "price_jump",
                    "price_change": price_change,
                    "rolling_std": rolling_std
                })
                continue

        valid_indices.append(idx)

    df = df.loc[valid_indices]

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
