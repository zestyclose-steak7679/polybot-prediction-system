import logging
from data.database import get_closed_bets

logger = logging.getLogger(__name__)

def track_and_adjust(strategy: str) -> float:
    df = get_closed_bets(limit=500)
    tag = "WEAK"
    edge_decay = 0.0

    if not df.empty and "strategy_tag" in df.columns:
        strat_df = df[df["strategy_tag"] == strategy]
        if not strat_df.empty and "edge_est" in strat_df.columns and "clv" in strat_df.columns:
            valid = strat_df.dropna(subset=["edge_est", "clv"])
            if not valid.empty:
                # Compute: edge_decay = initial_edge - current_edge (approximated via CLV)
                edge_decay = float((valid["edge_est"] - valid["clv"]).mean())

                # Tag signals
                if edge_decay > 0.03:
                    tag = "DECAYING"
                elif edge_decay < 0.0:
                    tag = "STRONG"
                else:
                    tag = "WEAK"

    logger.info(f"EDGE_DECAY_TRACKED: Strategy={strategy}, Decay={edge_decay:.4f}, Tag={tag}")

    # Dynamic Position Adjustment
    multiplier = 1.0
    if tag == "STRONG":
        multiplier = 1.2
    elif tag == "DECAYING":
        multiplier = 0.5
    else:
        multiplier = 0.8

    logger.info(f"POSITION_ADJUSTED: Tag={tag}, Multiplier={multiplier:.2f}")
    return multiplier
