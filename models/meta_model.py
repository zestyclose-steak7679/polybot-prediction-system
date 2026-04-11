"""
models/meta_model.py
─────────────────────────────────────────────────
Predicts expected CLV per strategy given current features + regime.
Used to weight strategies dynamically instead of fixed weights.

Until enough data: falls back to equal weights.
"""
import numpy as np
import pickle, sqlite3, logging
import pandas as pd
from pathlib import Path
from config import DB_PATH

logger = logging.getLogger(__name__)
MODEL_PATH  = "models/meta_model.pkl"
MIN_SAMPLES = 200


class MetaModel:
    def __init__(self):
        self.model       = None
        self.is_trained  = False
        self.strategy_names = []
        self._try_load()

    def _try_load(self):
        if Path(MODEL_PATH).exists():
            try:
                with open(MODEL_PATH,"rb") as f:
                    data = pickle.load(f)
                self.model, self.strategy_names = data
                self.is_trained = True
                logger.info("Meta-model loaded.")
            except Exception:
                pass

    def train(self) -> bool:
        try:
            from sklearn.ensemble import GradientBoostingRegressor
        except ImportError:
            return False
        try:
            with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
                df = pd.read_sql(
                    """SELECT pb.strategy_tag, pb.clv, pb.edge_est,
                              pb.confidence, pb.entry_price,
                              ml.liquidity, ml.volume, ml.one_day_change, ml.regime
                       FROM paper_bets pb
                       LEFT JOIN market_log ml ON pb.market_id = ml.market_id
                       WHERE pb.clv IS NOT NULL LIMIT 2000""",
                    con)
        except Exception as e:
            logger.error(f"Meta-model data load: {e}")
            return False

        df = df.dropna(subset=["clv","strategy_tag"])
        if len(df) < MIN_SAMPLES:
            return False

        df["strategy_code"] = pd.Categorical(df["strategy_tag"]).codes
        self.strategy_names = df["strategy_tag"].unique().tolist()

        X = df[["strategy_code","edge_est","confidence","entry_price",
                "liquidity","volume","one_day_change"]].fillna(0).values
        y = df["clv"].values

        self.model = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42)
        self.model.fit(X, y)
        self.is_trained = True
        Path(MODEL_PATH).parent.mkdir(exist_ok=True)
        with open(MODEL_PATH,"wb") as f:
            pickle.dump((self.model, self.strategy_names), f)
        logger.info("Meta-model trained.")
        return True

    def predict_weights(self, feats: dict, strategy_names: list) -> dict:
        """Return edge weight per strategy. Falls back to equal weights."""
        if not strategy_names:
            return {}

        if not self.is_trained or self.model is None:
            w = 1 / len(strategy_names)
            return {s: w for s in strategy_names}

        try:
            X_batch = np.array([
                [i, feats.get("edge_est", 0), feats.get("confidence", 0.5),
                 feats.get("price", 0.5), feats.get("liquidity", 1000),
                 feats.get("volume", 1000), feats.get("one_day_change", 0)]
                for i in range(len(strategy_names))
            ])
            preds = self.model.predict(X_batch)
            weights = {
                strat: max(float(preds[i]), 0.0)
                for i, strat in enumerate(strategy_names)
            }
        except Exception:
            weights = {strat: 0.0 for strat in strategy_names}

        # weights = softmax(weights) so they sum to 1
        total = sum(weights.values())
        if total == 0:
            w = 1 / len(strategy_names)
            return {s: w for s in strategy_names}

        vals = np.array(list(weights.values()))
        exp_vals = np.exp(vals - np.max(vals))
        softmax_vals = exp_vals / np.sum(exp_vals)
        return {k: float(v) for k, v in zip(weights.keys(), softmax_vals)}

meta_model = MetaModel()
