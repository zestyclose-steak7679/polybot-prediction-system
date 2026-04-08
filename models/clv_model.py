"""
models/clv_model.py
─────────────────────────────────────────────────
Regressor: features at entry time → predicted CLV.
Replaces binary outcome prediction with a continuous target
that measures market-relative performance.

Only activates after MIN_SAMPLES closed bets with CLV data.
Falls back to 0.0 (no opinion) otherwise.
"""
import numpy as np
import pandas as pd
import pickle, sqlite3, logging
from pathlib import Path
from config import DB_PATH
from data.features import FEATURE_COLUMNS

logger = logging.getLogger(__name__)
MODEL_PATH   = "models/clv_model.pkl"
MIN_SAMPLES  = 100   # minimum CLV samples before trusting model


class CLVModel:
    def __init__(self):
        self.model      = None
        self.is_trained = False
        self._try_load()

    def _try_load(self):
        if Path(MODEL_PATH).exists():
            try:
                with open(MODEL_PATH,"rb") as f:
                    self.model = pickle.load(f)
                self.is_trained = True
                logger.info("CLV model loaded from disk.")
            except Exception as e:
                logger.warning(f"CLV model load failed: {e}")

    def _save(self):
        Path(MODEL_PATH).parent.mkdir(exist_ok=True)
        with open(MODEL_PATH,"wb") as f:
            pickle.dump(self.model, f)

    def train(self) -> bool:
        try:
            from sklearn.ensemble import GradientBoostingRegressor
        except ImportError:
            logger.warning("scikit-learn not available.")
            return False

        try:
            with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
                df = pd.read_sql(
                    """SELECT pb.entry_price, pb.clv, pb.strategy_tag,
                              pb.edge_est, pb.confidence,
                              ml.yes_price, ml.liquidity, ml.volume, ml.one_day_change
                       FROM paper_bets pb
                       LEFT JOIN market_log ml ON pb.market_id = ml.market_id
                       WHERE pb.clv IS NOT NULL
                       ORDER BY pb.placed_at DESC LIMIT 1000""",
                    con)
        except Exception as e:
            logger.error(f"CLV data load failed: {e}")
            return False

        df = df.dropna(subset=["clv"])
        if len(df) < MIN_SAMPLES:
            logger.info(f"CLV model: need {MIN_SAMPLES} samples, have {len(df)}")
            return False

        # Build feature proxy from available columns
        X = pd.DataFrame({
            "price":          df.get("entry_price", 0.5),
            "edge_est":       df.get("edge_est", 0),
            "confidence":     df.get("confidence", 0.5),
            "liquidity_raw":  df.get("liquidity", 1000),
            "volume_raw":     df.get("volume", 1000),
            "one_day_change": df.get("one_day_change", 0),
        }).fillna(0)

        y = df["clv"].values

        self.model = GradientBoostingRegressor(
            n_estimators=150, max_depth=3, learning_rate=0.05, random_state=42)
        self.model.fit(X.values, y)
        self.is_trained = True
        self._save()
        logger.info(f"CLV model trained on {len(df)} samples.")
        return True

    def predict(self, feats: dict) -> float:
        """Predict expected CLV. Returns 0.0 if not trained."""
        if not self.is_trained or self.model is None:
            return 0.0
        try:
            X = np.array([[
                feats.get("price", 0.5),
                feats.get("edge_est", 0),
                feats.get("confidence", 0.5),
                feats.get("liquidity", 1000),
                feats.get("volume", 1000),
                feats.get("one_day_change", 0),
            ]])
            return float(self.model.predict(X)[0])
        except Exception as e:
            logger.debug(f"CLV predict error: {e}")
            return 0.0

clv_model = CLVModel()
