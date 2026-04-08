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
MIN_BETS_TO_KILL    = 50
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
        for strat, grp in df.groupby("strategy_tag"):
            # Already in cooldown?
            if strat in killed_log:
                killed.add(strat)
                continue

            clv_data = grp["clv"].dropna().tail(ROLLING_WINDOW)
            if len(clv_data) < MIN_BETS_TO_KILL:
                continue   # not enough data — benefit of the doubt

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
