from flask import Flask, jsonify
import os
import threading
import logging
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

# Resolve app root
_BASE_DIR = Path(__file__).resolve().parent
for _candidate in [_BASE_DIR, Path('/app')]:
    if (_candidate / 'main.py').exists():
        _APP_ROOT = _candidate
        break
else:
    _APP_ROOT = _BASE_DIR

sys.path.insert(0, str(_APP_ROOT))
os.chdir(str(_APP_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("polybot.webhook")
logger.info(f"APP_ROOT={_APP_ROOT} CWD={os.getcwd()}")

app = Flask(__name__)
_running = False

DB_PATH = os.environ.get("DB_PATH", str(_APP_ROOT / "polybot.db"))
DATA_DIR = os.environ.get("DATA_DIR", str(_APP_ROOT))
BANKROLL_FILE = os.path.join(DATA_DIR, "bankroll.txt")
os.makedirs(DATA_DIR, exist_ok=True)


@app.route("/trigger", methods=["POST"])
def trigger():
    global _running
    if _running:
        return jsonify({"status": "already_running"}), 429

    def run():
        global _running
        _running = True
        try:
            sys.path.insert(0, str(_APP_ROOT))
            os.chdir(str(_APP_ROOT))
            from main import run_cycle, load_bankroll, save_bankroll
            from data.database import init_db
            from data.price_history import init_price_history
            logger.info(f"Cycle start | CWD={os.getcwd()} | path0={sys.path[0]}")
            init_db()
            init_price_history()
            bankroll = load_bankroll()
            bankroll = run_cycle(bankroll)
            save_bankroll(bankroll)
            logger.info("Webhook cycle complete")
        except Exception as e:
            logger.error(f"Webhook cycle failed: {e}")
        finally:
            _running = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "triggered"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "running": _running}), 200


@app.route("/api/state", methods=["GET"])
def api_state():
    try:
        bankroll = 1000.0
        # Try bankroll from DB first, then fall back to file
        try:
            tmp_con = sqlite3.connect(DB_PATH)
            row = tmp_con.execute("SELECT value FROM bankroll_log ORDER BY rowid DESC LIMIT 1").fetchone()
            if row:
                bankroll = row[0]
            tmp_con.close()
        except:
            try:
                bankroll = float(open(BANKROLL_FILE).read().strip())
            except:
                pass

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS paper_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT, question TEXT, strategy_tag TEXT,
            side TEXT, entry_price REAL, bet_size REAL,
            bankroll_at REAL, kelly_raw REAL, edge_est REAL,
            confidence REAL, reason TEXT, placed_at TEXT,
            mode TEXT DEFAULT 'ACTIVE', result TEXT DEFAULT 'open',
            exit_price REAL, closing_price REAL,
            pnl REAL, roi REAL, clv REAL, closed_at TEXT
        )""")
        cur.execute("CREATE TABLE IF NOT EXISTS bankroll_log (ts TEXT, value REAL)")
        con.commit()

        cur.execute("SELECT * FROM paper_bets WHERE result='open' ORDER BY placed_at DESC LIMIT 20")
        open_bets = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM paper_bets WHERE result!='open' ORDER BY rowid DESC LIMIT 50")
        closed_bets = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT strategy_tag as strategy, COUNT(*) as total, SUM(clv) as total_clv FROM paper_bets WHERE result!='open' GROUP BY strategy_tag")
        strategies = [dict(r) for r in cur.fetchall()]

        try:
            cur.execute("SELECT ts as time, value FROM bankroll_log ORDER BY ts ASC")
            history = [dict(r) for r in cur.fetchall()]
        except:
            history = []

        con.close()

        return jsonify({
            "bankroll": bankroll,
            "open_bets": open_bets,
            "closed_bets": closed_bets,
            "strategies": strategies,
            "bankroll_history": history,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "polybot-webhook", "app_root": str(_APP_ROOT)}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
