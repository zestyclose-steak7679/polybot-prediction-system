from flask import Flask, jsonify, request
import os
import threading
import logging
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

_BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(_BASE_DIR))
os.chdir(str(_BASE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("polybot.webhook")

app = Flask(__name__)
_lock = threading.Lock()
_running = False

DB_PATH = os.environ.get("DB_PATH", "polybot.db")
DATA_DIR = os.environ.get("DATA_DIR", ".")
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
            import sys, os
            # Try multiple possible app roots
            for _path in [str(_BASE_DIR), '/app', os.path.dirname(os.path.abspath(__file__))]:
                if os.path.exists(os.path.join(_path, 'main.py')):
                    sys.path.insert(0, _path)
                    os.chdir(_path)
                    logger.info(f"App root found: {_path}")
                    break
            from main import run_cycle, load_bankroll, save_bankroll
            from data.database import init_db
            from data.price_history import init_price_history
            logger.info(f"CWD: {os.getcwd()} | BASE: {_BASE_DIR} | sys.path[0]: {sys.path[0]}")
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

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return jsonify({"status": "triggered"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "running": _running
    }), 200
@app.route("/api/state", methods=["GET", "OPTIONS"])

    return jsonify({"status": "ok", "running": _running}), 200


@app.route("/api/state", methods=["GET"])
def api_state():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        return response

    try:
        bankroll = 1000.0
        try:
            bankroll = float(open(BANKROLL_FILE).read().strip())
        except:
            pass

        os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
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

        response = jsonify({
            "bankroll": bankroll,
            "open_bets": open_bets,
            "closed_bets": closed_bets,
            "strategies": strategies,
            "bankroll_history": history,
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        return response
    except Exception as e:

        response = jsonify({"error": str(e)})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        return response, 500


        return jsonify({"error": str(e)}), 500



@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "polybot-webhook"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
