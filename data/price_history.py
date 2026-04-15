"""
data/price_history.py
─────────────────────────────────────────────────────────────
Stores price snapshots per market per cycle.
This is the foundation for real time-series features.

Every time we fetch markets, we log the price.
After N cycles we have a price series → momentum, reversion, etc.
"""

import sqlite3
import pandas as pd
from datetime import UTC, datetime, timedelta
from config import DB_PATH
import logging

logger = logging.getLogger(__name__)


def _conn():
    is_uri = isinstance(DB_PATH, str) and DB_PATH.startswith("file:")
    con = sqlite3.connect(DB_PATH, uri=is_uri)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    return con


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def init_price_history():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id   TEXT NOT NULL,
                yes_price   REAL,
                volume      REAL,
                liquidity   REAL,
                logged_at   TEXT NOT NULL
            )
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_ph_market ON price_history(market_id, logged_at)"
        )
        con.commit()


def log_prices(df: pd.DataFrame):
    """Log yes_price for every market in the filtered DataFrame."""
    if df.empty:
        return

    now = _utc_now().isoformat()

    # Handle duplicates gracefully by grouping
    df_dedup = df.groupby('market_id').last().reset_index()

    rows = [
        (row["market_id"], row["yes_price"],
         row.get("volume", 0), row.get("liquidity", 0), now)
        for _, row in df_dedup.iterrows()
    ]
    try:
        with _conn() as con:
            con.executemany(
                "INSERT INTO price_history (market_id, yes_price, volume, liquidity, logged_at) VALUES (?,?,?,?,?)",
                rows,
            )
            con.commit()
        logger.debug(f"Logged {len(rows)} price snapshots")
    except Exception as e:
        logger.error(f"Error logging prices: {e}")


def get_history(market_id: str, last_n: int = 20) -> pd.DataFrame:
    """
    Return last N price snapshots for a market, oldest first.
    Returns empty DataFrame if insufficient data.
    """
    try:
        with _conn() as con:
            df = pd.read_sql(
                """SELECT yes_price, volume, liquidity, logged_at
                   FROM price_history
                   WHERE market_id = ?
                   ORDER BY logged_at DESC
                   LIMIT ?""",
                con,
                params=(market_id, last_n),
            )
        if df.empty:
            return pd.DataFrame()
        return df.iloc[::-1].reset_index(drop=True)   # oldest first
    except Exception as e:
        logger.error(f"Failed to get price history: {e}")
        return pd.DataFrame()


def purge_old_history(days: int = 30):
    """Keep DB lean — remove price history older than N days."""
    cutoff = (_utc_now() - timedelta(days=days)).isoformat()
    with _conn() as con:
        con.execute("DELETE FROM price_history WHERE logged_at < ?", (cutoff,))
        con.commit()

def get_history_bulk(market_ids: list[str], last_n: int = 20) -> dict[str, pd.DataFrame]:
    """
    Return last N price snapshots for a list of markets in bulk.
    Returns a dictionary mapping market_id -> DataFrame of snapshots (oldest first).
    """
    if not market_ids:
        return {}

    res = {m: pd.DataFrame() for m in market_ids}
    batch_size = 900

    for i in range(0, len(market_ids), batch_size):
        batch = list(market_ids)[i:i+batch_size]
        placeholders = ",".join(["?"] * len(batch))

        try:
            with _conn() as con:
                df = pd.read_sql(
                    f"""
                    SELECT market_id, yes_price, volume, liquidity, logged_at
                    FROM (
                        SELECT market_id, yes_price, volume, liquidity, logged_at,
                               ROW_NUMBER() OVER(PARTITION BY market_id ORDER BY logged_at DESC) as rn
                        FROM price_history
                        WHERE market_id IN ({placeholders})
                    )
                    WHERE rn <= ?
                    ORDER BY market_id, logged_at ASC
                    """,
                    con,
                    params=(*batch, last_n)
                )

            if df.empty:
                continue

            for m, group in df.groupby("market_id"):
                res[m] = group.drop(columns=["market_id"]).reset_index(drop=True)

        except Exception as e:
            logger.warning(f"Bulk fetch failed: {e}. Falling back to sequential.")
            for m in batch:
                res[m] = get_history(m, last_n)

    return res
