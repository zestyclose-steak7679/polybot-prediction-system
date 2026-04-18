# POLYBOT — AI Coding Agent Reference

## System Overview
Polybot is a prediction market shadow trading bot that operates as a GitHub Actions runner. It utilizes SQLite for local persistence (which is checked directly into the git repository) and dispatches real-time execution and summary alerts via Telegram.

## Module Map
| Module | File | Purpose |
| ------ | ---- | ------- |
| ExecutionEngine | execution/engine.py | SHADOW/ACTIVE routing, duplicate bet prevention, invokes `record_paper_bet`. |
| record_paper_bet | data/database.py | `INSERT` into `paper_bets`, requires a `mode` parameter. |
| settle_and_compute_clv | tracking/clv.py | Closes open bets, handles timeouts, and calculates Closing Line Value (CLV). |
| get_active_strategies | learning/tracker.py | The kill guard. Requires a minimum of 10 bets before evaluating a strategy for disablement. |
| send_summary | alerts/telegram.py | Renders the 3-state strategy display (Active/Filtered/Disabled) and requires the `benchmark_data` param for accurate daily counts. |
| confidence_multiplier | scoring/engine.py | Applies a conservative bet size scalar ranging from 0.5x to 1.5x based on confidence. |
| REGIME_STRATEGY_MAP | strategies/router.py | Handles routing strategies based on the current detected market regime. |
| BacktestEngine | backtest/engine.py | Executes walk-forward testing; triggered via the `python main.py --backtest` flag. |
| init_db | data/database.py | Applies SQL schema upgrades and `ALTER TABLE` migrations wrapped in `try/except` blocks. |

## Critical Rules (Never Violate)
1. `record_paper_bet()` requires a explicit `mode="SHADOW"` or `mode="ACTIVE"` parameter.
2. The SHADOW execution block must check the database for duplicate bets BEFORE `_notify_outcome` fires.
3. `ALTER TABLE` migrations must always be wrapped in `try/except` blocks within `init_db()`.
4. `paper_bets` is gitignored — however, the actual DB file `polybot.db` persists via git commit in the CI workflow.
5. Kill guard constraint: `if n_bets < 10` → `active.append(strategy); continue`
6. `send_summary` requires the `tracker_active=` and `benchmark_data=` parameters.
7. `confidence_multiplier` lives in `scoring/engine.py`, NOT `scoring/strategies.py`.
8. Never use `--force-with-lease` for state commits inside the CI workflow — use plain `push` (e.g., `git push origin HEAD:main`).

## Known Failure Modes
- **ImportError on confidence_multiplier:** Check that the import is pointing to `scoring/engine.py`.
- **DB empty after run:** Check the `Persist state` git step in `bot.yml` to ensure `polybot.db` is being explicitly added and pushed.
- **Strategy shows disabled:** Check that the `n_bets < 10` safety guard is correctly implemented in `tracker.py`.
- **Regime shows N/A:** Ensure `clv["regime"] = dom_regime` is assigned correctly in `main.py`.
- **Bets counter wrong:** The summary reads from `benchmark_data` not `paper_bets`. Check the `benchmark_data` ingestion.

## State Files
- **polybot.db** — The primary SQLite database, committed to git each run.
- **bankroll.txt** — Tracks the current running bankroll.
- **regime_state.json** — Preserves the 3-cycle regime stability state.
- **killed_strategies.json** — Tracks permanently killed strategies and their kill reasons.
- **daily_benchmarks.json** — Tracks today's current bet and signal benchmark counts.
