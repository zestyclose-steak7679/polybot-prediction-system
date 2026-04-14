import time
import logging
from typing import Any, Mapping
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class AgentSignal:
    signal: Any
    edge: float
    confidence: float
    timestamp: float
    market_id: str
    agent_id: str

class BaseAgent:
    def __init__(self, agent_id: str, strategy_func):
        self.agent_id = agent_id
        self.strategy_func = strategy_func

    def generate_signal(self, row: Mapping[str, Any]) -> AgentSignal | None:
        raw_signal = self.strategy_func(row)
        if raw_signal:
            logger.info("AGENT_SIGNAL_GENERATED")
            return AgentSignal(
                signal=raw_signal,
                edge=raw_signal.edge,
                confidence=raw_signal.confidence,
                timestamp=time.time(),
                market_id=raw_signal.market_id,
                agent_id=self.agent_id
            )
        return None
