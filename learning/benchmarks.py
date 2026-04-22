"""
Daily benchmark system.
Tracks whether key metrics are moving in the right direction.
Fires Telegram alert if any benchmark is missed.
"""
import os
import json
import logging
from datetime import datetime, UTC
from pathlib import Path

logger = logging.getLogger(__name__)

BENCHMARK_FILE = Path("daily_benchmarks.json")

# Daily targets — what healthy compounding looks like
DAILY_BENCHMARKS = {
    "min_signals_per_day": 3,        # At least 3 signals generated
    "min_bets_per_day": 1,           # At least 1 bet placed
    "min_avg_clv": 0.01,             # CLV must stay positive
    "max_win_rate_floor": 0.45,      # Win rate must not fall below 45%
    "min_bankroll_change_pct": -5.0, # Bankroll must not drop more than 5% in a day
    "max_timeout_rate": 0.50,        # No more than 50% of closes via timeout
    "min_strategies_active": 1,      # At least 1 strategy must be active
}

def load_benchmarks() -> dict:
    """Load today's benchmark tracking data."""
    try:
        if BENCHMARK_FILE.exists():
            data = json.loads(BENCHMARK_FILE.read_text())
            # Reset if it's a new day
            today = datetime.now(UTC).date().isoformat()
            if data.get("date") != today:
                return _fresh_benchmarks(today)
            return data
    except Exception as e:
        logger.error("load_benchmarks failed: %s", e)
    return _fresh_benchmarks(datetime.now(UTC).date().isoformat())

def _fresh_benchmarks(date: str) -> dict:
    return {
        "date": date,
        "signals_today": 0,
        "bets_today": 0,
        "bankroll_start_of_day": None,
        "bankroll_current": None,
        "timeouts_today": 0,
        "closes_today": 0,
        "last_checked": None,
        "last_benchmark_alert": None,
    }

def save_benchmarks(data: dict) -> None:
    try:
        BENCHMARK_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error("save_benchmarks failed: %s", e)

def update_benchmarks(signals: int, bets: int, bankroll: float,
                       timeouts: int, closes: int) -> dict:
    """Update today's benchmark data with cycle results."""
    data = load_benchmarks()
    data["signals_today"] += signals
    data["bets_today"] += bets
    data["timeouts_today"] += timeouts
    data["closes_today"] += closes
    data["bankroll_current"] = bankroll
    if data["bankroll_start_of_day"] is None:
        data["bankroll_start_of_day"] = bankroll
    data["last_checked"] = datetime.now(UTC).isoformat()
    save_benchmarks(data)
    return data

def check_benchmarks(data: dict, clv_stats: dict,
                      strategy_count: int) -> list[dict]:
    """
    Check all benchmarks and return list of violations.
    Each violation is a dict with 'metric', 'expected', 'actual', 'severity'.
    """
    if data.get("last_benchmark_alert") == datetime.now(UTC).date().isoformat():
        return []

    violations = []

    # Only check benchmarks after 8 PM UTC (end of trading day)
    hour = datetime.now(UTC).hour
    if hour < 20:
        return violations

    # Check signals
    if data["signals_today"] < DAILY_BENCHMARKS["min_signals_per_day"]:
        violations.append({
            "metric": "Signals generated today",
            "expected": f">= {DAILY_BENCHMARKS['min_signals_per_day']}",
            "actual": data["signals_today"],
            "severity": "⚠️ WARNING"
        })

    # Check bets placed
    if data["bets_today"] < DAILY_BENCHMARKS["min_bets_per_day"]:
        violations.append({
            "metric": "Bets placed today",
            "expected": f">= {DAILY_BENCHMARKS['min_bets_per_day']}",
            "actual": data["bets_today"],
            "severity": "🚨 CRITICAL"
        })

    # Check CLV
    avg_clv = clv_stats.get("avg_clv", 0.0)
    if avg_clv < DAILY_BENCHMARKS["min_avg_clv"]:
        violations.append({
            "metric": "Average CLV",
            "expected": f">= {DAILY_BENCHMARKS['min_avg_clv']:.3f}",
            "actual": f"{avg_clv:.4f}",
            "severity": "🚨 CRITICAL"
        })

    # Check bankroll decline
    if data["bankroll_start_of_day"] and data["bankroll_current"]:
        daily_change_pct = ((data["bankroll_current"] - data["bankroll_start_of_day"])
                           / data["bankroll_start_of_day"]) * 100
        if daily_change_pct < DAILY_BENCHMARKS["min_bankroll_change_pct"]:
            violations.append({
                "metric": "Daily bankroll change",
                "expected": f">= {DAILY_BENCHMARKS['min_bankroll_change_pct']:.1f}%",
                "actual": f"{daily_change_pct:.2f}%",
                "severity": "🚨 CRITICAL"
            })

    # Check timeout rate
    if data["closes_today"] > 0:
        timeout_rate = data["timeouts_today"] / data["closes_today"]
        if timeout_rate > DAILY_BENCHMARKS["max_timeout_rate"]:
            violations.append({
                "metric": "Timeout close rate",
                "expected": f"<= {DAILY_BENCHMARKS['max_timeout_rate']:.0%}",
                "actual": f"{timeout_rate:.0%}",
                "severity": "⚠️ WARNING"
            })

    # Check active strategies
    if strategy_count < DAILY_BENCHMARKS["min_strategies_active"]:
        violations.append({
            "metric": "Active strategies",
            "expected": f">= {DAILY_BENCHMARKS['min_strategies_active']}",
            "actual": strategy_count,
            "severity": "🚨 CRITICAL"
        })

    return violations

def send_benchmark_alert(violations: list, data: dict, bankroll: float) -> None:
    """Send benchmark violation alert to Telegram."""
    from alerts.telegram import _get_credentials, _send
    token, chat_id = _get_credentials()
    if not token or not chat_id or not violations:
        return

    lines = [
        "🚨 <b>DAILY BENCHMARK ALERT</b>",
        f"📅 {data.get('date', 'unknown')}",
        "─" * 28,
        ""
    ]

    for v in violations:
        lines.append(
            f"{v['severity']} <b>{v['metric']}</b>\n"
            f"   Expected: {v['expected']}\n"
            f"   Actual: {v['actual']}"
        )

    lines.extend([
        "",
        "─" * 28,
        f"📊 Today's signals: {data.get('signals_today', 0)}",
        f"🎯 Today's bets: {data.get('bets_today', 0)}",
        f"💰 Bankroll: ${bankroll:.2f}",
        "",
        "⚡ Bot needs attention."
    ])

    _send("\n".join(lines))

    try:
        data = load_benchmarks()
        data["last_benchmark_alert"] = datetime.now(UTC).date().isoformat()
        save_benchmarks(data)
    except Exception as e:
        logger.error("Failed to update benchmark alert cooldown: %s", e)
