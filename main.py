"""
main.py — Polybot Full Autonomous System (Final)
python main.py           → single run
python main.py --loop    → every 30 min
python main.py --backtest → walk-forward backtest
python dashboard/server.py → http://localhost:8080
"""
import os
import sys
import time
import json
import logging
import argparse
from pathlib import Path
from datetime import UTC, datetime
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))

for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ[proxy_key] = ""

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import os
os.makedirs("logs", exist_ok=True)
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/polybot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("polybot.main")

from config import BANKROLL, EDGE_THRESHOLD
from alpha import aggregate_alpha_signals, build_alpha_signals, evaluate_alpha_modules, resolve_alpha_signals
from data.database        import (init_db, was_recently_alerted, record_alert,
                                    log_market, record_paper_bet, save_feature_snapshot,
                                    get_closed_bets, get_pnl_summary, log_alpha_signals,
                                    get_open_position_stats,
                                    get_alpha_outcomes)
from data.markets         import fetch_markets
from data.price_history   import log_prices, get_history, get_history_bulk, purge_old_history
from data.features        import build_features
from data.regime_features import compute_regime_features
from scoring.filters      import apply_filters, apply_diversity_filter
from scoring.strategies   import run_strategies
from scoring.engine       import compute_confidence
from models.edge_model    import edge_model
from models.clv_model     import clv_model
from models.meta_model    import meta_model, MIN_SAMPLES as META_MIN_SAMPLES
from models.regime_model  import regime_model
from portfolio.allocator  import allocate
from portfolio.risk_manager import apply_risk_constraints
from portfolio.strategy_weights import compute_sharpe_weights, get_strategy_weight_gate
from tracking.clv         import settle_and_compute_clv, clv_report, log_predicted_clv
from learning.tracker     import get_active_strategies, get_all_strategy_stats
from learning.online_trainer import run_if_due
from learning.drift_monitor  import compute_drift_multiplier, compute_edge_decay
from learning.alpha_diagnostics import collect_alpha_diagnostics, log_alpha_diagnostics
from learning.regime_stability import get_stable_regime
from learning.adaptation import adaptation_engine
from risk.controls        import run_all_checks
from risk.strategy_killer import get_killed_strategies, revive_eligible_strategies
from risk.drawdown_controller import get_size_multiplier
from meta.decision_engine import DecisionEngine
from alerts.telegram      import (send_pick_alert, send_summary,
                                  send_risk_halt, send_startup, send_error,
                                  send_weekly_report, send_positions_update)
from strategies.router    import StrategyRouter
from execution.engine     import ExecutionEngine
from utils.logger         import get_structured_logger

_LAST_HISTORY_ALERT = None
BANKROLL_FILE = Path("bankroll.txt")
router = StrategyRouter()


def load_bankroll() -> float:
    try:
        return float(BANKROLL_FILE.read_text().strip())
    except Exception:
        return float(BANKROLL)

def save_bankroll(amount: float):
    try:
        BANKROLL_FILE.write_text(str(round(amount, 2)))
    except Exception as e:
        logger.warning(f"Could not save bankroll: {e}")


def model_mode() -> str:
    edge_mode = "ML" if edge_model.is_trained else "H"
    clv_mode = "+" if clv_model.is_trained else "-"
    meta_mode = "+" if meta_model.is_trained else "-"
    return f"{edge_mode}/CLV{clv_mode}/META{meta_mode}"


struct_logger = get_structured_logger("main.pipeline")

