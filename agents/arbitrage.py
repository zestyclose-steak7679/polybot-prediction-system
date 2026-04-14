import pandas as pd
import time
import logging

logger = logging.getLogger(__name__)

class ArbitrageAgent:
    def __init__(self, agent_id="arbitrage_agent"):
        self.agent_id = agent_id

    def detect_arbitrage(self, df: pd.DataFrame) -> list:
        opportunities = []
        if df.empty or 'tags' not in df.columns:
            return opportunities

        # Simple grouping by common tags to simulate related markets
        for tags, group in df.groupby('tags'):
            if len(group) > 1:
                # Find max and min yes_price within related markets
                max_row = group.loc[group['yes_price'].idxmax()]
                min_row = group.loc[group['yes_price'].idxmin()]

                diff = max_row['yes_price'] - min_row['yes_price']
                if diff > 0.15: # Arbitrage threshold
                    logger.info("ARBITRAGE_DETECTED")
                    # Latency check simulation
                    time.sleep(0.01)
                    opportunities.append({
                        "agent_id": self.agent_id,
                        "market_1": max_row['market_id'],
                        "market_2": min_row['market_id'],
                        "diff": diff,
                        "timestamp": time.time()
                    })
        return opportunities

arbitrage_agent = ArbitrageAgent()
