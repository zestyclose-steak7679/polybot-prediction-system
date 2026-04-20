from flask import Flask, request, jsonify
import os
import threading
import logging

app = Flask(__name__)
logger = logging.getLogger(__name__)

SECRET = os.environ.get("WEBHOOK_SECRET", "")

@app.route("/trigger", methods=["POST"])
def trigger():
    # Optional secret check
    if SECRET:
        token = request.headers.get("X-Secret", "")
        if token != SECRET:
            return jsonify({"error": "unauthorized"}), 401

    def run():
        try:
            from main import run_cycle, load_bankroll, save_bankroll
            from data.database import init_db
            init_db()
            bankroll = load_bankroll()
            bankroll = run_cycle(bankroll)
            save_bankroll(bankroll)
        except Exception as e:
            logger.error(f"Webhook trigger failed: {e}")

    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()
    return jsonify({"status": "triggered"}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
