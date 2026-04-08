"""Public-API alpha signals that operate in shadow mode first."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter

import numpy as np
import pandas as pd

ALPHA_LIVE_CLV_THRESHOLD = 0.010


@dataclass
class AlphaSignal:
    market_id: str
    question: str
    alpha_name: str
    score: float
    predicted_clv: float
    direction: str
    reason: str
    shadow_only: bool
    feature_payload: dict
    regime: str
    entry_price: float
    passed_live_threshold: bool


def _bounded_quantile(values: list[float], q: float, default: float, low: float, high: float) -> float:
    if not values:
        return default
    return float(np.clip(np.quantile(np.asarray(values, dtype=float), q), low, high))


def _safe_price_range(history: pd.DataFrame) -> float:
    prices = history["yes_price"].to_numpy(dtype=float)
    if len(prices) == 0:
        return 0.0
    return float((prices.max() - prices.min()) / (np.mean(prices) + 1e-6))


def _safe_volume_pressure(row: pd.Series, history: pd.DataFrame) -> float:
    volume = float(row.get("volume", 0.0) or 0.0)
    avg_volume = float(history["volume"].mean()) if "volume" in history.columns else 0.0
    return volume / (avg_volume + 1e-6) if avg_volume > 0 else 1.0


def compute_alpha_thresholds(markets_df: pd.DataFrame, feature_map: dict, history_lookup: dict) -> dict[str, dict]:
    late_vol_spike: list[float] = []
    late_strength: list[float] = []
    reversion_z: list[float] = []
    reversion_distance: list[float] = []
    reversion_vol: list[float] = []
    reversion_accel: list[float] = []
    spread_values: list[float] = []
    spread_ranges: list[float] = []
    spread_liquidity: list[float] = []
    spread_volume_pressure: list[float] = []

    for row in markets_df.to_dict("records"):
        market_id = row["market_id"]
        feats = feature_map.get(market_id)
        history = history_lookup.get(market_id)
        if not feats or history is None or history.empty or len(history) < 5:
            continue

        late_vol_spike.append(float(feats.get("vol_spike_ratio", 1.0)))
        late_strength.append(
            abs(float(feats.get("mom_short", 0.0)))
            + 0.75 * abs(float(feats.get("mom_medium", 0.0)))
            + 1.25 * abs(float(feats.get("mom_acceleration", 0.0)))
        )

        reversion_z.append(abs(float(feats.get("z_score", 0.0))))
        reversion_distance.append(abs(float(feats.get("distance_from_mean", 0.0))))
        reversion_vol.append(float(feats.get("vol_spike_ratio", 1.0)))
        reversion_accel.append(abs(float(feats.get("mom_acceleration", 0.0))))

        spread_values.append(abs(1.0 - float(row["yes_price"]) - float(row["no_price"])))
        spread_ranges.append(_safe_price_range(history))
        spread_liquidity.append(float(row.get("liquidity", 0.0) or 0.0))
        spread_volume_pressure.append(_safe_volume_pressure(row, history))

    return {
        "late_drift": {
            "vol_spike_min": _bounded_quantile(late_vol_spike, 0.65, 1.15, 1.05, 1.8),
            "momentum_strength_min": _bounded_quantile(late_strength, 0.70, 0.02, 0.01, 0.12),
            "score_min": 0.50,
        },
        "reversion_gap": {
            "z_abs_min": _bounded_quantile(reversion_z, 0.70, 1.6, 1.1, 2.8),
            "distance_abs_min": _bounded_quantile(reversion_distance, 0.70, 0.025, 0.01, 0.08),
            "vol_spike_min": _bounded_quantile(reversion_vol, 0.60, 1.15, 1.0, 2.2),
            "accel_conflict_floor": _bounded_quantile(reversion_accel, 0.45, 0.0015, 0.001, 0.02),
            "score_min": 0.50,
        },
        "spread_pressure": {
            "spread_min": _bounded_quantile(spread_values, 0.70, 0.02, 0.01, 0.08),
            "price_range_min": _bounded_quantile(spread_ranges, 0.60, 0.02, 0.005, 0.12),
            "volume_pressure_min": _bounded_quantile(spread_volume_pressure, 0.40, 1.0, 0.8, 1.3),
            "liquidity_soft_cap": _bounded_quantile(spread_liquidity, 0.45, 10000.0, 2000.0, 20000.0),
            "score_min": 0.48,
        },
    }


def _make_signal(row: pd.Series, alpha_name: str, score: float, predicted_clv: float, direction: str, reason: str, regime: str, feature_payload: dict) -> AlphaSignal:
    side_price = float(row["yes_price"] if direction == "YES" else row["no_price"])
    return AlphaSignal(
        market_id=str(row["market_id"]),
        question=str(row.get("question", "")),
        alpha_name=alpha_name,
        score=round(float(np.clip(score, 0.0, 1.0)), 4),
        predicted_clv=round(float(max(predicted_clv, 0.0)), 5),
        direction=direction,
        reason=reason,
        shadow_only=True,
        feature_payload=feature_payload,
        regime=regime,
        entry_price=round(side_price, 4),
        passed_live_threshold=predicted_clv >= ALPHA_LIVE_CLV_THRESHOLD,
    )


def _late_drift_candidate(row: pd.Series, feats: dict, history: pd.DataFrame, thresholds: dict) -> dict:
    if history.empty or len(history) < 5:
        return {"passed": False, "reason": "insufficient_history", "score": 0.0, "predicted_clv": 0.0}
    if feats.get("near_resolution", 0) != 1:
        return {"passed": False, "reason": "not_near_resolution", "score": 0.0, "predicted_clv": 0.0}
    if feats.get("danger_zone", 0) == 1:
        return {"passed": False, "reason": "danger_zone", "score": 0.0, "predicted_clv": 0.0}

    mom_short = float(feats.get("mom_short", 0.0))
    mom_medium = float(feats.get("mom_medium", 0.0))
    accel = float(feats.get("mom_acceleration", 0.0))
    vol_spike = float(feats.get("vol_spike_ratio", 1.0))
    momentum_strength = abs(mom_short) + 0.75 * abs(mom_medium) + 1.25 * abs(accel)

    if np.sign(mom_short) == 0 or np.sign(mom_short) != np.sign(mom_medium) or np.sign(mom_short) != np.sign(accel):
        return {"passed": False, "reason": "misaligned_momentum", "score": 0.0, "predicted_clv": 0.0}
    if momentum_strength < thresholds["momentum_strength_min"]:
        return {"passed": False, "reason": "weak_momentum", "score": momentum_strength, "predicted_clv": 0.0}
    if vol_spike < thresholds["vol_spike_min"]:
        return {"passed": False, "reason": "low_volume_confirmation", "score": momentum_strength, "predicted_clv": 0.0}

    momentum_component = min(momentum_strength / max(thresholds["momentum_strength_min"], 1e-6), 2.0) / 2.0
    volume_component = min(vol_spike / max(thresholds["vol_spike_min"], 1e-6), 2.0) / 2.0
    score = 0.58 * momentum_component + 0.42 * volume_component
    predicted_clv = 0.0015 + abs(mom_short) * 0.12 + abs(accel) * 0.08 + max(vol_spike - thresholds["vol_spike_min"], 0.0) * 0.0015

    return {
        "passed": score >= thresholds["score_min"],
        "reason": "score_below_cutoff" if score < thresholds["score_min"] else "pass",
        "score": score,
        "predicted_clv": predicted_clv,
        "direction": "YES" if mom_short > 0 else "NO",
        "feature_payload": {
            "mom_short": mom_short,
            "mom_medium": mom_medium,
            "mom_acceleration": accel,
            "vol_spike_ratio": vol_spike,
            "momentum_strength": round(momentum_strength, 5),
            "hours_left": feats.get("hours_left", 999.0),
        },
        "reason_text": f"Late drift: momentum {momentum_strength:.4f}, volume {vol_spike:.2f}x",
    }


def _reversion_gap_candidate(row: pd.Series, feats: dict, history: pd.DataFrame, thresholds: dict) -> dict:
    if history.empty or len(history) < 5:
        return {"passed": False, "reason": "insufficient_history", "score": 0.0, "predicted_clv": 0.0}

    z_score = float(feats.get("z_score", 0.0))
    distance = float(feats.get("distance_from_mean", 0.0))
    vol_spike = float(feats.get("vol_spike_ratio", 1.0))
    accel = float(feats.get("mom_acceleration", 0.0))

    if abs(z_score) < thresholds["z_abs_min"]:
        return {"passed": False, "reason": "zscore_below_threshold", "score": abs(z_score), "predicted_clv": 0.0}
    if abs(distance) < thresholds["distance_abs_min"]:
        return {"passed": False, "reason": "distance_below_threshold", "score": abs(distance), "predicted_clv": 0.0}
    if vol_spike < thresholds["vol_spike_min"]:
        return {"passed": False, "reason": "low_panic_volume", "score": vol_spike, "predicted_clv": 0.0}
    if np.sign(z_score) == np.sign(accel) and abs(accel) > thresholds["accel_conflict_floor"]:
        return {"passed": False, "reason": "move_still_accelerating", "score": abs(accel), "predicted_clv": 0.0}

    z_component = min(abs(z_score) / max(thresholds["z_abs_min"], 1e-6), 2.0) / 2.0
    distance_component = min(abs(distance) / max(thresholds["distance_abs_min"], 1e-6), 2.0) / 2.0
    volume_component = min(vol_spike / max(thresholds["vol_spike_min"], 1e-6), 2.0) / 2.0
    score = 0.40 * z_component + 0.35 * distance_component + 0.25 * volume_component
    predicted_clv = 0.002 + abs(z_score) * 0.003 + abs(distance) * 0.10 + max(vol_spike - thresholds["vol_spike_min"], 0.0) * 0.001

    return {
        "passed": score >= thresholds["score_min"],
        "reason": "score_below_cutoff" if score < thresholds["score_min"] else "pass",
        "score": score,
        "predicted_clv": predicted_clv,
        "direction": "NO" if z_score > 0 else "YES",
        "feature_payload": {
            "z_score": z_score,
            "distance_from_mean": distance,
            "vol_spike_ratio": vol_spike,
            "mom_acceleration": accel,
        },
        "reason_text": f"Reversion gap: z={z_score:.2f}, dist={distance:.3f}, volume={vol_spike:.2f}x",
    }


def _spread_pressure_candidate(row: pd.Series, feats: dict, history: pd.DataFrame, thresholds: dict) -> dict:
    if history.empty or len(history) < 5:
        return {"passed": False, "reason": "insufficient_history", "score": 0.0, "predicted_clv": 0.0}

    spread = abs(1.0 - float(row["yes_price"]) - float(row["no_price"]))
    liquidity = float(row.get("liquidity", 0.0) or 0.0)
    volume_pressure = _safe_volume_pressure(row, history)
    price_range = _safe_price_range(history)
    prices = history["yes_price"].to_numpy(dtype=float)

    if spread < thresholds["spread_min"]:
        return {"passed": False, "reason": "spread_too_tight", "score": spread, "predicted_clv": 0.0}
    if price_range < thresholds["price_range_min"]:
        return {"passed": False, "reason": "range_too_small", "score": price_range, "predicted_clv": 0.0}
    if liquidity > thresholds["liquidity_soft_cap"] and volume_pressure < thresholds["volume_pressure_min"]:
        return {"passed": False, "reason": "book_too_stable", "score": volume_pressure, "predicted_clv": 0.0}

    spread_component = min(spread / max(thresholds["spread_min"], 1e-6), 2.0) / 2.0
    range_component = min(price_range / max(thresholds["price_range_min"], 1e-6), 2.0) / 2.0
    liquidity_component = 1.0 if liquidity <= thresholds["liquidity_soft_cap"] else 0.55
    score = 0.40 * spread_component + 0.35 * range_component + 0.25 * liquidity_component
    predicted_clv = 0.0015 + spread * 0.12 + price_range * 0.04 + min(volume_pressure, thresholds["volume_pressure_min"]) * 0.002

    return {
        "passed": score >= thresholds["score_min"],
        "reason": "score_below_cutoff" if score < thresholds["score_min"] else "pass",
        "score": score,
        "predicted_clv": predicted_clv,
        "direction": "YES" if float(row["yes_price"]) < float(prices.mean()) else "NO",
        "feature_payload": {
            "spread": round(spread, 5),
            "price_range": round(price_range, 5),
            "volume_pressure": round(volume_pressure, 4),
            "liquidity": liquidity,
        },
        "reason_text": f"Spread pressure: spread={spread:.3f}, range={price_range:.3f}, liquidity=${liquidity:,.0f}",
    }


ALPHA_EVALUATORS = {
    "late_drift": _late_drift_candidate,
    "reversion_gap": _reversion_gap_candidate,
    "spread_pressure": _spread_pressure_candidate,
}


def diagnose_alpha_signals(markets_df: pd.DataFrame, feature_map: dict, history_lookup: dict) -> dict:
    thresholds = compute_alpha_thresholds(markets_df, feature_map, history_lookup)
    diagnostics: dict[str, dict] = {}

    for alpha_name in ALPHA_EVALUATORS:
        diagnostics[alpha_name] = {
            "eligible_markets": 0,
            "pass_count": 0,
            "failure_reasons": Counter(),
            "scores": [],
            "predicted_clvs": [],
            "thresholds": thresholds[alpha_name],
        }

    for row in markets_df.to_dict("records"):
        market_id = row["market_id"]
        feats = feature_map.get(market_id)
        history = history_lookup.get(market_id)
        if not feats or history is None or history.empty or len(history) < 5:
            for alpha_name in diagnostics:
                diagnostics[alpha_name]["failure_reasons"]["insufficient_history"] += 1
            continue

        for alpha_name, evaluator in ALPHA_EVALUATORS.items():
            result = evaluator(row, feats, history, thresholds[alpha_name])
            diagnostics[alpha_name]["eligible_markets"] += 1
            diagnostics[alpha_name]["scores"].append(float(result.get("score", 0.0)))
            diagnostics[alpha_name]["predicted_clvs"].append(float(result.get("predicted_clv", 0.0)))
            if result["passed"]:
                diagnostics[alpha_name]["pass_count"] += 1
            else:
                diagnostics[alpha_name]["failure_reasons"][result["reason"]] += 1

    for payload in diagnostics.values():
        scores = np.asarray(payload.pop("scores"), dtype=float)
        clvs = np.asarray(payload.pop("predicted_clvs"), dtype=float)
        payload["score_stats"] = {
            "mean": round(float(scores.mean()), 4) if scores.size else 0.0,
            "p50": round(float(np.quantile(scores, 0.50)), 4) if scores.size else 0.0,
            "p80": round(float(np.quantile(scores, 0.80)), 4) if scores.size else 0.0,
            "max": round(float(scores.max()), 4) if scores.size else 0.0,
        }
        payload["predicted_clv_stats"] = {
            "mean": round(float(clvs.mean()), 5) if clvs.size else 0.0,
            "p80": round(float(np.quantile(clvs, 0.80)), 5) if clvs.size else 0.0,
            "max": round(float(clvs.max()), 5) if clvs.size else 0.0,
        }
        payload["failure_reasons"] = dict(payload["failure_reasons"].most_common())

    return diagnostics


def build_alpha_signals(markets_df: pd.DataFrame, feature_map: dict, regime_map: dict, history_lookup: dict) -> list[AlphaSignal]:
    """Build public-data alpha signals from feature-ready markets only."""
    alpha_signals: list[AlphaSignal] = []
    if markets_df.empty:
        return alpha_signals

    thresholds = compute_alpha_thresholds(markets_df, feature_map, history_lookup)

    for row in markets_df.to_dict("records"):
        market_id = row["market_id"]
        feats = feature_map.get(market_id)
        history = history_lookup.get(market_id)
        if not feats or history is None or history.empty or len(history) < 5:
            continue

        regime = regime_map.get(market_id, "neutral")
        for alpha_name, evaluator in ALPHA_EVALUATORS.items():
            result = evaluator(row, feats, history, thresholds[alpha_name])
            if not result["passed"]:
                continue
            alpha_signals.append(
                _make_signal(
                    row,
                    alpha_name,
                    result["score"],
                    result["predicted_clv"],
                    result["direction"],
                    result["reason_text"],
                    regime,
                    result["feature_payload"],
                )
            )

    return alpha_signals


def aggregate_alpha_signals(alpha_signals: list[AlphaSignal]) -> list[dict]:
    """Aggregate per-market alpha predictions without affecting live sizing."""
    if not alpha_signals:
        return []

    grouped: dict[str, list[AlphaSignal]] = {}
    for signal in alpha_signals:
        grouped.setdefault(signal.market_id, []).append(signal)

    aggregates = []
    for market_id, signals in grouped.items():
        total_score = sum(signal.score for signal in signals)
        weighted_clv = sum(signal.predicted_clv * signal.score for signal in signals) / max(total_score, 1e-9)
        yes_weight = sum(signal.score for signal in signals if signal.direction == "YES")
        no_weight = sum(signal.score for signal in signals if signal.direction == "NO")
        aggregates.append(
            {
                "market_id": market_id,
                "predicted_clv_alpha": round(weighted_clv, 5),
                "direction": "YES" if yes_weight >= no_weight else "NO",
                "score": round(total_score / max(len(signals), 1), 4),
                "alpha_names": [signal.alpha_name for signal in signals],
            }
        )

    aggregates.sort(key=lambda item: item["predicted_clv_alpha"], reverse=True)
    return aggregates
