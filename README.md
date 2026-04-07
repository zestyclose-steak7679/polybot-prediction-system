Polybot — Autonomous Polymarket Prediction System
A fully autonomous paper-trading and signal bot for Polymarket. Fetches live markets, scores them with heuristic + ML models, manages a portfolio with Kelly sizing and risk controls, and sends Telegram alerts — all with zero manual intervention.
---
Architecture
```
polybot/
├── main.py                        ← entry point (single run / loop / backtest)
├── config.py                      ← all settings and thresholds
├── telegram_terminal.py           ← interactive Telegram terminal interface
├── requirements.txt
│
├── data/
│   ├── markets.py                 ← Gamma API fetch (no auth required)
│   ├── database.py                ← SQLite schema, paper bet logging, CLV tracking
│   ├── features.py                ← feature engineering (momentum, volume, ELO, H2H)
│   ├── price_history.py           ← per-market price history store
│   └── regime_features.py        ← volatility / trend / autocorrelation features
│
├── scoring/
│   ├── filters.py                 ← hard filters (liquidity, price range, volume)
│   ├── strategies.py              ← momentum / reversal / volume_spike signals
│   └── engine.py                  ← scoring pipeline + Kelly sizing
│
├── models/
│   ├── edge_model.py              ← heuristic (Mode A) → GBM (Mode B at 50+ bets)
│   ├── clv_model.py               ← closing line value predictor
│   ├── meta_model.py              ← strategy weight allocator
│   └── regime_model.py            ← unsupervised regime detector (KMeans)
│
├── alpha/
│   ├── signals.py                 ← shadow alpha signals (late_volume, reversion, spread)
│   ├── evaluator.py               ← alpha module performance tracker
│   └── tracker.py                 ← alpha outcome resolver
│
├── learning/
│   ├── tracker.py                 ← per-strategy stats and activation logic
│   ├── online_trainer.py          ← scheduled model retraining
│   ├── drift_monitor.py           ← feature drift detection → size multiplier
│   ├── alpha_diagnostics.py       ← alpha signal diagnostics per cycle
│   └── regime_stability.py        ← 3-cycle regime confirmation filter
│
├── risk/
│   ├── controls.py                ← max drawdown, open bet cap, daily loss limits
│   ├── drawdown_controller.py     ← bet size multiplier based on drawdown
│   └── strategy_killer.py         ← auto-disables underperforming strategies
│
├── portfolio/
│   ├── allocator.py               ← Kelly-based capital allocation
│   ├── risk_manager.py            ← per-signal risk constraints
│   └── strategy_weights.py        ← Sharpe-weighted strategy blending
│
├── tracking/
│   └── clv.py                     ← closing line value settlement + reporting
│
├── alerts/
│   └── telegram.py                ← pick alerts, summaries, errors, risk halts
│
├── execution/
│   └── paper.py                   ← paper trade recorder
│
├── backtest/
│   └── engine.py                  ← walk-forward backtester
│
├── dashboard/
│   └── server.py                  ← local web dashboard (localhost:8080)
│
├── strategies/
│   └── router.py                  ← regime-aware strategy selector
│
└── tests/
    ├── test_alpha.py
    ├── test_feedback_loop.py
    └── test_position_timeout.py
```
---
How It Works
Each cycle (every 30 min) runs this pipeline:
Settle — close resolved/stale positions, compute CLV on settled bets
Risk checks — halt if drawdown > 20% or open bets at cap
Retrain — auto-retrain edge/CLV/meta models if due
Drift check — detect feature distribution shift, reduce bet sizes if needed
Fetch markets — pull live Polymarket markets via Gamma API
Filter — apply hard filters (liquidity, volume, price range)
Feature engineering — build per-market features + regime vectors
Alpha signals — run shadow alpha modules (late volume, reversion, spread compression)
Strategy selection — regime-aware routing selects active strategies
Signal generation — momentum / reversal / volume_spike strategies score markets
Model enhancement — edge model + CLV model + meta-model refine signals
Portfolio allocation — Kelly sizing with Sharpe-weighted strategy blending
Risk constraints — per-signal position limits applied
Alert + log — send Telegram alerts, record paper bets to SQLite
---
Models
Model	Activates	Purpose
`edge_model`	Always (heuristic) → ML at 50+ bets	Estimates true probability of YES
`clv_model`	At 30+ closed bets	Predicts expected closing line value
`meta_model`	At 100+ CLV-resolved bets	Weights strategies by predicted performance
`regime_model`	Always (KMeans, online)	Classifies market into neutral/trending/volatile/mean-reverting
---
Setup
Step 1 — Install dependencies
```bash
pip install -r requirements.txt
```
Step 2 — Telegram bot
Message `@BotFather` on Telegram → `/newbot` → copy token
Message `@userinfobot` → copy your chat ID
Step 3 — Environment variables
Mac/Linux:
```bash
export TELEGRAM_TOKEN=your_token_here
export TELEGRAM_CHAT_ID=your_chat_id_here
export BANKROLL=1000
```
Windows:
```cmd
set TELEGRAM_TOKEN=your_token_here
set TELEGRAM_CHAT_ID=your_chat_id_here
set BANKROLL=1000
```
Step 4 — Run
```bash
# Single cycle (test)
python main.py

# Autonomous loop (every 30 min)
python main.py --loop

# Walk-forward backtest
python main.py --backtest

# Local dashboard
python dashboard/server.py   # → http://localhost:8080

# Interactive Telegram terminal
python telegram_terminal.py
```
---
Free 24/7 via GitHub Actions
Push this repo to GitHub
Go to Settings → Secrets → Actions and add:
`TELEGRAM_TOKEN`
`TELEGRAM_CHAT_ID`
`BANKROLL`
Bot runs every 30 min automatically on GitHub's free tier
GitHub free tier = 2,000 min/month. Bot uses ~1,440 min/month.
---
Configuration (`config.py`)
Edge & Sizing
Variable	Default	Meaning
`EDGE_THRESHOLD`	`0.04`	Minimum 4% estimated edge to generate a signal
`KELLY_FRACTION`	`0.25`	Quarter-Kelly staking (conservative)
`MAX_BET_PCT`	`0.03`	Never bet more than 3% of bankroll per signal
Risk Controls
Variable	Default	Meaning
`MAX_DRAWDOWN_PCT`	`0.20`	Halt all betting if bankroll drops 20% from peak
`MAX_OPEN_BETS`	`8`	Maximum simultaneous paper bets
`MAX_POSITION_AGE_HOURS`	`6`	Recycle capital from stale open positions
`STRATEGY_MIN_ROI`	`-0.05`	Auto-disable strategy if ROI drops below -5%
`MIN_BETS_TO_EVAL`	`10`	Don't evaluate a strategy until it has 10 bets
Market Filters
Variable	Default	Meaning
`MIN_LIQUIDITY`	`500`	Minimum $500 liquidity
`MIN_VOLUME`	`1000`	Minimum $1,000 total volume
`MIN_PRICE`	`0.05`	Ignore markets priced below 5¢ or above 95¢
`MAX_PRICE`	`0.95`	(see above)
`ALERT_COOLDOWN_HOURS`	`6`	Don't re-alert the same market within 6 hours
Strategies
Variable	Default	Meaning
`MOMENTUM_THRESHOLD`	`0.05`	5% price move required to trigger momentum signal
`REVERSAL_THRESHOLD`	`0.12`	12% move required to trigger reversal signal
`VOLUME_SPIKE_RATIO`	`2.0`	Volume must be 2× expected to trigger volume_spike
Target Markets
```python
TARGET_TAGS = [
    "sports", "cricket", "football", "soccer", "nba", "nfl",
    "tennis", "ipl", "world-cup",
    "politics", "elections", "us-politics", "india", "geopolitics",
    "crypto", "bitcoin", "ethereum", "defi",
]
```
---
Closing Line Value (CLV)
The bot tracks CLV (Closing Line Value) as its primary performance metric — whether signals beat the final market price before resolution. A positive mean CLV over 30+ bets indicates genuine edge. Negative CLV means the market was already pricing in the information.
CLV is used to:
Evaluate alpha signal quality
Gate strategy weight activation
Trigger strategy auto-kill if consistently negative
---
Tests
```bash
python -m pytest tests/
```
Covers: alpha signal pipeline, feedback loop, position timeout, bankroll loading.
---
What It Does / Doesn't Do
✅ Fetches real Polymarket markets (no auth needed)  
✅ Multi-strategy signal generation (momentum, reversal, volume spike)  
✅ Heuristic → ML edge model (auto-upgrades at 50+ closed bets)  
✅ Regime detection (neutral / trending / volatile / mean-reverting)  
✅ Kelly sizing with Sharpe-weighted strategy blending  
✅ Full risk controls (drawdown halt, open bet cap, strategy killer)  
✅ CLV tracking as primary edge metric  
✅ Shadow alpha modules (run in observation before going live)  
✅ Walk-forward backtesting  
✅ Telegram alerts + interactive terminal  
✅ Local web dashboard  
✅ Free 24/7 via GitHub Actions
❌ Does NOT place real bets (paper trading only)  
❌ Does NOT connect to Polymarket CLOB API  
❌ Does NOT guarantee edge — CLV must be validated over 30+ bets before trusting signals
---
Roadmap
Current: Full autonomous paper trading with ML edge model, CLV tracking, regime detection
Next: Player availability / news event features to capture information not priced into sharp odds
Future: Live execution via Polymarket CLOB API once positive CLV is confirmed over sufficient sample
