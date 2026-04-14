from dataclasses import dataclass
import time
from scoring.strategies import Signal

@dataclass
class AgentSignal:
    signal: Signal
    edge: float
    confidence: float
    timestamp: float
    market_id: str
    agent_id: str
