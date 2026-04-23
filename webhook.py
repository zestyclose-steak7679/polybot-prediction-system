from flask import Flask, jsonify, request
import os
import threading
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("polybot.webhook")

app = Flask(__name__)
SECRET = os.environ.get("WEBHOOK_SECRET", "")
_lock = threading.Lock()
_running = False

@app.route("/trigger", methods=["POST"])
def trigger():
    global _running

    # Verify secret
    received_secret = request.headers.get("X-Webhook-Secret")
    if not SECRET or received_secret != SECRET:
        logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
        return jsonify({"status": "unauthorized"}), 401

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
    return jsonify({
        "status": "ok",
        "running": _running
    }), 200

@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "polybot-webhook"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
