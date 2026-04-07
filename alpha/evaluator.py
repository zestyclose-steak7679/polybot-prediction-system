"""Evaluation and promotion rules for shadow alpha modules."""

from __future__ import annotations

import pandas as pd

ALPHA_MIN_PROMOTION_SAMPLES = 100
ALPHA_POSITIVE_RATE_THRESHOLD = 0.55


def evaluate_alpha_modules(resolved_alpha_df: pd.DataFrame) -> dict[str, dict]:
    if resolved_alpha_df.empty or "alpha_name" not in resolved_alpha_df.columns:
        return {}

    results: dict[str, dict] = {}
    for alpha_name, group in resolved_alpha_df.groupby("alpha_name"):
        clv_series = group["resolved_clv"].dropna()
        if clv_series.empty:
            continue

        avg_clv = float(clv_series.mean())
        positive_rate = float((clv_series > 0).mean())
        clv_std = float(clv_series.std()) + 1e-9
        clv_sharpe = avg_clv / clv_std
        sample_count = int(len(clv_series))
        promoted = (
            sample_count >= ALPHA_MIN_PROMOTION_SAMPLES
            and avg_clv > 0.0
            and positive_rate >= ALPHA_POSITIVE_RATE_THRESHOLD
        )

        results[alpha_name] = {
            "alpha_name": alpha_name,
            "n": sample_count,
            "avg_clv": round(avg_clv, 5),
            "positive_rate": round(positive_rate, 3),
            "clv_sharpe": round(clv_sharpe, 3),
            "promoted": promoted,
            "status": "promoted" if promoted else "shadow",
        }

    return dict(
        sorted(
            results.items(),
            key=lambda item: (
                item[1]["promoted"],
                item[1]["avg_clv"],
                item[1]["n"],
            ),
            reverse=True,
        )
    )
