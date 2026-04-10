"""
alerts/telegram.py
Telegram Bot API sender. Uses requests only.
"""

import logging
from datetime import UTC, datetime

import requests

from config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

logger = logging.getLogger(__name__)
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
SESSION = requests.Session()
SESSION.trust_env = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _console_safe(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _send(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram token or chat ID is missing, skipping alert.")
        print(_console_safe(text))
        return False
    try:
        if len(text) > 4096:
            text = text[:4093] + "..."
        resp = SESSION.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def send_pick_alert(pick: dict, bankroll: float):
    text = (
        f"<b>POLYBOT PAPER PICK | {pick.get('strategy', '').upper()}</b>\n"
        f"------------------------------\n"
        f"<b>{pick['question']}</b>\n\n"
        f"Bet {pick['side']} @ {pick['price']:.3f} ({pick['decimal_odds']:.2f}x)\n\n"
        f"<b>Signal</b>\n"
        f"  Edge:       {pick['edge']*100:.1f}%\n"
        f"  Confidence: {pick.get('confidence', 0)*100:.1f}%\n"
        f"  Reason:     {pick.get('reason', 'N/A')}\n\n"
        f"<b>Sizing</b>\n"
        f"  Bet size:   ${pick['bet_size']:.2f} ({pick['bet_size']/bankroll*100:.1f}% of ${bankroll:.0f})\n"
        f"  Kelly raw:  {pick['kelly_raw']*100:.1f}%\n\n"
        f"<b>Market</b>\n"
        f"  Liquidity:  ${pick['liquidity']:,.0f}\n"
        f"  Volume:     ${pick['volume']:,.0f}\n"
        f"  24h move:   {pick['one_day_change']*100:+.1f}%\n"
        f"  Closes:     {str(pick.get('end_date', ''))[:10] or 'N/A'}\n"
        f"------------------------------\n"
        f"<i>Paper trade only.</i>"
    )
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
):
    pnl_sign = "+" if stats.get("total_pnl", 0) >= 0 else ""
    position_stats = position_stats or {}
    cycle_metrics = cycle_metrics or {}
    clv_stats = clv_stats or {}

    strat_lines = ""
    for s in strategy_stats:
        roi_str = f"{s['roi']*100:.1f}%" if s.get("roi") is not None else "N/A"
        wr_str = f"{s['win_rate']*100:.0f}%" if s.get("win_rate") is not None else "N/A"
        avg_clv = _fmt_optional_float(s.get("avg_clv"), 4)
        resolved_n = s.get("resolved_clv_n", 0)
        status = "ACTIVE" if s["strategy"] in active_strategies else "OFF"
        strat_lines += (
            f"  {status:6s} {s['strategy']:13s} "
            f"ROI {roi_str:>7} | WR {wr_str:>4} | n={s.get('n_bets', 0)} | "
            f"CLV {avg_clv:>7} | resolved={resolved_n}\n"
        )

    alpha_lines = ""
    for alpha in (alpha_stats or [])[:3]:
        status = "PROMOTED" if alpha.get("promoted") else "SHADOW"
        alpha_lines += (
            f"  {status:8s} {alpha['alpha_name']:13s} "
            f"CLV {alpha.get('avg_clv', 0):>7.4f} | "
            f"Hit {alpha.get('positive_rate', 0) * 100:>4.0f}% | n={alpha.get('n', 0)}\n"
        )
    alpha_section = f"<b>Alpha shadow</b>\n{alpha_lines}" if alpha_lines else ""

    open_bets = position_stats.get("n_open", 0)
    avg_hold = position_stats.get("avg_hold_hours", 0.0)
    closed_this_cycle = cycle_metrics.get("closed_this_cycle", 0)
    timeout_closed = cycle_metrics.get("timeout_closed_this_cycle", 0)
    clv_closed = cycle_metrics.get("clv_resolved_this_cycle", 0)
    alpha_shadow = cycle_metrics.get("triggered_shadow_signals", 0)
    alpha_resolved_total = cycle_metrics.get("alpha_resolved_total", 0)
    avg_clv = _fmt_optional_float(clv_stats.get("avg_clv"), 5)

    text = (
        f"<b>POLYBOT SUMMARY</b>\n"
        f"------------------------------\n"
        f"Time: {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Bankroll: <b>${bankroll:.2f}</b>\n"
        f"New signals: {picks_count}\n\n"
        f"<b>Overall (paper)</b>\n"
        f"  Bets: {stats.get('total_bets', 0)} | W/L {stats.get('wins', 0)}/{stats.get('losses', 0)}\n"
        f"  Win rate: {stats.get('win_rate', 0):.1f}%\n"
        f"  ROI: {stats.get('roi', 0):+.2f}%\n"
        f"  P&L: {pnl_sign}${stats.get('total_pnl', 0):.2f}\n"
        f"  CLV resolved: {stats.get('clv_resolved_bets', 0)} | Avg CLV: {avg_clv}\n\n"
        f"<b>Turnover</b>\n"
        f"  Open bets: {open_bets} | Avg hold: {avg_hold:.1f}h\n"
        f"  Closed this cycle: {closed_this_cycle} | Timeout exits: {timeout_closed}\n"
        f"  CLV closed this cycle: {clv_closed} | Alpha shadow this cycle: {alpha_shadow}\n"
        f"  Alpha resolved total: {alpha_resolved_total}\n\n"
        f"<b>Strategy competition</b>\n"
        f"{strat_lines}"
        f"{alpha_section}"
        f"Model: {model_mode}\n"
        f"------------------------------"
    )
    return _send(text)


def send_risk_halt(reason: str, bankroll: float):
    text = (
        f"<b>POLYBOT RISK HALT</b>\n"
        f"Bankroll: ${bankroll:.2f}\n"
        f"Reason: {reason}"
    )
    return _send(text)


def send_startup():
    return _send(
        f"<b>POLYBOT STARTED</b>\n"
        f"Paper mode | multi-strategy\n"
        f"Time: {_utc_now().strftime('%Y-%m-%d %H:%M UTC')}"
    )


def send_error(msg: str):
    return _send(f"<b>POLYBOT ERROR</b>\n{msg}")
