import logging

logger = logging.getLogger(__name__)

class MetaDecisionLayer:
    def __init__(self):
        self.agent_weights = {}

    def evaluate(self, agent_signals, performance_metrics, regime):
        decisions = []
        for agent_sig in agent_signals:
            agent_id = agent_sig.agent_id
            perf = performance_metrics.get(agent_id, {})
            roi = perf.get("roi", 0)

            # IF agent performance high -> increase allocation
            # IF agent performance degrading -> reduce allocation
            weight = 1.0
            if roi > 0.05:
                weight = 1.5
            elif roi < -0.05:
                weight = 0.5

            # Confidence weighting
            confidence = agent_sig.confidence
            final_weight = weight * confidence

            self.agent_weights[agent_id] = final_weight
            decisions.append({
                "agent_id": agent_id,
                "signal": agent_sig.signal,
                "weight": final_weight
            })
            logger.info("META_DECISION_MADE")

        return decisions

meta_decision = MetaDecisionLayer()
