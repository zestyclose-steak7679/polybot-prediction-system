"""
models/edge_model.py
─────────────────────────────────────────────────────────────
Phase 2 edge model with honest fallback logic.

MODE A — Heuristic (default, no training needed):
  Uses feature signals directly to estimate true probability.
  This is what runs until we have real outcome data.

MODE B — ML (auto-activates at 50+ closed bets):
  GradientBoostingClassifier trained on actual outcomes.
  Replaces heuristics with data-driven probabilities.

The model itself does NOT decide to bet.
It outputs a probability estimate.
The strategies/engine layer converts that to edge and bet sizing.

Real talk: Mode B only matters if Mode A showed alpha first.
Don't trust an untrained model with real capital.
"""

import numpy as np
import pandas as pd
import sqlite3
import pickle
import logging
from pathlib import Path
from config import DB_PATH
from data.features import FEATURE_COLUMNS, features_to_array

logger = logging.getLogger(__name__)

MODEL_PATH     = "models/edge_model.skops"
MIN_TRAIN_BETS = 50   # minimum closed bets before training ML model


# ── Heuristic edge (Mode A) ───────────────────────────────

def heuristic_edge(feats: dict, price: float) -> float:
    """
    Estimate a probability adjustment from features.
    Returns a small delta to add/subtract from market price.

    This is NOT pretending to know the true prob.
    It's saying: given these signals, the market might be off by X%.

    Signals used:
      z_score          — overextension (reversion signal)
      vol_spike_ratio  — smart money activity
      near_resolution  — info arrival zone
      mom_ratio        — momentum exhaustion
    """
    delta = 0.0

    # Mean reversion: z > 1.5 → price likely above true prob
    z = feats.get("z_score", 0)
    if abs(z) > 1.5:
        delta -= np.sign(z) * min(abs(z) * 0.015, 0.04)

    # Volume spike: smart money detected → follow direction
    spike = feats.get("vol_spike_ratio", 1.0)
    if spike > 2.0:
        mom = feats.get("mom_short", 0)
        delta += np.sign(mom) * min(np.log10(spike) * 0.02, 0.04)

    # Near resolution: volatility zone → small premium
    if feats.get("near_resolution", 0) and not feats.get("danger_zone", 0):
        delta += 0.01

    # Momentum exhaustion: ratio > 2 means recent move >> total → likely reverting
    ratio = feats.get("mom_ratio", 0)
    if abs(ratio) > 2.0:
        delta -= np.sign(ratio) * 0.01

    from config import MIN_PRICE, MAX_PRICE

    # Clamp: never claim more than 8% adjustment
    # Heuristic mode must clip output probability to [MIN_PRICE, MAX_PRICE] from config
    prob = price + float(np.clip(delta, -0.08, 0.08))
    prob = min(max(prob, MIN_PRICE), MAX_PRICE)
    return float(prob - price)


# ── ML model (Mode B) ────────────────────────────────────

class EdgeModel:
    def __init__(self):
        self.model       = None
        self.is_trained  = False
        self._try_load()

    def _try_load(self):
        """Load saved model if it exists."""
        if Path(MODEL_PATH).exists():
            try:
                with open(MODEL_PATH, "rb") as f:
                    self.model      = pickle.load(f)
                    self.is_trained = True
                logger.info("Loaded trained edge model from disk.")
            except Exception as e:
                logger.warning(f"Could not load model: {e}")

    def _save(self):
        Path(MODEL_PATH).parent.mkdir(exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(self.model, f)
        logger.info("Edge model saved.")

    def should_train(self) -> bool:
        """Check if we have enough outcome data to train."""
        try:
            with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
                count = con.execute(
                    "SELECT COUNT(*) FROM paper_bets WHERE result != 'open'"
                ).fetchone()[0]
            from config import MIN_BETS_TO_EVAL
            return count >= 50
        except Exception:
            return False

    def train(self, force: bool = False) -> bool:
        """
        Train GBM on closed paper bets with feature data.
        Returns True if training succeeded.

        We only train on bets that have feature data logged.
        Falls back gracefully if data is insufficient.
        """
        if not force and not self.should_train():
            logger.info(f"Not enough closed bets for ML training (need {MIN_TRAIN_BETS})")
            return False

        try:
            from sklearn.ensemble import GradientBoostingClassifier
        except ImportError:
            logger.warning("scikit-learn not installed. Running heuristic mode only.")
            return False

        try:
            with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
                df = pd.read_sql(
                    """SELECT pb.*, ml.yes_price, ml.liquidity, ml.volume,
                              ml.one_day_change, ml.signal_edge
                       FROM paper_bets pb
                       LEFT JOIN market_log ml ON pb.market_id = ml.market_id
                       WHERE pb.result != 'open'
                       ORDER BY pb.placed_at DESC
                       LIMIT 500""",
                    con
                )
        except Exception as e:
            logger.error(f"Training data load failed: {e}")
            return False

        if df.empty or "result" not in df.columns:
            return False

        # Build feature matrix from stored data
        # We use the fields we DO have in the DB as a proxy for full features
        feature_df = pd.DataFrame({
            "price":          df.get("entry_price", 0.5),
            "mom_short":      df.get("one_day_change", 0) * 0.1,
            "mom_medium":     df.get("one_day_change", 0),
            "mom_long":       df.get("one_day_change", 0),
            "mom_ratio":      1.0,
            "mom_acceleration": 0.0,
            "distance_from_mean": 0.0,
            "std_dev":        0.05,
            "z_score":        0.0,
            "vol_spike_ratio": df.get("volume", 1000) / 1000,
            "vol_trend":      0.0,
            "liquidity_log":  np.log10(df.get("liquidity", 1000).clip(lower=1)),
            "illiquid_flag":  (df.get("liquidity", 10000) < 10000).astype(int),
            "very_illiquid":  (df.get("liquidity", 10000) < 2000).astype(int),
            "hours_left":     999.0,
            "near_resolution": 0,
        }).fillna(0)

        X = feature_df[FEATURE_COLUMNS].values
        y = (df["result"] == "win").astype(int).values

        if len(np.unique(y)) < 2:
            logger.warning("Training skipped: only one outcome class in data")
            return False

        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )
        self.model.fit(X, y)
        self.is_trained = True
        self._save()

        acc = self.model.score(X, y)
        logger.info(f"Edge model trained | {len(y)} bets | in-sample acc: {acc:.3f}")
        logger.warning(
            "⚠ In-sample accuracy is NOT predictive accuracy. "
            "Monitor out-of-sample ROI before trusting this."
        )
        return True

    def predict_prob(self, feats: dict) -> float:
        """
        Predict P(win) for a set of features.
        Returns value in [0, 1].

        Falls back to heuristic if model not trained.
        """
        price = feats.get("price", 0.5)

        if self.is_trained and self.model is not None:
            try:
                X = features_to_array(feats).reshape(1, -1)
                prob = float(self.model.predict_proba(X)[0][1])
                logger.debug(f"ML prob={prob:.4f} for price={price:.4f}")
                return prob
            except Exception as e:
                logger.warning(f"ML prediction failed, using heuristic: {e}")

        # Heuristic fallback
        delta = heuristic_edge(feats, price)
        prob = min(max(price + delta, 0.0), 1.0)
        return prob

    def feature_importance(self) -> dict | None:
        """Return feature importances if model is trained."""
        if not self.is_trained or self.model is None:
            return None
        try:
            return dict(zip(FEATURE_COLUMNS, self.model.feature_importances_))
        except Exception:
            return None


# Singleton — main.py imports this
edge_model = EdgeModel()
