"""
scoring/engine.py

Phase 1 scoring — honest heuristics, no fake ML.
─────────────────────────────────────────────────
What this IS:
  A market-quality filter + momentum detector.
  It tells you WHICH markets are worth watching, not who will win.

What this IS NOT:
  A crystal ball. Edge estimates here are conservative guesses.
  Real edge requires a real prediction model (Phase 2).

Scoring components (0–1 each):
  1. liquidity_score   — bigger pool = more tradeable, tighter spread
  2. volume_momentum   — recent 24h activity vs total (hot market)
  3. price_tension     — prices near 0.3–0.7 = most uncertain = most opportunity
  4. spread_efficiency — YES+NO close to 1.0 = efficient market (good sign)
  5. price_move        — significant 24h move = potential overreaction to fade

Edge estimate:
  We DON'T pretend to know the true probability.
  We flag markets where a 4% edge would be plausible given signals.
  You decide whether to act.
"""

import pandas as pd
import numpy as np
import logging
from config import EDGE_THRESHOLD, KELLY_FRACTION, MAX_BET_PCT, BANKROLL

logger = logging.getLogger(__name__)


# ── Individual scorers (each returns 0.0–1.0) ─────────────────────────────────

def _liquidity_score(liq: float) -> float:
    """Log-scaled. $500 → 0.1, $10k → 0.5, $100k → 0.8"""
    if liq <= 0:
        return 0.0
    return float(np.clip(np.log10(liq) / 6.0, 0.0, 1.0))


def _volume_momentum(volume: float, one_day_change: float) -> float:
    """High absolute price move in 24h = active market."""
    move = abs(one_day_change)
    # Scale: 0% move → 0, 10% move → 0.5, 20%+ move → 1.0
    return float(np.clip(move / 0.20, 0.0, 1.0))


def _price_tension(yes_price: float) -> float:
    """
    Markets near 0.5 have maximum uncertainty = maximum potential edge.
    Bell curve centred at 0.5.
    """
    return float(1.0 - abs(yes_price - 0.5) * 2)


def _spread_efficiency(yes_price: float, no_price: float) -> float:
    """
    |YES + NO - 1| is the book's cut.
    Tight spread (< 2%) = efficient, tradeable.
    Wide spread (> 8%) = avoid.
    """
    spread = abs(1.0 - yes_price - no_price)
    return float(np.clip(1.0 - spread / 0.08, 0.0, 1.0))


def compute_confidence(signal, market_row, history_df) -> float:
    """
    Confidence = weighted combination of:
    - History depth:     min(len(history_df) / 20, 1.0)      weight=0.30
    - Volume consistency: 1 - (vol_std / (vol_mean + 1e-6))  weight=0.25
    - Price stability:   1 - abs(one_day_change)              weight=0.25
    - Edge margin:       min(signal.edge / 0.10, 1.0)         weight=0.20
    All components clipped to [0.0, 1.0] before combining.
    Returns float in [0.0, 1.0].
    """
    history_depth = min(len(history_df) / 20, 1.0)

    if not history_df.empty and "volume" in history_df.columns:
        vol_mean = history_df["volume"].mean()
        vol_std = history_df["volume"].std()
        vol_consistency = 1.0 - min(vol_std / (vol_mean + 1e-6), 1.0)
    else:
        vol_consistency = 0.3

    price_stability = max(0.0, 1.0 - abs(market_row.get("one_day_change", 0.5)))
    edge_margin = min(signal.edge / 0.10, 1.0)

    confidence = (
        0.30 * history_depth +
        0.25 * vol_consistency +
        0.25 * price_stability +
        0.20 * edge_margin
    )
    return round(float(np.clip(confidence, 0.0, 1.0)), 4)


# ── Main scoring ──────────────────────────────────────────────────────────────

WEIGHTS = {
    "liquidity":   0.30,
    "momentum":    0.25,
    "tension":     0.20,
    "efficiency":  0.15,
    "volume_raw":  0.10,
}


def score_market(row: pd.Series) -> float:
    liq    = _liquidity_score(row["liquidity"])
    mom    = _volume_momentum(row["volume"], row["one_day_change"])
    tens   = _price_tension(row["yes_price"])
    eff    = _spread_efficiency(row["yes_price"], row["no_price"])
    vol_s  = float(np.clip(np.log10(max(row["volume"], 1)) / 7.0, 0, 1))

    score = (
        WEIGHTS["liquidity"]  * liq   +
        WEIGHTS["momentum"]   * mom   +
        WEIGHTS["tension"]    * tens  +
        WEIGHTS["efficiency"] * eff   +
        WEIGHTS["volume_raw"] * vol_s
    )
    return round(score, 4)


