# Polybot — Phase 1

Polymarket signal bot. Fetches real markets, scores them, sends Telegram alerts.
Paper trades automatically. Zero cost to run.

## Structure
```
polybot/
├── config.py              ← all settings
├── main.py                ← run this
├── requirements.txt
├── data/
│   ├── markets.py         ← Gamma API fetch (no auth)
│   └── database.py        ← SQLite
├── scoring/
│   ├── filters.py         ← hard filters (liquidity, price range)
│   └── engine.py          ← scoring + Kelly
├── alerts/
│   └── telegram.py        ← Telegram bot sender
├── execution/
│   └── paper.py           ← paper trade logger
└── .github/workflows/
    └── bot.yml            ← free 24/7 via GitHub Actions
```

---

## Setup (5 minutes)

### Step 1 — Install
```bash
pip install -r requirements.txt
```

### Step 2 — Telegram
1. Message `@BotFather` on Telegram → `/newbot` → copy token
2. Message `@userinfobot` → copy your chat ID

### Step 3 — Set environment variables

**Windows:**
```cmd
set TELEGRAM_TOKEN=your_token_here
set TELEGRAM_CHAT_ID=your_chat_id_here
set BANKROLL=1000
```

**Mac/Linux:**
```bash
export TELEGRAM_TOKEN=your_token_here
export TELEGRAM_CHAT_ID=your_chat_id_here
export BANKROLL=1000
```

### Step 4 — Run locally
```bash
# Single run (test)
python main.py

# Loop mode (runs every 30 min forever)
python main.py --loop
```

---

## Free 24/7 via GitHub Actions

1. Push this folder to a GitHub repo
2. Go to repo → Settings → Secrets → Actions
3. Add three secrets:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`  
   - `BANKROLL` (e.g. `1000`)
4. That's it — bot runs every 30 min automatically, free

Cost: 0. GitHub free tier = 2000 min/month. Bot uses ~1440 min/month.

---

## What it does (Phase 1)

✅ Fetches real Polymarket markets (sports, politics, crypto)  
✅ Filters by liquidity + volume + price range  
✅ Scores markets by momentum + price tension + efficiency  
✅ Estimates edge (conservative heuristic — no fake ML)  
✅ Calculates Kelly bet size  
✅ Sends Telegram alert with full breakdown  
✅ Logs paper bets to SQLite  
✅ Deduplicates (won't re-alert same market within 6h)  
✅ Tracks paper P&L  

❌ Does NOT place real bets (Phase 3)  
❌ Does NOT have a real prediction model (Phase 2)  

---

## Tuning (config.py)

| Variable | Default | Meaning |
|---|---|---|
| `EDGE_THRESHOLD` | 0.04 | Min 4% edge to alert |
| `KELLY_FRACTION` | 0.25 | Quarter-Kelly (conservative) |
| `MAX_BET_PCT` | 0.05 | Never bet >5% bankroll |
| `MIN_LIQUIDITY` | 500 | Min $500 liquidity |
| `ALERT_COOLDOWN_HOURS` | 6 | Don't re-alert same market |

---

## Phase roadmap

- **Phase 1 (now):** Real data + heuristic scoring + Telegram alerts + paper trades
- **Phase 2:** Real prediction model (historical data + ML)
- **Phase 3:** Live execution via Polymarket CLOB API
