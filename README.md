# 🤖 Polybot — Autonomous Prediction Market Trading System

> A self-improving, signal-driven trading bot for [Polymarket](https://polymarket.com) — built for learning, designed for real edge.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![GitHub Actions](https://img.shields.io/badge/hosting-GitHub%20Actions-2088FF)](https://github.com/features/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: Paper Trading](https://img.shields.io/badge/status-paper%20trading-yellow.svg)](#)

---

## What Is This?

Polybot is an automated prediction market trading system that fetches real Polymarket markets, scores them using engineered signals, manages risk with Kelly sizing, and either paper-trades or executes live. It runs 24/7 for free via GitHub Actions.

**The honest framing:** this is a learning project built with serious architectural depth. Whether it generates real profit depends entirely on whether the underlying signals have positive Closing Line Value (CLV) over time — not on the sophistication of the system around them. Architecture doesn't create alpha. Data does.

---

## System Architecture

```
[DATA ENGINE]
      ↓
[PROBABILITY ENGINE]  ← 17 engineered features, GBM meta-model
      ↓
[ALPHA ENGINE]        ← signal scoring, edge decay, shadow strategies
      ↓
[REGIME DETECTOR]     ← MiniBatchKMeans market clustering
      ↓
[RISK MANAGER]        ← Kelly sizing, drawdown control, correlation matrix
      ↓
[EXECUTION ENGINE]    ← paper trades or live CLOB orders
      ↓
[EVALUATION ENGINE]   ← CLV tracking, Sharpe, Brier score
      ↓
  (feedback loop into models)
```

### Layer 1 — Data Engine
- Polymarket Gamma API (no auth required) for market fetching
- Price history tracking across 30-minute cycles
- Stale market detection, volume validation, price history integrity checks
- SQLite persistence (`polybot.db`)

### Layer 2 — Probability Engine
- 17 engineered features: momentum ratios, z-scores, volume spike ratios, time-to-resolution, liquidity flags
- `GradientBoostingClassifier` / `GradientBoostingRegressor` trained on CLV targets (not PnL)
- Walk-forward training to prevent lookahead bias

### Layer 3 — Alpha Engine
- Three competing active strategies with Sharpe-weighted meta-model allocation
- Two shadow alpha strategies (`late_drift`, `reversion_gap`) — promoted to active when statistically validated
- Edge decay: signal scores decay as market approaches resolution
- Signal scoring pipeline with cross-market comparison

### Layer 4 — Regime Detector
- `MiniBatchKMeans` clustering for unsupervised market regime identification
- Regime state persisted to `regime_state.json`
- Bet sizing and strategy weights adjusted per regime

### Layer 5 — Risk Manager
- Quarter-Kelly sizing with configurable Kelly fraction
- Empirical correlation matrix derived from historical strategy PnL pivots
- Drawdown controller: reduces position sizes automatically under drawdown
- Feature drift monitor: flags when live feature distribution diverges from training
- Position timeout mechanism for stale open bets
- `MAX_OPEN_BETS = 8` cap with bankroll exposure tracking

### Layer 6 — Evaluation Engine
- **CLV (Closing Line Value)** is the north star metric — captured within 48-hour resolution window
- Brier score, hit rate, Sharpe ratio tracked per strategy
- Strategy killer: disables underperforming strategies after 50-bet minimum threshold + 12-hour cooldown
- Full settlement statistics with per-strategy breakdowns

---

## Repository Structure

```
polybot/
├── main.py                    ← entry point (single run, loop, backtest)
├── config.py                  ← all tunable parameters
├── requirements.txt
│
├── data/
│   ├── markets.py             ← Gamma API fetch
│   └── database.py            ← SQLite schema + queries
│
├── scoring/
│   ├── filters.py             ← hard filters (liquidity, price range)
│   ├── engine.py              ← 17-feature engineering + meta-model
│   └── features.py            ← feature extraction pipeline
│
├── alpha/
│   ├── strategies.py          ← active + shadow strategy implementations
│   ├── meta_model.py          ← Sharpe-weighted strategy allocator
│   └── regime.py              ← MiniBatchKMeans regime detector
│
├── backtest/
│   └── walk_forward.py        ← walk-forward replay engine
│
├── alerts/
│   └── telegram.py            ← Telegram Bot API alerts
│
├── tests/
│   └── ...                    ← unit + integration tests
│
└── .github/workflows/
    └── bot.yml                ← GitHub Actions (free 24/7 hosting)
```

---

## Quickstart

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure Telegram (for alerts)

1. Message `@BotFather` on Telegram → `/newbot` → copy token
2. Message `@userinfobot` → copy your chat ID

### 3. Set environment variables

```bash
# Mac/Linux
export TELEGRAM_TOKEN=your_token_here
export TELEGRAM_CHAT_ID=your_chat_id_here
export BANKROLL=1000

# Windows
set TELEGRAM_TOKEN=your_token_here
set TELEGRAM_CHAT_ID=your_chat_id_here
set BANKROLL=1000
```

### 4. Run

```bash
# Single run (test)
python main.py

# Loop mode — runs every 30 minutes
python main.py --loop

# Walk-forward backtest on historical data
python main.py --backtest

# Flask dashboard (port 8080)
python dashboard/server.py
```

---

## Free 24/7 Hosting via GitHub Actions

1. Push to a GitHub repo
2. Go to **Settings → Secrets → Actions** and add:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `BANKROLL`
3. Done — bot runs every 30 minutes, completely free

> GitHub free tier = 2000 min/month. Bot uses ~1440 min/month. Zero cost.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `EDGE_THRESHOLD` | `0.04` | Min 4% edge to place a bet |
| `KELLY_FRACTION` | `0.25` | Quarter-Kelly (conservative sizing) |
| `MAX_BET_PCT` | `0.05` | Never bet >5% bankroll per position |
| `MIN_LIQUIDITY` | `500` | Min $500 market liquidity |
| `ALERT_COOLDOWN_HOURS` | `6` | Re-alert cooldown per market |
| `MAX_OPEN_BETS` | `8` | Max simultaneous open positions |
| `STRATEGY_MIN_BETS` | `50` | Min bets before strategy can be killed |
| `CLV_WINDOW_HOURS` | `48` | Hours before resolution to capture CLV |
| `DRAWDOWN_HALT_PCT` | `0.15` | Reduce sizing at 15% drawdown |

---

## Metrics & Evaluation

The primary evaluation signal is **CLV (Closing Line Value)** — not P&L.

> CLV measures whether you bought at better odds than the market's final implied probability before resolution. Positive average CLV over 50+ bets is the only reliable signal that your edge is real and not noise.

Secondary metrics tracked per strategy:
- **Sharpe Ratio** — risk-adjusted returns
- **Brier Score** — probability calibration quality
- **Hit Rate** — raw win rate (least informative in isolation)
- **Kelly-weighted P&L** — actual paper/live profit

---

## Current Status

| Component | Status |
|---|---|
| Data pipeline | ✅ Live |
| 17-feature engineering | ✅ Live |
| Meta-model (GBM) | ✅ Live |
| Regime detection | ✅ Live |
| Kelly sizing + drawdown control | ✅ Live |
| CLV tracking | ✅ Live |
| Strategy killer | ✅ Live |
| Paper trading | ✅ Live |
| Live execution (CLOB) | 🔧 Phase 3 |
| External signals (news/Twitter) | 🔧 Future |

---

## Honest Caveats

- **Heuristic edge estimates are not calibrated probabilities.** The system's signals are engineered features, not outputs from a proper Bayesian model. Treat them accordingly.
- **50+ closed bets per strategy is the minimum** to draw any conclusions about CLV. Don't kill strategies early — that's the strategy killer's job, with its built-in cooldown.
- **58% bankroll deployment is normal**, not alarming. With `MAX_OPEN_BETS = 8` and 30-min cycles, this is expected capital accumulation across multiple positions.
- **Correlation matrix is empirical.** It's derived from historical strategy PnL and updated over time. Early estimates with few data points should be treated as rough guides only.

---

## Roadmap

**Phase 1 (complete):** Real data + heuristic scoring + Telegram alerts + paper trades

**Phase 2 (current):** ML models, CLV training targets, regime detection, alpha engine, risk management

**Phase 3 (next):** Live execution via Polymarket CLOB API with full Polygon wallet integration

**Phase 4 (future):** External signal ingestion (news, Twitter), cross-market arbitrage detection, ensemble probability calibration

---

## Development Notes

This project tracks CLV as its core training signal and uses walk-forward validation to prevent data leakage. The goal is not to over-engineer the system, but to accumulate enough real market observations to determine whether any of the current signals carry genuine predictive power.

If they don't, the system will tell you — that's what the strategy killer and CLV tracking are for.

---

## License

MIT — use freely, fork freely, trade responsibly.
