import time
import pandas as pd
import numpy as np
import random
import string

# We will create an original version of run_strategies
from scoring.strategies import STRATEGY_MAP, logger
def run_strategies_original(df: pd.DataFrame, active: list[str]):
    signals = []
    seen    = set()   # (market_id, side) pairs to avoid duplicate alerts

    for _, row in df.iterrows():
        for name in active:
            fn = STRATEGY_MAP.get(name)
            if fn is None:
                continue
            try:
                sig = fn(row)
            except Exception as e:
                logger.debug(f"Strategy {name} error on {row.get('market_id')}: {e}")
                continue

            if sig is None:
                continue

            key = (sig.market_id, sig.side)
            if key in seen:
                continue

            seen.add(key)
            signals.append(sig)

    signals.sort(key=lambda s: s.edge, reverse=True)
    return signals

# Create dummy data
num_rows = 10000
data = {
    "market_id": ["".join(random.choices(string.ascii_letters + string.digits, k=10)) for _ in range(num_rows)],
    "question": ["Dummy Question"] * num_rows,
    "yes_price": np.random.uniform(0.1, 0.9, num_rows),
    "no_price": np.random.uniform(0.1, 0.9, num_rows),
    "one_day_change": np.random.uniform(-0.2, 0.2, num_rows),
    "liquidity": np.random.uniform(10, 1000, num_rows),
    "volume": np.random.uniform(10, 2000, num_rows),
    "tags": ["[]"] * num_rows,
    "end_date": ["2024-12-31"] * num_rows,
}
df = pd.DataFrame(data)

active_strategies = list(STRATEGY_MAP.keys())

start_time = time.time()
signals = run_strategies_original(df, active_strategies)
end_time = time.time()

print(f"Original run_strategies took {end_time - start_time:.4f} seconds and generated {len(signals)} signals.")
