import logging
from data.database import get_open_bets
from data.markets import fetch_markets

logger = logging.getLogger(__name__)

def log_portfolio_snapshot():
    open_bets = get_open_bets()
    if open_bets.empty:
        return

    markets = fetch_markets()
    total_exposure = open_bets["bet_size"].sum()
    unrealized_pnl = 0.0

    for _, bet in open_bets.iterrows():
        mid = bet["market_id"]
        row = markets[markets["market_id"] == mid] if not markets.empty else None
        if row is not None and not row.empty:
            cp = row.iloc[0]["yes_price"] if bet["side"] == "YES" else row.iloc[0]["no_price"]
            ep = bet["entry_price"]
            if bet["side"] == "YES":
                unrealized_pnl += bet["bet_size"] * (cp / ep - 1.0) if ep > 0 else 0
            else:
                if ep < 1.0:
                    unrealized_pnl += bet["bet_size"] * ((1.0-cp) / (1.0-ep) - 1.0)

    logger.info(f"PORTFOLIO_UPDATED: Active={len(open_bets)}, Total Exposure=${total_exposure:.2f}, Unrealized PnL=${unrealized_pnl:.2f}")
