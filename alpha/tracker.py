"""Persistence and resolution helpers for shadow alpha signals."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd

from data.database import get_unresolved_alpha_signals, resolve_alpha_signal
from tracking.clv import CLV_CAPTURE_HOURS, compute_clv

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hours_to_resolution(end_date_str: str) -> float:
    try:
        end = datetime.fromisoformat(str(end_date_str).replace("Z", "").split("+")[0])
        return max((end - _utc_now()).total_seconds() / 3600, 0.0)
    except Exception:
        return 999.0


def resolve_alpha_signals(current_markets: pd.DataFrame) -> int:
    """
    Resolve shadow alpha rows once the market reaches the CLV capture window.
    """
    unresolved = get_unresolved_alpha_signals()
    if unresolved.empty or current_markets.empty:
        return 0

    resolved_count = 0
    for signal in unresolved.to_dict("records"):
        market_rows = current_markets[current_markets["market_id"] == signal["market_id"]]
        if market_rows.empty:
            continue

        row = market_rows.iloc[0]
        hours_left = _hours_to_resolution(row.get("end_date", ""))
        resolved_yes = row["yes_price"] >= 0.95
        resolved_no = row["yes_price"] <= 0.05
        if hours_left > CLV_CAPTURE_HOURS and not (resolved_yes or resolved_no):
            continue

        closing_price = float(row["yes_price"] if signal["direction"] == "YES" else row["no_price"])
        direction_val = 1 if signal["direction"] == "YES" else -1
        clv_value = compute_clv(float(signal["entry_price"]), closing_price, direction=direction_val)
        if clv_value is None:
            continue

        resolution_state = "resolved" if (resolved_yes or resolved_no) else "clv_window"
        resolve_alpha_signal(int(signal["id"]), closing_price, clv_value, resolution_state)
        resolved_count += 1

    if resolved_count:
        logger.info("Resolved %s shadow alpha signals", resolved_count)
    return resolved_count
