# POLYBOT — Prediction Market Shadow Trading System

> Autonomous paper trading bot for Polymarket. Generates signals, executes shadow bets, tracks CLV, and reports via Telegram.

## Overview
Brief 2-3 sentence description of what Polybot does:
- Fetches prediction markets from Polymarket's Gamma API
- Generates signals via momentum, reversal, and volume_spike strategies
- Executes paper/shadow trades, tracks performance, reports via Telegram
- Runs autonomously every 15 minutes via Railway + cron-job.org

## Architecture

### Execution Flow
```text
cron-job.org (every 15min)
  → POST /trigger → Railway Flask webhook (webhook.py)
    → run_cycle() in main.py
      → fetch_markets() → apply_filters() → run_strategies()
      → allocate() → execute_signal() → record_paper_bet()
      → settle_and_compute_clv() → send_summary() via Telegram
```

### Module Map
| Module | File | Purpose |
|--------|------|---------|
| Webhook server | webhook.py | Flask app, receives cron triggers |
| Main cycle | main.py | Orchestrates full trading cycle |
| Market data | data/markets.py | Fetches from Gamma API |
| Filters | scoring/filters.py | Liquidity, volume, price filters |
| Strategies | scoring/strategies.py | momentum, reversal, volume_spike |
| Execution | execution/engine.py | SHADOW/ACTIVE routing |
| Settlement | tracking/clv.py | CLV tracking, timeout settlement |
| Database | data/database.py | SQLite schema + queries |
| Alerts | alerts/telegram.py | All Telegram notifications |
| Config | config.py | All configurable parameters |

## Stack
- **Runtime**: Python 3.11
- **Infrastructure**: Railway (webhook server) + cron-job.org (scheduler)
- **Database**: SQLite (`polybot.db`) on Railway disk
- **Alerts**: Telegram Bot API
- **State backup**: Git commit on each Railway run
- **Dashboard**: Vercel Next.js → Railway `/api/state` endpoint
- **CI/CD**: GitHub Actions (manual trigger only via workflow_dispatch)

## Strategies
| Strategy | Signal | Regime |
|----------|--------|--------|
| momentum | Follow 24h price direction (>5% move) | trending, neutral |
| reversal | Fade large moves (>12% move) | mean_reverting, volatile |
| volume_spike | Follow unusual volume (>2x expected) | illiquid_spike, neutral |

## Key Configuration (config.py)
| Parameter | Value | Purpose |
|-----------|-------|---------|
| EDGE_THRESHOLD | 0.04 | Min 4% edge to generate signal |
| KELLY_FRACTION | 0.25 | Quarter-Kelly sizing |
| MAX_BET_PCT | 0.03 | Max 3% bankroll per bet |
| MAX_OPEN_BETS | 5 | Max simultaneous positions |
| MAX_POSITION_AGE_HOURS | 24 | Timeout stale positions |
| STOP_LOSS_PCT | 0.50 | Close if loss > 50% of bet |
| MAX_POSITIONS_PER_STRATEGY | 3 | Per-strategy concentration cap |

## Execution Modes
- **SHADOW**: Bet recorded but bankroll not reduced. Used during warmup (<30 closed bets) or when CLV is below threshold.
- **ACTIVE**: Real paper bet, bankroll decremented. Promoted when strategy CLV > -0.20 (warmup) or > -0.05 (post-warmup).

## Database Schema (key tables)
- `paper_bets` — all bets (SHADOW + ACTIVE), CLV columns, result
- `price_history` — per-market price snapshots every cycle
- `market_log` — signals generated per cycle
- `alpha_signals` — shadow alpha module results
- `decision_log` — meta decision engine audit trail
- `bankroll_log` — equity curve data points
- `bot_state` — persistent key-value store (weekly report timestamp etc.)

## State Files
| File | Purpose | Persistence |
|------|---------|-------------|
| polybot.db | All trading data | Railway disk + git backup |
| bankroll.txt | Current bankroll | Railway disk + git backup |
| regime_state.json | 3-cycle regime stability | Railway disk + git backup |
| killed_strategies.json | Permanently disabled strategies | Railway disk + git backup |
| daily_benchmarks.json | Today's activity counts | Railway disk + git backup |

## Critical Rules (Never Violate)
1. `record_paper_bet()` requires `mode="SHADOW"` or `mode="ACTIVE"`
2. ALTER TABLE migrations must be wrapped in `try/except` in `init_db()`
3. `polybot.db` is tracked in git — never gitignore it
4. Stop loss fires BEFORE resolved/stale checks in `settle_and_compute_clv()`
5. Strategy cap checks count ACTIVE bets only, not SHADOW bets
6. Weekly report timestamp stored in `bot_state` DB table, not `last_weekly.txt`

## Known Failure Modes
| Symptom | Cause | Fix |
|---------|-------|-----|
| POST /trigger returns 500 | Missing Flask import in webhook.py | Add `request` to Flask imports |
| POST /trigger returns 401 | WEBHOOK_SECRET set but not sent by cron | Remove auth check from webhook.py |
| Bot stuck in SHADOW mode | CLV below threshold, stats=None during warmup | Warmup gate: n_closed<30 → ACTIVE |
| Bankroll shows $1000 always | git rebase overwriting bankroll.txt | Use `-X ours` rebase strategy |
| Weekly report spamming | last_weekly.txt reset by git | Use bot_state DB table instead |
| 0 signals | market_id accessed wrong in strategies.py | Use row["market_id"] not variable |

## Dashboard
Live monitoring at: `https://polybot-prediction-system.vercel.app`

Reads from Railway's `/api/state` endpoint. Shows:
- Bankroll + equity curve
- Open/closed positions
- Strategy performance
- CLV tracking

## Local Development
```bash
pip install -r requirements.txt
cp .env.example .env  # Add Telegram credentials
python main.py         # Single run
python main.py --loop  # Every 30 min
python main.py --backtest  # Walk-forward backtest
```

## Environment Variables
| Variable | Required | Purpose |
|----------|----------|---------|
| TELEGRAM_TOKEN | Yes | Bot API token |
| TELEGRAM_CHAT_ID | Yes | Target chat ID |
| BANKROLL | No | Starting bankroll (default 1000) |
| WEBHOOK_SECRET | No | Removed — not used |
