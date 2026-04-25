from flask import Flask, jsonify, request
import os
import threading
import logging
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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


@app.route("/trigger", methods=["POST"])
def trigger():
    global _running
    if _running:
        return jsonify({"status": "already_running"}), 429

    def run():
        global _running
        _running = True
        try:
            from main import run_cycle, load_bankroll, save_bankroll
            from data.database import init_db
            from data.price_history import init_price_history
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
    return jsonify({"status": "ok", "running": _running}), 200


@app.route("/api/state", methods=["GET"])
def api_state():
    try:
        bankroll = 1000.0
        try:
            bankroll = float(open(BANKROLL_FILE).read().strip())
        except:
            pass

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

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
    return jsonify({"service": "polybot-webhook"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