def score_all(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["score"] = df.apply(score_market, axis=1)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    return df


# ── Edge and Kelly ────────────────────────────────────────────────────────────

def estimate_edge(yes_price: float, score: float) -> tuple[str, float, float]:
    """
    Phase 1 edge estimation.

    We do NOT claim to know the true probability.
    We use the market price as base and apply a small score-derived adjustment.

    Returns: (side, true_prob_estimate, edge)
      side = "YES" or "NO"
    """
    # Score 0.0–1.0 → edge adjustment 0%–6%
    # This is intentionally conservative
    adjustment = score * 0.06

    # Bet YES if market looks underpriced (score suggests positive momentum)
    # Bet NO if market looks overpriced
    # Simple heuristic: high price movement + high score → fade (contrarian)
    true_prob_yes = yes_price + adjustment
    true_prob_no  = (1 - yes_price) + adjustment

    edge_yes = true_prob_yes - yes_price
    edge_no  = true_prob_no - (1 - yes_price)

    if edge_yes >= edge_no:
        return "YES", round(true_prob_yes, 4), round(edge_yes, 4)
    else:
        return "NO", round(true_prob_no, 4), round(edge_no, 4)


def kelly_bet(bankroll: float, prob: float, decimal_odds: float) -> dict:
    """
    Full Kelly formula, capped at MAX_BET_PCT of bankroll.
    decimal_odds = 1/price  (e.g. price 0.45 → odds 2.22)

    Returns dict with bet_size, kelly_raw, kelly_fraction_used.
    """
    b = decimal_odds - 1          # net odds (profit per $1 staked)
    if b <= 0:
        return {"bet_size": 0, "kelly_raw": 0, "kelly_fraction_used": 0}

    kelly_raw = (prob * (b + 1) - 1) / b
    kelly_raw = max(0.0, kelly_raw)

    kelly_adj  = kelly_raw * KELLY_FRACTION
    max_bet    = bankroll * MAX_BET_PCT
    bet_size   = min(bankroll * kelly_adj, max_bet)
    bet_size   = round(max(0.0, bet_size), 2)

    return {
        "bet_size":           bet_size,
        "kelly_raw":          round(kelly_raw, 4),
        "kelly_fraction_used": KELLY_FRACTION,
    }


# ── Top picks ─────────────────────────────────────────────────────────────────

def get_top_picks(df: pd.DataFrame, bankroll: float, top_n: int = 5) -> list[dict]:
    """
    Score all markets, apply edge threshold, return top N as list of dicts
    ready for alerting and paper logging.
    """
    if df.empty:
        return []

    scored = score_all(df)
    picks  = []

    for _, row in scored.iterrows():
        side, true_prob, edge = estimate_edge(row["yes_price"], row["score"])

        if edge < EDGE_THRESHOLD:
            continue

        price       = row["yes_price"] if side == "YES" else row["no_price"]
        decimal_odds = round(1 / price, 4) if price > 0 else 0
        kelly        = kelly_bet(bankroll, true_prob, decimal_odds)

        logger.info(f"SIGNAL_VALIDATED: {row['market_id']} for {side} passed validation")
        picks.append({
            "market_id":    row["market_id"],
            "question":     row["question"],
            "tags":         row["tags"],
            "side":         side,
            "price":        price,
            "decimal_odds": decimal_odds,
            "true_prob":    true_prob,
            "edge":         edge,
            "score":        row["score"],
            "liquidity":    row["liquidity"],
            "volume":       row["volume"],
            "one_day_change": row["one_day_change"],
            "end_date":     row["end_date"],
            **kelly,
        })

        if len(picks) >= top_n:
            break

    logger.info(f"Top picks found: {len(picks)}")
    return picks


def confidence_multiplier(confidence: float) -> float:
    """
    Maps confidence score to bet size multiplier.
    Conservative scaling — never bet more than 1.5x base,
    never less than 0.5x base.
    """
    if confidence is None:
        return 1.0
    confidence = max(0.0, min(1.0, float(confidence)))
    if confidence >= 0.75:
        return 1.5
    elif confidence >= 0.60:
        return 1.25
    elif confidence >= 0.45:
        return 1.0
    elif confidence >= 0.30:
        return 0.75
    else:
        return 0.5
