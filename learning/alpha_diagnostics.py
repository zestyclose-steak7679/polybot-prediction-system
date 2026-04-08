"""Diagnostics and logging helpers for shadow alpha calibration."""

from __future__ import annotations

import logging

from alpha.signals import diagnose_alpha_signals


def collect_alpha_diagnostics(markets_df, feature_map: dict, history_lookup: dict) -> dict:
    return diagnose_alpha_signals(markets_df, feature_map, history_lookup)


def log_alpha_diagnostics(logger: logging.Logger, diagnostics: dict) -> None:
    if not diagnostics:
        logger.info("Alpha diagnostics: no eligible markets")
        return

    for alpha_name, payload in diagnostics.items():
        thresholds = payload.get("thresholds", {})
        blockers = payload.get("failure_reasons", {})
        blocker_text = ", ".join(f"{reason}={count}" for reason, count in list(blockers.items())[:3]) or "none"
        score_stats = payload.get("score_stats", {})
        clv_stats = payload.get("predicted_clv_stats", {})
        logger.info(
            "Alpha diag | %s | pass %s/%s | score mean %.3f p80 %.3f max %.3f | pred_clv mean %.5f p80 %.5f | blockers: %s | thresholds: %s",
            alpha_name,
            payload.get("pass_count", 0),
            payload.get("eligible_markets", 0),
            score_stats.get("mean", 0.0),
            score_stats.get("p80", 0.0),
            score_stats.get("max", 0.0),
            clv_stats.get("mean", 0.0),
            clv_stats.get("p80", 0.0),
            blocker_text,
            thresholds,
        )
