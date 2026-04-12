"""
learning/drift_monitor.py
─────────────────────────────────────────────────
Detects when feature distributions shift significantly.
Compares today's feature means vs 7-day baseline.
Returns confidence multiplier (1.0 = normal, <1.0 = drift detected).

Used by main.py to reduce position sizes when features drift.
"""
import sqlite3, json, logging
import numpy as np
import pandas as pd
from config import DB_PATH

logger = logging.getLogger(__name__)
DRIFT_THRESHOLD = 0.30   # 30% change in feature mean triggers warning


def compute_edge_decay(recent_window: int = 10, historical_window: int = 30) -> dict:
    """
    Compare recent CLV to historical CLV.
    If recent_clv < historical_clv * 0.7 → edge decaying, reduce sizes.
    Returns dict with decay_factor (0.5-1.0) and status string.
    """
    try:
        from data.database import get_closed_bets
        bets = get_closed_bets()
        if len(bets) < recent_window + 5:
            return {"decay_factor": 1.0, "status": "insufficient_data"}

        bets_sorted = bets.sort_values("placed_at", ascending=False)
        recent_clv = bets_sorted.head(recent_window)["clv"].mean()
        historical_clv = bets_sorted.tail(historical_window)["clv"].mean()

        if historical_clv <= 0:
            return {"decay_factor": 1.0, "status": "no_historical_edge"}

        ratio = recent_clv / (historical_clv + 1e-6)

        if ratio < 0.5:
            decay_factor = 0.5
            status = "severe_decay"
        elif ratio < 0.7:
            decay_factor = 0.7
            status = "moderate_decay"
        elif ratio < 0.9:
            decay_factor = 0.85
            status = "mild_decay"
        else:
            decay_factor = 1.0
            status = "healthy"

        return {
            "decay_factor": decay_factor,
            "status": status,
            "recent_clv": round(recent_clv, 4),
            "historical_clv": round(historical_clv, 4),
            "ratio": round(ratio, 4)
        }
    except Exception as e:
        logger.error("Edge decay check failed: %s", e)
        return {"decay_factor": 1.0, "status": "error"}


def _load_snapshots(days: int = 7) -> pd.DataFrame:
    try:
        with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
            df = pd.read_sql(
                f"""SELECT features_json, snapshot_at FROM feature_snapshots
                    WHERE snapshot_at >= datetime('now', '-{days} days')
                    ORDER BY snapshot_at DESC LIMIT 2000""",
                con)
        return df
    except Exception:
        return pd.DataFrame()


def _parse_snapshots(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        try:
            feats = json.loads(r["features_json"])
            feats["snapshot_at"] = r["snapshot_at"]
            rows.append(feats)
        except Exception:
            pass
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def compute_drift_multiplier() -> tuple[float, dict]:
    """
    Returns (multiplier, drift_report).
    multiplier 1.0 = no drift, 0.5 = heavy drift (reduce sizes).
    """
    df = _load_snapshots(days=7)
    if df.empty:
        return 1.0, {"status": "insufficient_data"}

    parsed = _parse_snapshots(df)
    if parsed.empty or len(parsed) < 10:
        return 1.0, {"status": "insufficient_data"}

    numeric = parsed.select_dtypes(include=[np.number])
    if numeric.empty:
        return 1.0, {"status": "insufficient_data"}

    numeric["snapshot_at"] = parsed["snapshot_at"]
    today_mask  = pd.to_datetime(numeric["snapshot_at"], utc=True) >= pd.Timestamp.utcnow() - pd.Timedelta(hours=24)
    today_df    = numeric[today_mask].drop(columns=["snapshot_at"])
    history_df  = numeric[~today_mask].drop(columns=["snapshot_at"])

    if today_df.empty or history_df.empty:
        return 1.0, {"status": "insufficient_data"}

    drift_report = {}
    n_drifted = 0

    for col in today_df.columns:
        hist_mean = float(history_df[col].mean())
        today_mean = float(today_df[col].mean())
        if abs(hist_mean) < 1e-9:
            continue
        pct_change = abs(today_mean - hist_mean) / (abs(hist_mean) + 1e-9)
        drift_report[col] = round(pct_change, 3)
        if pct_change > DRIFT_THRESHOLD:
            n_drifted += 1

    total_features = max(len(drift_report), 1)
    drift_fraction = n_drifted / total_features

    if drift_fraction > 0.5:
        multiplier = 0.5
        logger.warning(f"Heavy feature drift: {n_drifted}/{total_features} features shifted >30%")
    elif drift_fraction > 0.25:
        multiplier = 0.75
        logger.info(f"Moderate feature drift: {n_drifted}/{total_features} features")
    else:
        multiplier = 1.0

    multiplier = float(np.clip(multiplier, 0.0, 1.0))

    top_drifted = sorted(drift_report.items(), key=lambda x: x[1], reverse=True)[:5]
    if top_drifted:
        logger.info("Top drifted features: " + " | ".join(f"{k}={v:.2f}" for k,v in top_drifted))

    return multiplier, drift_report
