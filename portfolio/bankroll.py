import logging
from data.database import get_open_bets

logger = logging.getLogger(__name__)

class BankrollTracker:
    def __init__(self, initial_capital: float):
        self.starting_capital = initial_capital
        self.current_capital = initial_capital
        self.allocated_capital = 0.0

    def update(self, current: float):
        self.current_capital = current
        open_bets = get_open_bets()
        self.allocated_capital = open_bets["bet_size"].sum() if not open_bets.empty else 0.0

        if self.allocated_capital > self.current_capital:
            logger.warning("Over-allocation detected!")
            self.allocated_capital = self.current_capital

        logger.info(f"BANKROLL_UPDATED: Start=${self.starting_capital:.2f}, Current=${self.current_capital:.2f}, Allocated=${self.allocated_capital:.2f}, Available=${self.available_balance():.2f}")

    def available_balance(self) -> float:
        return max(0.0, self.current_capital - self.allocated_capital)