def run_cycle(bankroll: float, startup: bool = False) -> float:
    cycle_ts = datetime.now(UTC).replace(tzinfo=None).isoformat()
    logger.info("=" * 65)
    logger.info("CYCLE | %s | $%.2f", cycle_ts, bankroll)
    struct_logger.info("cycle_start", "all", "success", {"bankroll": bankroll})

    if startup:
        send_startup(bankroll)

    cycle_metrics = {
        "raw_markets": 0,
        "raw_signals": 0,
        "enhanced_signals": 0,
        "executed_trades": 0,
        "blocked_by_open_cap": 0,
        "blocked_by_threshold": 0,
        "blocked_by_risk": 0,
        "open_bets": 0,
        "avg_hold_hours": 0.0,
        "closed_this_cycle": 0,
        "timeout_closed_this_cycle": 0,
        "clv_resolved_this_cycle": 0,
        "triggered_shadow_signals": 0,
        "resolved_alpha_count": 0,
    }

    # 1. Settle resolved/stale positions first so capital is current before risk checks.
    bankroll, settlement_stats = settle_and_compute_clv(bankroll)
    cycle_metrics["closed_this_cycle"] = settlement_stats["closed_count"]
    cycle_metrics["timeout_closed_this_cycle"] = settlement_stats["timeout_closed_count"]
    cycle_metrics["clv_resolved_this_cycle"] = settlement_stats["clv_resolved_count"]
    if settlement_stats["closed_count"] > 0:
        logger.info(
            "Settlement | closed=%s timeout=%s returned=$%.2f avg_clv=%s",
            settlement_stats["closed_count"],
            settlement_stats["timeout_closed_count"],
            settlement_stats["returned_capital"],
            settlement_stats["avg_clv_closed"],
        )

    # 1.5 Evaluate Decision Quality
    try:
        from learning.decision_evaluator import process_decision_evaluations
        process_decision_evaluations()
    except Exception as e:
        logger.error(f"Error during decision evaluation: {e}")

    position_stats = get_open_position_stats()
    cycle_metrics["open_bets"] = position_stats["n_open"]
    cycle_metrics["avg_hold_hours"] = position_stats["avg_hold_hours"]

    # Send open positions update to Telegram
    from data.database import get_open_positions_detail
    open_positions_df = get_open_positions_detail()
    if not open_positions_df.empty:
        send_positions_update(open_positions_df)

    # 2. Risk checks
    risk_ok, risk_msgs = run_all_checks(bankroll)
    for m in risk_msgs: logger.info(m)
    if not risk_ok:
        if "Max open bets reached" in risk_msgs[-1]:
            cycle_metrics["blocked_by_open_cap"] = position_stats["n_open"]
            logger.info(
                "Cycle feedback | blocked_by_open_cap=%s open_bets=%s avg_hold=%.1fh stale=%s",
                cycle_metrics["blocked_by_open_cap"],
                position_stats["n_open"],
                position_stats["avg_hold_hours"],
                position_stats["stale_count"],
            )
        send_risk_halt(risk_msgs[-1], bankroll)
        save_bankroll(bankroll)
        return bankroll

    # 3. Retrain models
    run_if_due(edge_model, clv_model, meta_model)

    # 4. Feature drift check
    adaptation_engine.run_cycle_updates()
    drift_result = compute_drift_multiplier()
    drift_mult = drift_result[0] if isinstance(drift_result, tuple) else float(drift_result)
    if drift_mult < 1.0:
        logger.warning(f"Feature drift detected → size multiplier {drift_mult:.2f}")

    # 5. Fetch + filter
    raw_df = fetch_markets()
    cycle_metrics["raw_markets"] = len(raw_df)
    logger.info("Raw markets fetched: %s", len(raw_df))
    if raw_df.empty:
        send_error("No markets survived API intake. Check tag matching and upstream filters.")
        save_bankroll(bankroll)
        return bankroll
    resolved_alpha = resolve_alpha_signals(raw_df)
    cycle_metrics["resolved_alpha_count"] = resolved_alpha
    if resolved_alpha:
        logger.info("Alpha outcomes resolved this cycle: %s", resolved_alpha)

    # Log prices for ALL fetched markets FIRST — before filtering
    # This maximises history accumulation and ensures apply_filters
    # and feature builder both see current data in the same cycle.
    log_prices(raw_df)
    purge_old_history(days=30)

    df = apply_filters(raw_df)
    df = apply_diversity_filter(df)
    logger.info("Markets after filters and diversity: %s", len(df))
    if df.empty:
        logger.warning("No markets passed filters")
        save_bankroll(bankroll)
        return bankroll

    # 6. Price history

    # 7-8. Features + regime per market
    feature_map, history_map, regime_map, regime_vecs = {}, {}, {}, []

    from alpha.signals import MIN_HISTORY_REQUIRED
    market_ids = df["market_id"].tolist()
    bulk_history = get_history_bulk(market_ids, last_n=MIN_HISTORY_REQUIRED)

    for row in df.to_dict("records"):
        try:
            mid     = row["market_id"]
            history = bulk_history.get(mid, pd.DataFrame())
            feats   = build_features(row, history)
            if not feats:
                continue
            feature_map[mid] = feats
            history_map[mid] = history
            prices  = history["yes_price"].values if not history.empty else np.array([])
            volumes = history["volume"].values if not history.empty and "volume" in history.columns else np.array([])
            rf      = compute_regime_features(prices, volumes)
            raw_regime   = regime_model.predict(rf)
            stable_regime = get_stable_regime(raw_regime)   # 3-cycle confirmation
            regime_map[mid] = stable_regime
            regime_vecs.append([rf["volatility"], rf["trend_strength"],
                                 rf["autocorr"],   rf["vol_spike"],
                                 rf["price_range"]])
        except Exception as e:
            logger.warning("Market %s skipped due to error: %s", row.get("market_id", "?"), e)
            continue

    logger.info(f"Markets with sufficient history: {len(feature_map)}")
    if not feature_map:
        global _LAST_HISTORY_ALERT
        now = time.time()
        if _LAST_HISTORY_ALERT is None or (now - _LAST_HISTORY_ALERT) > 1800:
            send_error("⚠️ POLYBOT: 0 markets with sufficient price history. Cycle skipped. Check data pipeline.")
            _LAST_HISTORY_ALERT = now
        logger.info("Waiting for more price history before generating feature-driven signals.")
        save_bankroll(bankroll)
        return bankroll

    # Online regime learning
    if regime_vecs:
        try:
            regime_model.partial_fit(np.array(regime_vecs))
        except Exception:
            pass

    feature_ready_df = df[df["market_id"].isin(feature_map.keys())].reset_index(drop=True)

    alpha_diagnostics = collect_alpha_diagnostics(feature_ready_df, feature_map, history_map)
    log_alpha_diagnostics(logger, alpha_diagnostics)
    alpha_diag_summary = "; ".join(
        f"{name}: eligible={payload.get('eligible_markets', 0)} triggered={payload.get('pass_count', 0)} blockers={','.join(list(payload.get('failure_reasons', {}).keys())[:2]) or 'none'}"
        for name, payload in alpha_diagnostics.items()
    )
    if alpha_diag_summary:
        logger.info("Alpha feedback | %s", alpha_diag_summary)

    try:
        from alpha.quant_engine import run_quant_pipeline
        run_quant_pipeline(feature_ready_df, feature_map, history_map)
    except Exception as e:
        logger.warning(f"Quant pipeline shadow evaluation failed: {e}")

    alpha_signals = build_alpha_signals(feature_ready_df, feature_map, regime_map, history_map)
    logged_alpha = log_alpha_signals(alpha_signals, cycle_ts=cycle_ts)
    cycle_metrics["triggered_shadow_signals"] = logged_alpha
    alpha_aggregate = aggregate_alpha_signals(alpha_signals)
    alpha_stats = list(evaluate_alpha_modules(get_alpha_outcomes()).values())
    avg_alpha_clv = float(np.mean([sig.predicted_clv for sig in alpha_signals])) if alpha_signals else 0.0
    top_alpha_names = ", ".join(sorted({sig.alpha_name for sig in alpha_signals})) if alpha_signals else "none"
    logger.info(
        "Shadow alpha: %s logged | avg predicted CLV %.5f | modules: %s",
        logged_alpha,
        avg_alpha_clv,
        top_alpha_names,
    )
    if alpha_aggregate:
        logger.info(
            "Top alpha candidate: %s | %s | %.5f | %s",
            alpha_aggregate[0]["market_id"],
            alpha_aggregate[0]["direction"],
            alpha_aggregate[0]["predicted_clv_alpha"],
            ",".join(alpha_aggregate[0]["alpha_names"]),
        )

    # 9. Strategy selection
    killed          = get_killed_strategies()

    # Check for revivals
    sstats = get_all_strategy_stats()
    stats_dict = {s["strategy"]: s for s in sstats}
    revived = revive_eligible_strategies(list(killed), stats_dict)

    # If any revived, remove them from killed list logic
    import json
    from risk.strategy_killer import _load_killed, _save_killed
    if revived:
        klog = _load_killed()
        for r in revived:
            klog.pop(r, None)
            killed.discard(r)
        _save_killed(klog)

    base_active     = get_active_strategies()
    available       = [s for s in base_active if s not in killed] or base_active
    regimes         = list(regime_map.values())
    dom_regime      = max(set(regimes), key=regimes.count) if regimes else "neutral"
    routed          = router.select(dom_regime, available)
    logger.info(f"Regime: {dom_regime} | Active: {routed} | Killed: {killed or '∅'}")

    # 10. Signals
    signals = run_strategies(feature_ready_df, routed)
    cycle_metrics["raw_signals"] = len(signals)
    avg_signal_edge = float(np.mean([sig.edge for sig in signals])) if signals else 0.0
    logger.info(f"Signals generated: {len(signals)} | Avg edge: {avg_signal_edge:.4f}")

    # 11. Model edge + meta weights
    closed_bets    = get_closed_bets()
    weight_gate = get_strategy_weight_gate(closed_bets, routed)
    sharpe_weights = compute_sharpe_weights(closed_bets) if weight_gate["active"] else {}
    if not weight_gate["active"]:
        logger.info("Strategy weighting in research mode: %s", weight_gate["reason"])
    meta_weight_active = meta_model.is_trained and int(closed_bets["clv"].notna().sum()) >= META_MIN_SAMPLES if not closed_bets.empty and "clv" in closed_bets.columns else False
    if meta_model.is_trained and not meta_weight_active:
        logger.info("Meta-model held observational: need %s CLV-resolved bets", META_MIN_SAMPLES)
    enhanced = []

    for sig in signals:
        try:
            feats = feature_map.get(sig.market_id)
            if not feats:
                continue

            market_row = df[df["market_id"] == sig.market_id].iloc[0] if not df.empty else pd.Series(dtype=float)
            history_df = get_history(sig.market_id) if sig.market_id in [s.market_id for s in signals] else pd.DataFrame()
            sig.confidence = compute_confidence(sig, market_row, history_df)

            model_feats = {
                **feats,
                "price": sig.price, "edge_est": sig.edge,
                "confidence": sig.confidence,
                "liquidity": sig.liquidity, "volume": sig.volume,
                "one_day_change": sig.one_day_change,
            }

            equal_weight = 1 / max(len(routed), 1)
            meta_w   = meta_model.predict_weights(model_feats, routed) if meta_weight_active else {name: equal_weight for name in routed}
            sw       = sharpe_weights.get(sig.strategy, equal_weight) if weight_gate["active"] else equal_weight
            clv_pred = clv_model.predict(model_feats)

            ep = edge_model.predict_prob(feats)
            if ep != sig.price:
                sig.confidence = round(ep, 4)
                sig.edge       = round(ep - sig.price, 4)

            mw = meta_w.get(sig.strategy, 1/max(len(routed),1))

            if not edge_model.is_trained and not clv_model.is_trained:
                # Models not ready — pass raw heuristic edge directly
                if sig.edge >= EDGE_THRESHOLD:
                    enhanced.append(sig)
                continue

            if clv_model.is_trained:
                combined = (0.45 * sig.edge
                            + 0.30 * clv_pred
                            + 0.15 * mw * sig.edge
                            + 0.10 * sw * sig.edge)
            else:
                combined = (0.60 * sig.edge
                            + 0.25 * mw * sig.edge
                            + 0.15 * sw * sig.edge)
            sig.edge = round(combined, 4)

            if sig.edge >= EDGE_THRESHOLD:
                enhanced.append(sig)
        except Exception as e:
            logger.warning("Signal %s skipped during enhancement: %s", sig.market_id, e)
            continue

    avg_enhanced_edge = float(np.mean([sig.edge for sig in enhanced])) if enhanced else 0.0
    valid_confs = [sig.confidence for sig in enhanced if getattr(sig, "confidence", None) is not None]
    avg_confidence = float(np.mean(valid_confs)) if valid_confs else None
    cycle_metrics["enhanced_signals"] = len(enhanced)
    cycle_metrics["blocked_by_threshold"] = max(len(signals) - len(enhanced), 0)
    cycle_metrics["avg_confidence"] = avg_confidence
    logger.info(f"Enhanced signals: {len(enhanced)} | Avg edge: {avg_enhanced_edge:.4f}")

    # 12. Drawdown + drift multipliers
    dd_mult, dd_status = get_size_multiplier(bankroll)
    decay_result = compute_edge_decay()
    decay = decay_result if isinstance(decay_result, dict) else (decay_result[1] if isinstance(decay_result, tuple) and len(decay_result) > 1 else {"decay_factor": 1.0, "status": "ok"})
    total_mult = dd_mult * drift_mult * decay["decay_factor"]
    logger.info(
        "Size multipliers: DD=%.2f Drift=%.2f Decay=%.2f Total=%.2f | Decay status: %s",
        dd_mult, drift_mult, decay["decay_factor"], total_mult, decay["status"]
    )

    # 13. Portfolio + risk
    allocations = allocate(enhanced, bankroll)
    sigs_list   = [a["signal"] for a in allocations]
    sizes_list  = [a["bet_size"] * total_mult * getattr(a["signal"], "adaptive_multiplier", 1.0) for a in allocations]
    sizes_list  = apply_risk_constraints(sigs_list, sizes_list, bankroll)
    cycle_metrics["blocked_by_risk"] = max(len(enhanced) - sum(1 for size in sizes_list if size > 0), 0)

    # 13.5 Meta Decision Engine Evaluates Trades
    decision_engine = DecisionEngine()
    sstats  = get_all_strategy_stats()
    agent_metrics = {s["strategy"]: s for s in sstats}
    risk_state = {"is_reduced": dd_mult < 1.0}
    decisions = decision_engine.evaluate_trade(sigs_list, agent_metrics, dom_regime, risk_state)

    from data.database import record_decision
    for i, dec in enumerate(decisions):
        if dec["action"] == "SKIP":
            sizes_list[i] = 0.0
            logger.info(f"DECISION_ENGINE | {sigs_list[i].market_id} | SKIPPED: {dec['reason']}")
        elif dec["action"] == "REDUCE":
            sizes_list[i] *= dec["confidence"]
            logger.info(f"DECISION_ENGINE | {sigs_list[i].market_id} | REDUCED size by {dec['confidence']}: {dec['reason']}")

        record_decision(
            market_id=sigs_list[i].market_id,
            agent_id=dec["selected_agent"],
            decision=dec["action"],
            reason=dec["reason"],
            confidence=dec["confidence"],
            bet_size_before=sizes_list[i] if dec["action"] != "REDUCE" else sizes_list[i] / dec["confidence"],
            bet_size_after=sizes_list[i]
        )

    logger.info(
        f"Trade candidates after risk and meta decisions: {sum(1 for size in sizes_list if size > 0)} | "
        f"Total exposure: ${sum(sizes_list):.2f}"
    )

    # 14. Alert + log
    new_alerts = 0
    for alloc, bet_size in zip(allocations, sizes_list):
        engine = ExecutionEngine(bankroll)
        sig    = alloc["signal"]
        regime = regime_map.get(sig.market_id, dom_regime)

        log_market(sig.market_id, sig.question, sig.price,
                   sig.liquidity, sig.volume, sig.one_day_change,
                   sig.strategy, sig.edge, regime)

        if was_recently_alerted(sig.market_id):
            continue
        if bet_size <= 0:
            continue

        signal_dict = {**sig.__dict__, "bet_size": bet_size,
                       "kelly_raw": alloc["kelly_raw"],
                       "decimal_odds": alloc["decimal_odds"]}

        logger.info(f"ALERT | {sig.strategy}/{regime} | {sig.side} "
                    f"'{sig.question[:45]}' edge={sig.edge:.3f} ${bet_size:.2f}")

        record_alert(sig.market_id, sig.question, sig.side, sig.strategy, sig.edge)


        bet_id, exec_status = engine.execute_signal(
            signal=sig,
            bet_size=bet_size,
            kelly_raw=alloc["kelly_raw"],
            decimal_odds=alloc["decimal_odds"]
        )

        if bet_id and exec_status == "success":
            if feature_map.get(sig.market_id):
                save_feature_snapshot(bet_id, sig.market_id,
                                      json.dumps(feature_map[sig.market_id]))

                # Recompute predicted clv for logging to avoid variable scoping issues from loop above
                pred_clv = clv_model.predict(feature_map[sig.market_id]) if clv_model.is_trained else 0.0
                log_predicted_clv(
                    market_id=sig.market_id,
                    entry_price=sig.price,
                    predicted_clv=pred_clv,
                    signal_edge=sig.edge,
                    strategy=sig.strategy,
                    cycle_ts=cycle_metrics.get("cycle_start", datetime.now(UTC).replace(tzinfo=None).isoformat())
                )
            bankroll -= bet_size
            new_alerts += 1
        elif exec_status == "shadow":
            new_alerts += 1 # We still consider it processed

    cycle_metrics["executed_trades"] = new_alerts
    position_stats = get_open_position_stats()
    cycle_metrics["open_bets"] = position_stats["n_open"]
    cycle_metrics["avg_hold_hours"] = position_stats["avg_hold_hours"]

    # 15. Summary
    clv     = clv_report()
    stats   = get_pnl_summary()
    sstats  = get_all_strategy_stats()
    cycle_metrics["alpha_resolved_total"] = sum(alpha["n"] for alpha in alpha_stats) if alpha_stats else 0
    mmode = model_mode()
    send_summary(
        stats,
        sstats,
        bankroll,
        new_alerts,
        routed,
        model_mode=mmode,
        alpha_stats=alpha_stats,
        position_stats=position_stats,
        cycle_metrics=cycle_metrics,
        clv_stats=clv,
    )

    if clv["n"] > 0:
        logger.info(
            f"CLV | avg={clv['avg_clv']:.5f} pos={clv['positive_rate']:.1%} "
            f"sharpe={clv['clv_sharpe']:.3f} n={clv['n']}"
        )
    if alpha_stats:
        logger.info(
            "Alpha shadow leaders: %s",
            " | ".join(
                f"{alpha['alpha_name']}={alpha['avg_clv']:.5f}/n{alpha['n']}"
                for alpha in alpha_stats[:3]
            ),
        )
    logger.info(
        "Cycle feedback | raw=%s enhanced=%s executed=%s blocked_threshold=%s blocked_risk=%s open=%s avg_hold=%.1fh closed=%s timeout_closed=%s clv_closed=%s alpha_shadow=%s",
        cycle_metrics["raw_signals"],
        cycle_metrics["enhanced_signals"],
        cycle_metrics["executed_trades"],
        cycle_metrics["blocked_by_threshold"],
        cycle_metrics["blocked_by_risk"],
        cycle_metrics["open_bets"],
        cycle_metrics["avg_hold_hours"],
        cycle_metrics["closed_this_cycle"],
        cycle_metrics["timeout_closed_this_cycle"],
        cycle_metrics["clv_resolved_this_cycle"],
        cycle_metrics["triggered_shadow_signals"],
    )

    logger.info(
        "HEALTH | bankroll=$%.2f | bets=%s | win_rate=%.1f%% | avg_clv=%.4f | "
        "signals_raw=%s | signals_executed=%s | regime=%s | model=%s",
        bankroll,
        stats.get("total_bets", 0),
        stats.get("win_rate", 0.0),
        clv.get("avg_clv", 0.0),
        cycle_metrics["raw_signals"],
        cycle_metrics["executed_trades"],
        dom_regime,
        mmode,
    )

    save_bankroll(bankroll)

    from learning.benchmarks import update_benchmarks, check_benchmarks, send_benchmark_alert
    benchmark_data = update_benchmarks(
        signals=cycle_metrics["raw_signals"],
        bets=cycle_metrics["executed_trades"],
        bankroll=bankroll,
        timeouts=cycle_metrics["timeout_closed_this_cycle"],
        closes=cycle_metrics["closed_this_cycle"]
    )
    active_strategy_count = len([s for s in routed if s not in get_killed_strategies()])
    violations = check_benchmarks(benchmark_data, clv, active_strategy_count)
    if violations:
        logger.warning("BENCHMARK VIOLATIONS: %s", len(violations))
        send_benchmark_alert(violations, benchmark_data, bankroll)

    # Weekly Report
    weekly_file = Path("last_weekly.txt")
    last_weekly = 0.0
    if weekly_file.exists():
        try:
            last_weekly = float(weekly_file.read_text().strip())
        except Exception:
            pass
    now_ts = datetime.now(UTC).timestamp()
    if now_ts - last_weekly > 7 * 24 * 3600:
        logger.info("Sending weekly report...")
        period_str = f"{(datetime.now(UTC) - pd.Timedelta(days=7)).strftime('%Y-%m-%d')} to {datetime.now(UTC).strftime('%Y-%m-%d')}"
        best_strat = sstats[0]["strategy"] if sstats else "N/A"
        worst_strat = sstats[-1]["strategy"] if sstats else "N/A"
        roi = stats.get('roi', 0.0)
        weekly_stats = {
            "period": period_str,
            "bets": stats.get('total_bets', 0),
            "wins": stats.get('wins', 0),
            "losses": stats.get('losses', 0),
            "win_rate": stats.get('win_rate', 0.0),
            "roi": stats.get('roi', 0.0),
            "pnl": stats.get('total_pnl', 0.0),
            "avg_clv": clv.get("avg_clv", 0.0),
            "best_strategy": best_strat,
            "worst_strategy": worst_strat,
            "regime_dist": dom_regime,
            "bankroll": bankroll,
            "bankroll_change": stats.get('roi', 0.0),
        }

        send_weekly_report(weekly_stats)
        weekly_file.write_text(str(now_ts))

    logger.info(f"END | ${bankroll:.2f} | alerts={new_alerts} | regime={dom_regime} | {mmode}")
    return bankroll


