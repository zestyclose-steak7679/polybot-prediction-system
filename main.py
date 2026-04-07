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

for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ[proxy_key] = ""

for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

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
from data.price_history   import log_prices, get_history, purge_old_history
from data.features        import build_features
from data.regime_features import compute_regime_features
from scoring.filters      import apply_filters
from scoring.strategies   import run_strategies
from models.edge_model    import edge_model
from models.clv_model     import clv_model
from models.meta_model    import meta_model, MIN_SAMPLES as META_MIN_SAMPLES
from models.regime_model  import regime_model
from portfolio.allocator  import allocate
from portfolio.risk_manager import apply_risk_constraints
from portfolio.strategy_weights import compute_sharpe_weights, get_strategy_weight_gate
from tracking.clv         import settle_and_compute_clv, clv_report
from learning.tracker     import get_active_strategies, get_all_strategy_stats
from learning.online_trainer import run_if_due
from learning.drift_monitor  import compute_drift_multiplier
from learning.alpha_diagnostics import collect_alpha_diagnostics, log_alpha_diagnostics
from learning.regime_stability import get_stable_regime
from risk.controls        import run_all_checks
from risk.strategy_killer import get_killed_strategies
from risk.drawdown_controller import get_size_multiplier
from alerts.telegram      import (send_pick_alert, send_summary,
                                   send_startup, send_error, send_risk_halt)
from strategies.router    import StrategyRouter

BANKROLL_FILE = Path("bankroll.txt")
router = StrategyRouter()


def load_bankroll() -> float:
    try:
        return float(BANKROLL_FILE.read_text().strip())
    except Exception:
        return BANKROLL

def save_bankroll(amount: float):
    BANKROLL_FILE.write_text(str(round(amount, 2)))


def model_mode() -> str:
    edge_mode = "ML" if edge_model.is_trained else "H"
    clv_mode = "+" if clv_model.is_trained else "-"
    meta_mode = "+" if meta_model.is_trained else "-"
    return f"{edge_mode}/CLV{clv_mode}/META{meta_mode}"


def run_cycle(bankroll: float, startup: bool = False) -> float:
    cycle_ts = datetime.now(UTC).replace(tzinfo=None).isoformat()
    logger.info("=" * 65)
    logger.info("CYCLE | %s | $%.2f", cycle_ts, bankroll)

    if startup:
        send_startup()

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

    position_stats = get_open_position_stats()
    cycle_metrics["open_bets"] = position_stats["n_open"]
    cycle_metrics["avg_hold_hours"] = position_stats["avg_hold_hours"]

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
    drift_mult, _ = compute_drift_multiplier()
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
    df = apply_filters(raw_df)
    logger.info("Markets after filters: %s", len(df))
    if df.empty:
        logger.warning("No markets passed filters")
        save_bankroll(bankroll)
        return bankroll

    # 6. Price history
    log_prices(df)
    purge_old_history(days=30)

    # 7-8. Features + regime per market
    feature_map, history_map, regime_map, regime_vecs = {}, {}, {}, []
    for _, row in df.iterrows():
        mid     = row["market_id"]
        history = get_history(mid, last_n=20)
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

    logger.info(f"Markets with sufficient history: {len(feature_map)}")
    if not feature_map:
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
        feats = feature_map.get(sig.market_id)
        if not feats:
            continue

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
        combined = 0.45 * sig.edge + 0.30 * clv_pred + 0.15 * mw * sig.edge + 0.10 * sw * sig.edge
        sig.edge = round(combined, 4)

        if sig.edge >= EDGE_THRESHOLD:
            enhanced.append(sig)

    avg_enhanced_edge = float(np.mean([sig.edge for sig in enhanced])) if enhanced else 0.0
    cycle_metrics["enhanced_signals"] = len(enhanced)
    cycle_metrics["blocked_by_threshold"] = max(len(signals) - len(enhanced), 0)
    logger.info(f"Enhanced signals: {len(enhanced)} | Avg edge: {avg_enhanced_edge:.4f}")

    # 12. Drawdown + drift multipliers
    dd_mult, dd_status = get_size_multiplier(bankroll)
    total_mult = dd_mult * drift_mult
    logger.info(f"Size multipliers: DD={dd_mult:.2f} Drift={drift_mult:.2f} Total={total_mult:.2f}")

    # 13. Portfolio + risk
    allocations = allocate(enhanced, bankroll)
    sigs_list   = [a["signal"] for a in allocations]
    sizes_list  = [a["bet_size"] * total_mult for a in allocations]
    sizes_list  = apply_risk_constraints(sigs_list, sizes_list, bankroll)
    cycle_metrics["blocked_by_risk"] = max(len(enhanced) - sum(1 for size in sizes_list if size > 0), 0)
    logger.info(
        f"Trade candidates after risk: {sum(1 for size in sizes_list if size > 0)} | "
        f"Total exposure: ${sum(sizes_list):.2f}"
    )

    # 14. Alert + log
    new_alerts = 0
    for alloc, bet_size in zip(allocations, sizes_list):
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
        send_pick_alert(signal_dict, bankroll)
        record_alert(sig.market_id, sig.question, sig.side, sig.strategy, sig.edge)

        bet_id = record_paper_bet(
            market_id=sig.market_id, question=sig.question,
            strategy_tag=sig.strategy, side=sig.side,
            entry_price=sig.price, bet_size=bet_size,
            bankroll=bankroll, kelly_raw=alloc["kelly_raw"],
            edge_est=sig.edge, confidence=sig.confidence, reason=sig.reason,
        )
        if bet_id and feature_map.get(sig.market_id):
            save_feature_snapshot(bet_id, sig.market_id,
                                  json.dumps(feature_map[sig.market_id]))
        bankroll -= bet_size
        new_alerts += 1

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

    save_bankroll(bankroll)
    logger.info(f"END | ${bankroll:.2f} | alerts={new_alerts} | regime={dom_regime} | {mmode}")
    return bankroll


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop",     action="store_true")
    parser.add_argument("--backtest", action="store_true")
    args = parser.parse_args()

    init_db()
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
