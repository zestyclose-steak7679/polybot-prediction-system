import logging
from collections import defaultdict
from learning.tracker import compute_strategy_roi

logger = logging.getLogger(__name__)

class AgentPerformanceTracker:
    def __init__(self):
        self.metrics = defaultdict(dict)

    def update_performance(self, agent_ids: list):
        for agent_id in agent_ids:
            # Reusing strategy_roi assuming agent_id maps to strategy tag
            stats = compute_strategy_roi(agent_id, last_n=20)
            if stats:
                self.metrics[agent_id] = {
                    "pnl": stats.get("total_pnl", 0),
                    "clv": stats.get("avg_clv", 0),
                    "win_rate": stats.get("win_rate", 0),
                    "roi": stats.get("roi", 0)
                }
                logger.info("AGENT_PERFORMANCE_UPDATED")
            else:
                self.metrics[agent_id] = {
                    "pnl": 0, "clv": 0, "win_rate": 0, "roi": 0
                }

    def rank_agents(self):
        # Rank by ROI first, then win_rate
        ranked = sorted(self.metrics.items(), key=lambda x: (x[1]["roi"], x[1]["win_rate"]), reverse=True)
        logger.info("AGENT_RANK_UPDATED")
        return [agent_id for agent_id, _ in ranked]

performance_tracker = AgentPerformanceTracker()