def preflight_check() -> bool:
    """Validate all critical components before starting cycle."""
    ok = True

    # Check Telegram
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or ""
    if not token or not chat_id:
        logger.error("PREFLIGHT FAIL: Telegram credentials missing")
        ok = False
    else:
        logger.info("PREFLIGHT OK: Telegram credentials present (token: %s...)", token[:8])

    # Check bankroll
    try:
        bankroll = load_bankroll()
        logger.info("PREFLIGHT OK: Bankroll $%.2f", bankroll)
    except Exception as e:
        logger.error("PREFLIGHT FAIL: Bankroll load error: %s", e)
        ok = False

    # Check database path accessible
    try:
        init_db()
        logger.info("PREFLIGHT OK: Database initialised")
    except Exception as e:
        logger.error("PREFLIGHT FAIL: Database error: %s", e)
        ok = False

    return ok

def main():
    if not preflight_check():
        logger.error("Preflight failed — exiting")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop",     action="store_true")
    parser.add_argument("--backtest", action="store_true")
    args = parser.parse_args()

    if not Path("polybot.db").exists():
        open("polybot.db", "w").close()

    from data.price_history import init_price_history  
    init_price_history()                               
    bankroll = load_bankroll()

    if args.backtest:
        from backtest.engine import BacktestEngine
        r = BacktestEngine(initial_bankroll=bankroll).run()
        if not r.empty:
            r.to_csv("logs/backtest_results.csv", index=False)
            logger.info("→ logs/backtest_results.csv")
        return

    if args.loop:
        first = True
        while True:
            try:
                bankroll = run_cycle(bankroll, startup=first)
                first = False
            except Exception as e:
                logger.exception(f"Cycle error: {e}")
                send_error(str(e))
            logger.info("Sleeping 30 min...")
            time.sleep(30 * 60)
    else:
        run_cycle(bankroll, startup=False)


if __name__ == "__main__":
    main()
