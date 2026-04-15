import logging
import math
from data.database import get_unscored_decisions, update_decision_score
# If clv data is retrieved via paper_bets, we might need a function to get it.
from data.database import query_to_df

logger = logging.getLogger(__name__)

SCALE_FACTOR = 10.0 # to scale CLV before tanh

def evaluate_decision(action: str, clv_15m: float) -> float:
    """
    Evaluates the quality of a decision based on 15m CLV.
    """
    if action == "EXECUTE":
        score = clv_15m
    elif action == "SKIP":
        score = -clv_15m # Missed opportunity if clv is positive
    elif action == "REDUCE":
        score = clv_15m * 0.5
    else:
        score = 0.0

    return math.tanh(score * SCALE_FACTOR)

def process_decision_evaluations():
    """
    Queries unscored decisions, attempts to attach CLV metrics,
    evaluates them, and updates the database.
    """
    decisions_df = get_unscored_decisions()
    if decisions_df.empty:
        return

    # Get CLV data for the matching market_ids.
    # Paper bets contain clv_5m, clv_15m, clv_60m
    markets_to_score = decisions_df['market_id'].unique().tolist()

    if not markets_to_score:
        return

    placeholders = ','.join('?' * len(markets_to_score))
    clv_query = f"""
        SELECT market_id, clv_5m, clv_15m, clv_60m
        FROM paper_bets
        WHERE market_id IN ({placeholders})
        AND clv_15m IS NOT NULL
    """
    clv_data = query_to_df(clv_query, params=tuple(markets_to_score))

    if clv_data.empty:
        return

    # Also check alpha_signals if paper_bets didn't have it (for shadow signals)
    # We'll stick to paper_bets for now, or just query clv_predictions?
    # paper_bets stores clv_5m, clv_15m, clv_60m directly

    clv_map = clv_data.groupby('market_id').last().to_dict(orient='index')

    scored_count = 0
    for _, row in decisions_df.iterrows():
        m_id = row['market_id']
        if m_id not in clv_map:
            continue

        clv_info = clv_map[m_id]
        c15 = clv_info.get('clv_15m')

        if c15 is None or math.isnan(c15):
            continue

        c5 = clv_info.get('clv_5m')
        c60 = clv_info.get('clv_60m')

        # Replace NaN with None for sqlite
        c5 = None if math.isnan(c5) else c5
        c60 = None if math.isnan(c60) else c60

        score = evaluate_decision(row['decision'], c15)
        update_decision_score(row['id'], c5, c15, c60, score)
        scored_count += 1

    if scored_count > 0:
        logger.info(f"DECISION_EVALUATOR | Evaluated {scored_count} decisions based on 15m CLV")
