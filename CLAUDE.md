# POLYBOT — AI Coding Agent Reference

## System Overview
Polybot is a prediction market shadow trading bot designed to run autonomously via a scheduled GitHub Actions runner. It utilizes a file-based SQLite database for state persistence, tracks strategies and regimes over time, and dispatches detailed execution alerts and strategy summaries via Telegram.

## Module Map

| Module | File | Purpose |
| --- | --- | --- |
| ExecutionEngine | execution/engine.py | SHADOW/ACTIVE routing, record_paper_bet |
| record_paper_bet | data/database.py | INSERT into paper_bets, requires mode param |
| settle_and_compute_clv | tracking/clv.py | closes open bets, writes CLV |
| get_active_strategies | learning/tracker.py | kill guard, min 10 bets before disable |
| send_summary | alerts/telegram.py | 3-state strategy display, benchmark_data param |
| confidence_multiplier | scoring/engine.py | 0.5x-1.5x bet sizing by confidence |
| REGIME_STRATEGY_MAP | strategies/router.py | regime to strategy routing |
| BacktestEngine | backtest/engine.py | walk-forward, run via --backtest flag |
| init_db | data/database.py | ALTER TABLE migrations in try/except |

## Critical Rules (Never Violate)
1. record_paper_bet() requires mode="SHADOW" or mode="ACTIVE" parameter
2. SHADOW block must check duplicates BEFORE _notify_outcome fires
3. ALTER TABLE migrations must be wrapped in try/except in init_db()
4. paper_bets is gitignored — DB persists via git commit in workflow
5. kill guard: if n_bets < 10 → active.append(strategy); continue
6. send_summary requires tracker_active= and benchmark_data= params
7. confidence_multiplier lives in scoring/engine.py not scoring.strategies
8. Never use --force-with-lease for state commits — use plain push

## Known Failure Modes
- ImportError on confidence_multiplier → check scoring/engine.py
- DB empty after run → check git persist step in bot.yml
- Strategy shows disabled → check n_bets < 10 guard in tracker.py
- Regime shows N/A → check clv["regime"] = dom_regime in main.py
- Bets counter wrong → summary reads benchmark_data not paper_bets

## State Files
- polybot.db — SQLite, committed to git each run
- bankroll.txt — current bankroll
- regime_state.json — 3-cycle regime stability state
- killed_strategies.json — permanently killed strategies
- daily_benchmarks.json — today's bet/signal counts
