import time
import pandas as pd
import numpy as np
import random
import string
from scoring.strategies import run_strategies, STRATEGY_MAP, logger

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
signals = run_strategies(df, active_strategies)
end_time = time.time()

print(f"Optimized run_strategies (to_dict) took {end_time - start_time:.4f} seconds and generated {len(signals)} signals.")
