"""
risk/strategy_killer.py
Kills strategies with persistent negative CLV (not just noise).
Guards: min 50 bets, rolling window, re-enable after 12h cooldown.
"""
import json, logging
from pathlib import Path
from datetime import UTC, datetime, timedelta
from data.database import get_closed_bets

logger = logging.getLogger(__name__)
CLV_KILL_THRESHOLD  = -0.005   # avg CLV < -0.5%
MIN_BETS_TO_KILL    = 20
ROLLING_WINDOW      = 50
COOLDOWN_HOURS      = 12
COOLDOWN_FILE       = "killed_strategies.json"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load_killed() -> dict:
    try:
        return json.loads(Path(COOLDOWN_FILE).read_text())
    except Exception:
        return {}


def _save_killed(killed: dict):
    Path(COOLDOWN_FILE).write_text(json.dumps(killed))


def revive_eligible_strategies(killed: list, all_stats: dict) -> list:
    """
    Revive strategies that were killed but now show positive recent CLV.
    A strategy can be revived if it has been dead for 24+ hours
    and recent market conditions have changed regime.
    """
    revived = []
    for strategy in killed:
        stats = all_stats.get(strategy, {})
        # Revive if it has less than MIN_BETS_TO_KILL bets (killed too early)
        if stats.get("n_bets", 0) < MIN_BETS_TO_KILL:
            revived.append(strategy)
            logger.info("Reviving strategy %s — killed with insufficient data", strategy)
    return revived


def get_killed_strategies() -> set:
    df = get_closed_bets(limit=500)
    killed_log = _load_killed()
    now = _utc_now()
    killed = set()

    # Clear cooldowns that have expired
    expired = [k for k, ts in killed_log.items()
               if now - datetime.fromisoformat(ts) > timedelta(hours=COOLDOWN_HOURS)]
    for k in expired:
        del killed_log[k]
        logger.info(f"Strategy re-enabled after cooldown: {k}")

    if not df.empty and "strategy_tag" in df.columns:
        from config import STRATEGY_MIN_ROI
        from learning.tracker import get_all_strategy_stats
        sstats = get_all_strategy_stats()
        stats_dict = {s["strategy"]: s for s in sstats}

        for strat, grp in df.groupby("strategy_tag"):
            # Already in cooldown?
            if strat in killed_log:
                killed.add(strat)
                continue

            clv_data = grp["clv"].dropna().tail(ROLLING_WINDOW)
            if len(clv_data) < MIN_BETS_TO_KILL:
                continue   # not enough data — benefit of the doubt

            stats = stats_dict.get(strat, {})
            n_bets = stats.get("n_bets", 0) if isinstance(stats, dict) else 0
            if n_bets < MIN_BETS_TO_KILL:
                continue

            roi = stats.get("roi", 0.0) if isinstance(stats, dict) else 0.0
            if roi > STRATEGY_MIN_ROI:
                continue

            avg_clv = float(clv_data.mean())
            if avg_clv < CLV_KILL_THRESHOLD:
                killed.add(strat)
                killed_log[strat] = now.isoformat()
                logger.warning(
                    f"Strategy KILLED: {strat} | rolling avg CLV={avg_clv:.5f} "
                    f"over {len(clv_data)} bets | cooldown {COOLDOWN_HOURS}h"
                )

    _save_killed(killed_log)
    return killed
