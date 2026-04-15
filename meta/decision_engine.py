import logging
import json
from datetime import datetime, UTC
from typing import List, Dict, Any
from config import EDGE_THRESHOLD

logger = logging.getLogger(__name__)

class DecisionEngine:
    def __init__(self):
        pass

    def evaluate_trade(
        self,
        signals: List[Any],
        agent_metrics: Dict[str, Any],
        regime: str,
        risk_state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        decisions = []
        is_high_risk = risk_state.get("is_reduced", False)

        market_signals = {}
        for sig in signals:
            market_signals.setdefault(sig.market_id, []).append(sig)

        for sig in signals:
            agent_id = sig.strategy
            edge = getattr(sig, "edge", 0.0)
            side = getattr(sig, "side", "")

            decision = {
                "action": "EXECUTE",
                "confidence": getattr(sig, "confidence", 1.0),
                "reason": "Clear edge and favorable conditions",
                "selected_agent": agent_id,
                "market_id": sig.market_id,
                "signal": sig
            }

            market_group = market_signals.get(sig.market_id, [])
            conflicting_agents = []
            has_conflict = False
            best_clv_agent = agent_id
            max_clv = agent_metrics.get(agent_id, {}).get("avg_clv", 0)

            for other_sig in market_group:
                conflicting_agents.append(other_sig.strategy)
                if other_sig.side != side:
                    has_conflict = True
                other_clv = agent_metrics.get(other_sig.strategy, {}).get("avg_clv", 0)
                if other_clv > max_clv:
                    max_clv = other_clv
                    best_clv_agent = other_sig.strategy

            if has_conflict and best_clv_agent != agent_id:
                decision["action"] = "SKIP"
                decision["reason"] = f"Conflict: {best_clv_agent} has higher CLV"
                decision["confidence"] = 0.0
            elif has_conflict:
                decision["reason"] = "Conflict resolved: This agent has higher CLV"

            if edge < EDGE_THRESHOLD:
                decision["action"] = "SKIP"
                decision["reason"] = f"Edge {edge:.4f} below threshold {EDGE_THRESHOLD}"
                decision["confidence"] = 0.0

            if regime == "high_volatility" and "momentum" not in agent_id.lower() and decision["action"] == "EXECUTE":
                decision["action"] = "REDUCE"
                decision["confidence"] = 0.5
                decision["reason"] = f"Unfavorable regime ({regime}) for {agent_id}"

            if is_high_risk and decision["action"] == "EXECUTE":
                decision["action"] = "REDUCE"
                decision["confidence"] = 0.5
                decision["reason"] = "Risk override: Near drawdown limit"

            decisions.append(decision)

            log_payload = {
                "decision": decision["action"],
                "reason": decision["reason"],
                "confidence": decision["confidence"],
                "agents_considered": conflicting_agents
            }
            logger.info(f"DECISION | {sig.market_id} | {json.dumps(log_payload)}")

        return decisions
