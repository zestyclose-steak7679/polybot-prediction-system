"""
alerts/telegram.py
Telegram Bot API sender. Uses requests only.
"""

import logging
import os
from datetime import UTC, datetime

import requests

logger = logging.getLogger(__name__)
SESSION = requests.Session()
SESSION.trust_env = False


def _get_credentials():
    token = (os.environ.get("TELEGRAM_TOKEN") or
             os.environ.get("TELEGRAM_BOT_TOKEN") or "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or ""
    return token.strip(), chat_id.strip()

def _send(text: str) -> bool:
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
        if not resp.ok:
            logger.error("Telegram API error: %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:
        logger.error("Telegram send exception: %s", e)
        return False


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _console_safe(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _quality_stars(confidence: float) -> str:
    if confidence >= 0.75: return "⭐⭐⭐ High"
    elif confidence >= 0.50: return "⭐⭐ Medium"
    else: return "⭐ Low"


def send_pick_alert(pick: dict, bankroll: float):
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        return

    q = pick.get('question', '')
    if len(q) > 60:
        q = q[:57] + "..."

    price_cents = int(pick['price'] * 100)
    conf = pick.get('confidence', 0)
    stars = _quality_stars(conf)

    text = (
        f"🎯 NEW SIGNAL\n\n"
        f"📌 {q}\n\n"
        f"Direction:   {pick['side']}\n"
        f"Price:       {pick['price']:.2f}  ({price_cents}¢)\n"
        f"Edge:        +{pick['edge']*100:.1f}%\n"
        f"Confidence:  {stars}  ({conf:.2f})\n"
        f"Bet size:    ${pick['bet_size']:.2f}\n"
        f"Strategy:    {pick.get('strategy', 'N/A')}\n"
        f"Regime:      {pick.get('regime', 'N/A')}\n\n"
        f"💰 Bankroll: ${bankroll:,.2f}\n"
        f"🕐 {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"⚠️ Paper trade only."
    )

    if len(text) > 4096:
        text = text[:4093] + "..."
    return _send(text)


def send_execution_alert(signal_dict: dict, status: str, reason: str = ""):
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        return False

    market_id = signal_dict.get('market_id', 'N/A')
    price = signal_dict.get('price', 0.0)
    size = signal_dict.get('bet_size', 0.0)

    emoji = "✅" if status == "SUCCESS" else "❌" if status == "FAILURE" else "⏭️"

    text = (
        f"{emoji} EXECUTION {status}\n\n"
        f"Market ID: {market_id}\n"
        f"Price: {price:.3f}\n"
        f"Size: ${size:.2f}\n"
    )
    if reason:
        text += f"Reason: {reason}\n"

    return _send(text)

def _fmt_optional_float(value, digits: int = 4, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}{suffix}"


def send_summary(
    stats: dict,
    strategy_stats: list,
    bankroll: float,
    picks_count: int,
    active_strategies: list,
    model_mode: str = "Heuristic",
    alpha_stats: list | None = None,
    position_stats: dict | None = None,
    cycle_metrics: dict | None = None,
    clv_stats: dict | None = None,
    benchmark_data: dict | None = None,
    tracker_active: list | None = None,
):
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        return

    pnl_sign = "+" if stats.get("total_pnl", 0) >= 0 else ""
    position_stats = position_stats or {}
    cycle_metrics = cycle_metrics or {}
    clv_stats = clv_stats or {}

    # Performance
    total_bets = (
        benchmark_data.get('bets_today', 0)
        if benchmark_data
        else stats.get('total_bets', 0)
    )
    wins = stats.get('wins', 0)
    losses = stats.get('losses', 0)
    win_rate = stats.get('win_rate', 0.0)
    roi = stats.get('roi', 0.0)
    pnl = stats.get('total_pnl', 0.0)
    avg_clv = clv_stats.get("avg_clv", 0.0)
    avg_clv_val = avg_clv if avg_clv is not None else 0.0
    sharpe = stats.get('sharpe', 0.0)
    sharpe_val = sharpe if sharpe is not None else 0.0

    # Open Positions
    open_bets = position_stats.get("n_open", 0)
    avg_hold = position_stats.get("avg_hold_hours", 0.0)
    closed_this_cycle = cycle_metrics.get("closed_this_cycle", 0)
    timeout_closed = cycle_metrics.get("timeout_closed_this_cycle", 0)

    # Strategies
    from risk.strategy_killer import _load_killed
    from config import STRATEGY_MIN_ROI
    killed_log = _load_killed()

    strat_items = []
    for s in strategy_stats:
        name = s["strategy"]
        if name in active_strategies:
            strat_items.append(f"✅ {name}")
        elif tracker_active is not None and name in tracker_active:
            strat_items.append(f"⏸ {name} (regime filtered)")
        else:
            reason = killed_log.get(name, {}).get("reason") if isinstance(killed_log.get(name), dict) else None
            # If strategy is disabled by tracker.py instead of killer, it won't have a reason in killed_log
            if not reason:
                roi_val = s.get("roi")
                if roi_val is not None and roi_val < STRATEGY_MIN_ROI:
                    reason = f"ROI {roi_val*100:.1f}% < {STRATEGY_MIN_ROI*100:.0f}%"
                else:
                    reason = "disabled"
            strat_items.append(f"❌ {name} ({reason})")

    strat_line = "    | ".join(strat_items)

    # Alpha Shadow
    alpha_lines = ""
    for alpha in (alpha_stats or [])[:3]:
        alpha_lines += (
            f"{alpha['alpha_name']:<14} CLV {alpha.get('avg_clv', 0):.2f}  "
            f"Hit {alpha.get('positive_rate', 0) * 100:.0f}%  n={alpha.get('n', 0)}\n"
        )

    regime = clv_stats.get("regime", "N/A")

    raw_signals = cycle_metrics.get("raw_signals", 0)
    blocked_by_threshold = cycle_metrics.get("blocked_by_threshold", 0)
    blocked_by_risk = cycle_metrics.get("blocked_by_risk", 0)
    executed_trades = cycle_metrics.get("executed_trades", 0)
    avg_confidence = cycle_metrics.get("avg_confidence")
    signal_breakdown = f"{raw_signals} raw | {blocked_by_threshold} no edge | {blocked_by_risk} risk blocked | {executed_trades} executed"

    text = (
        f"📊 POLYBOT SUMMARY\n"
        f"🕐 {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"💰 Bankroll: ${bankroll:,.2f}\n"
        f"🔍 Signals: {signal_breakdown}\n\n"
        f"── PERFORMANCE ──\n"
        f"Bets: {total_bets}  |  W/L: {wins}/{losses}  |  Win rate: {win_rate:.1f}%\n"
        f"ROI: {pnl_sign}{roi:.2f}%  |  P&L: {pnl_sign}${pnl:.2f}\n"
        f"Avg CLV: {avg_clv_val:.3f}  |  Sharpe: {sharpe_val:.3f}\n\n"
        f"── POSITIONS ──\n"
        f"Open: {open_bets}  |  Avg hold: {avg_hold:.1f}h\n"
        f"Closed this cycle: {closed_this_cycle}  |  Timeouts: {timeout_closed}\n\n"
        f"── STRATEGIES ──\n"
        f"{strat_line}\n\n"
        f"── ALPHA SHADOW ──\n"
        f"{alpha_lines}\n"
        f"── MODEL ──\n"
        f"{model_mode}  |  Regime: {regime}  |  META: {round(avg_confidence, 2) if avg_confidence is not None else '-'}\n"
        f"{'─' * 28}"
    )

    if len(text) > 4096:
        text = text[:4093] + "..."
    return _send(text)


def send_risk_halt(reason: str, bankroll: float):
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        return
    text = f"🛑 RISK HALT\n\n{reason}\n\n💰 Bankroll: ${bankroll:.2f}"

    return _send(text)


def send_startup(bankroll: float):
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        return
    text = f"🚀 Polybot started\n💰 Bankroll: ${bankroll:.2f}"

    return _send(text)


def send_error(msg: str):
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        return
    text = f"❌ ERROR\n\n{msg}"

    if len(text) > 4096:
        text = text[:4093] + "..."
    return _send(text)


def send_weekly_report(stats: dict) -> None:
    """Send weekly performance summary to Telegram."""
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        return
    msg = (
        f"📅 <b>WEEKLY REPORT</b>\n"
        f"{'─'*28}\n"
        f"Period: {stats['period']}\n\n"
        f"<b>Performance</b>\n"
        f"  Bets: {stats['bets']}  |  W/L: {stats['wins']}/{stats['losses']}\n"
        f"  Win rate: {stats['win_rate']:.1f}%\n"
        f"  ROI: {stats['roi']:+.2f}%\n"
        f"  P&L: ${stats['pnl']:+.2f}\n"
        f"  Avg CLV: {stats['avg_clv']:.4f}\n\n"
        f"<b>Best strategy</b>: {stats['best_strategy']}\n"
        f"<b>Worst strategy</b>: {stats['worst_strategy']}\n"
        f"<b>Regime distribution</b>: {stats['regime_dist']}\n"
        f"{'─'*28}\n"
        f"💰 Bankroll: <b>${stats['bankroll']:.2f}</b>\n"
        f"📈 7-day change: {stats['bankroll_change']:+.2f}%"
    )
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg,
                                 "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error("Weekly report send failed: %s", e)

def send_positions_update(positions_df) -> None:
    """Send current open positions to Telegram."""
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        return
    if positions_df.empty:
        msg = "📭 <b>OPEN POSITIONS</b>\n\nNo open positions."
    else:
        lines = ["📊 <b>OPEN POSITIONS</b>\n"]
        total_unrealised = 0.0
        for _, row in positions_df.iterrows():
            pnl = row.get("unrealised_pnl", 0.0) or 0.0
            total_unrealised += pnl
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            lines.append(
                f"{'🟢' if pnl >= 0 else '🔴'} {str(row['question'])[:45]}\n"
                f"   {row['side']} @ {row['entry_price']:.3f} | "
                f"Hold: {row['hold_hours']:.1f}h | P&L: {pnl_str}\n"
                f"   Strategy: {row['strategy']} | Size: ${row['bet_size']:.2f}"
            )
        total_str = f"+${total_unrealised:.2f}" if total_unrealised >= 0 else f"-${abs(total_unrealised):.2f}"
        lines.append(f"\n💼 Total unrealised: <b>{total_str}</b>")
        msg = "\n".join(lines)
    _send(msg)

def send_benchmark_alert(violations: list, data: dict, bankroll: float) -> None:
    """Send benchmark violation alert to Telegram."""
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
