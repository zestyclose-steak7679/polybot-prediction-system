"""learning/online_trainer.py — retrains all models on schedule"""
import logging
from pathlib import Path
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)
LAST_TRAIN_FILE = "last_train.txt"
RETRAIN_HOURS   = 6


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

def _load_last() -> datetime | None:
    try:
        return datetime.fromisoformat(Path(LAST_TRAIN_FILE).read_text().strip())
    except Exception:
        return None

def _save_last():
    Path(LAST_TRAIN_FILE).write_text(_utc_now().isoformat())

def due() -> bool:
    last = _load_last()
    if last is None:
        return True
    return _utc_now() - last > timedelta(hours=RETRAIN_HOURS)

def run_if_due(edge_model, clv_model, meta_model) -> dict:
    """Retrain all models if scheduled. Returns dict of results."""
    if not due():
        return {}

    results = {}

    logger.info("=== ONLINE TRAINER: retraining all models ===")

    results["edge"]  = edge_model.train()
    results["clv"]   = clv_model.train()
    results["meta"]  = meta_model.train()

    _save_last()

    modes = {k: ("trained" if v else "skipped") for k,v in results.items()}
    logger.info(f"Training results: {modes}")

    # Log feature importance if edge model trained
    if results.get("edge") and edge_model.is_trained:
        fi = edge_model.feature_importance()
        if fi:
            top = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:5]
            logger.info("Top features: " + " | ".join(f"{k}={v:.3f}" for k,v in top))

    return results
