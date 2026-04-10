"""
models/regime_model.py
─────────────────────────────────────────────────
Rule-based regime detection (fast, no data needed).
Upgrades to MiniBatchKMeans after enough data.

Regimes:
  trending       → momentum works
  mean_reverting → reversion works
  volatile       → liquidity/reversion, reduce size
  illiquid_spike → liquidity edge
  neutral        → all strategies at reduced weight
"""
import numpy as np
import pickle, logging
from pathlib import Path
logger = logging.getLogger(__name__)

REGIME_MODEL_PATH = "models/regime_kmeans.pkl"
REGIME_LABELS = ["trending","mean_reverting","volatile","illiquid_spike","neutral"]


class RegimeModel:
    def __init__(self):
        self.kmeans = None
        self.use_ml  = False
        self._try_load()

    def _try_load(self):
        if Path(REGIME_MODEL_PATH).exists():
            try:
                with open(REGIME_MODEL_PATH,"rb") as f:
                    self.kmeans = pickle.load(f)
                self.use_ml = True
                logger.info("Loaded KMeans regime model.")
            except Exception:
                pass

    def predict(self, regime_feats: dict) -> str:
        try:
            if self.use_ml and self.kmeans is not None:
                return self._ml_predict(regime_feats)
            return self._rule_predict(regime_feats)
        except Exception as e:
            logger.warning(f"Regime prediction failed: {e}")
            return "neutral"

    def _rule_predict(self, f: dict) -> str:
        vol    = f.get("volatility", 0)
        trend  = f.get("trend_strength", 0)
        autocorr = f.get("autocorr", 0)
        spike  = f.get("vol_spike", 1)

        if spike > 2.5:
            return "illiquid_spike"
        if vol > 0.04 and abs(trend) > 0.015:
            return "volatile"
        if autocorr > 0.25:
            return "trending"
        if autocorr < -0.20:
            return "mean_reverting"
        return "neutral"

    def _ml_predict(self, f: dict) -> str:
        X = np.array([[f.get("volatility",0), f.get("trend_strength",0),
                       f.get("autocorr",0),   f.get("vol_spike",1),
                       f.get("price_range",0)]])
        cluster = int(self.kmeans.predict(X)[0])
        return REGIME_LABELS[cluster % len(REGIME_LABELS)]

    def partial_fit(self, X: np.ndarray):
        """Online update of KMeans (called each cycle with new regime vector)."""
        try:
            from sklearn.cluster import MiniBatchKMeans
            if self.kmeans is None:
                self.kmeans = MiniBatchKMeans(n_clusters=5, random_state=42)
            self.kmeans.partial_fit(X)
            self.use_ml = True
            Path(REGIME_MODEL_PATH).parent.mkdir(exist_ok=True)
            with open(REGIME_MODEL_PATH,"wb") as f:
                pickle.dump(self.kmeans, f)
        except Exception as e:
            logger.warning(f"Regime model partial fit failed: {e}")
            return

regime_model = RegimeModel()
