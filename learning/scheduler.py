"""
learning/scheduler.py
─────────────────────────────────────────────────────────────
Controls when the ML model retrains and logs feature importance.

Retrain logic:
  - Every 6 hours (or N cycles)
  - Only if we have MIN_TRAIN_BETS new closed bets since last train
  - Logs feature importance so you can see what the model learned
"""

import sqlite3
import logging
from pathlib import Path
from datetime import UTC, datetime, timedelta
from config import DB_PATH

logger = logging.getLogger(__name__)

RETRAIN_INTERVAL_HOURS = 6
LAST_TRAIN_FILE = "last_train.txt"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load_last_train() -> datetime | None:
    try:
        ts = Path(LAST_TRAIN_FILE).read_text().strip()
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _save_last_train():
    Path(LAST_TRAIN_FILE).write_text(_utc_now().isoformat())


def should_retrain() -> bool:
    last = _load_last_train()
    if last is None:
        return True   # never trained
    return _utc_now() - last > timedelta(hours=RETRAIN_INTERVAL_HOURS)


def run_retrain_if_due(model) -> bool:
    """
    Attempt retraining if scheduled.
    Returns True if model was retrained.
    """
    if not should_retrain():
        return False

    logger.info("Retrain scheduled — attempting...")
    success = model.train()

    if success:
        _save_last_train()
        logger.info("Retrain complete.")

        # Log feature importance
        fi = model.feature_importance()
        if fi:
            top = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:5]
            logger.info("Top 5 features: " + " | ".join(f"{k}={v:.3f}" for k, v in top))
    else:
        logger.info("Retrain skipped (insufficient data or fallback mode).")

    return success
