import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Environment ───────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or ""

# ── Bankroll ──────────────────────────────────────────────
BANKROLL = float(os.environ.get("BANKROLL", "1000"))

# ── Edge / Kelly ──────────────────────────────────────────
EDGE_THRESHOLD   = 0.04   # minimum 4% estimated edge to alert
KELLY_FRACTION   = 0.25   # quarter-Kelly (conservative)
MAX_BET_PCT      = 0.03   # never bet more than 3% of bankroll per signal

# ── Risk controls ─────────────────────────────────────────
MAX_DRAWDOWN_PCT  = 0.20  # halt all betting if bankroll drops 20% from peak
MIN_BETS_TO_EVAL  = 10    # don't judge a strategy until it has 10 bets
STRATEGY_MIN_ROI  = -0.05 # disable strategy if ROI drops below -5%
MAX_OPEN_BETS     = 5     # max simultaneous paper bets
MAX_POSITIONS_PER_STRATEGY = 3
MAX_POSITION_AGE_HOURS = 24  # recycle paper capital from stale positions
STOP_LOSS_PCT     = 0.50  # close if loss > 50% of bet size

# ── Market filters ────────────────────────────────────────
MIN_LIQUIDITY    = 500    # minimum $500 liquidity
MIN_VOLUME       = 1000   # minimum $1000 total volume
MIN_PRICE        = 0.05   # ignore markets priced < 5c or > 95c
MAX_PRICE        = 0.95

# ── Categories to track ───────────────────────────────────
TARGET_TAGS = [
    "sports", "cricket", "football", "soccer", "nba", "nfl",
    "tennis", "ipl", "world-cup",
    "politics", "elections", "us-politics", "india", "geopolitics",
    "crypto", "bitcoin", "ethereum", "defi",
]

# ── Strategy settings ─────────────────────────────────────
# momentum  : follow direction of recent price move
# reversal  : fade large moves (overreaction)
# volume_spike: follow markets with unusual activity
ACTIVE_STRATEGIES = ["momentum", "reversal", "volume_spike"]

# Thresholds per strategy
MOMENTUM_THRESHOLD     = 0.05   # 5% move required to signal
REVERSAL_THRESHOLD     = 0.12   # 12% move to bet against
VOLUME_SPIKE_RATIO     = 2.0    # volume must be 2x its "expected" based on liquidity

# ── Gamma API ─────────────────────────────────────────────
GAMMA_URL    = "https://gamma-api.polymarket.com"
MARKET_LIMIT = 100

# ── Database ──────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "/app/storage/polybot.db")

# ── State file paths ──────────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "/app/storage")
BANKROLL_FILE     = os.path.join(DATA_DIR, "bankroll.txt")
PEAK_BANKROLL_FILE = os.path.join(DATA_DIR, "peak_bankroll.txt")
LAST_TRAIN_FILE   = os.path.join(DATA_DIR, "last_train.txt")
KILLED_FILE       = os.path.join(DATA_DIR, "killed_strategies.json")
REGIME_FILE       = os.path.join(DATA_DIR, "regime_state.json")
LAST_WEEKLY_FILE  = os.path.join(DATA_DIR, "last_weekly.txt")

# ── Dedup window ─────────────────────────────────────────
ALERT_COOLDOWN_HOURS = 6
