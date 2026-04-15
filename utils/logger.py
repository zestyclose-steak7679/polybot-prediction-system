import logging
import json
from datetime import UTC, datetime

class StructuredLogger:
    def __init__(self, module_name: str):
        self.module = module_name
        self.logger = logging.getLogger(f"structured.{module_name}")

    def log(self, event: str, market_id: str, status: str, details: dict, level=logging.INFO):
        log_entry = {
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
            "module": self.module,
            "event": event,
            "market_id": market_id,
            "status": status,
            "details": details or {}
        }
        self.logger.log(level, json.dumps(log_entry))

    def info(self, event: str, market_id: str, status: str, details: dict = None):
        self.log(event, market_id, status, details, level=logging.INFO)

    def error(self, event: str, market_id: str, status: str, details: dict = None):
        self.log(event, market_id, status, details, level=logging.ERROR)

    def warning(self, event: str, market_id: str, status: str, details: dict = None):
        self.log(event, market_id, status, details, level=logging.WARNING)

    def debug(self, event: str, market_id: str, status: str, details: dict = None):
        self.log(event, market_id, status, details, level=logging.DEBUG)

def get_structured_logger(module_name: str) -> StructuredLogger:
    return StructuredLogger(module_name)
