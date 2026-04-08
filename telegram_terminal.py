"""
telegram_terminal.py
====================
Live portfolio terminal for Polybot, delivered via Telegram.

Integrates directly with existing polybot modules — no new dependencies.
Reads from polybot.db (paper_bets, alpha_signals) and live state files.

COMMANDS
  /terminal   → send live dashboard, starts auto-refresh every 30s
  /stop       → stop auto-refresh
  /positions  → open bets table
  /history    → last 20 closed bets
  /strategies → per-strategy ROI + CLV breakdown
  /clv        → CLV significance report
  /risk       → risk controls status

SETUP
  1. pip install python-telegram-bot>=20.0
  2. Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in env (already in config.py)
  3. Run alongside main.py:  python telegram_terminal.py
  4. In Telegram: /terminal to start live view

DESIGN CHOICES vs the generic advice you received
  - text-based tables (tabulate), NOT images — faster, no matplotlib dep,
    works in groups, searchable in chat history
  - edit_message_text loop (30s) — single pinned message, no notification spam
  - reads directly from sqlite — no API roundtrip, always current
  - no py-polymarket-clob dep — you already have data.markets + data.database
"""

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from tabulate import tabulate
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from telegram.error import BadRequest

# --- local polybot imports ---
sys.path.insert(0, str(Path(__file__).parent))
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BANKROLL, MAX_DRAWDOWN_PCT, MAX_OPEN_BETS
from data.database import (
    get_open_bets, get_closed_bets, get_pnl_summary,
    get_open_position_stats, init_db,
)
from tracking.clv import clv_report
from learning.tracker import get_all_strategy_stats
from risk.controls import load_peak, check_drawdown, check_open_positions

logger = logging.getLogger("polybot.terminal")

GOAL = 30_000.0
START = 1_000.0

REFRESH_INTERVAL = 30   # seconds between auto-refresh
REFRESH_JOB_KEY  = "terminal_refresh"
MESSAGE_ID_KEY   = "terminal_msg_id"


# ─── Formatting helpers ────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _bankroll() -> float:
    try:
        return float(Path("bankroll.txt").read_text().strip())
    except Exception:
        return BANKROLL


def _pct(val: float | None, digits: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{val*100:+.{digits}f}%"


def _usd(val: float | None) -> str:
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else "-"
    return f"{sign}${abs(val):.2f}"


def _clv_str(val: float | None) -> str:
    if val is None:
        return "—"
    return f"{val:+.4f}"


def _trunc(s: str, n: int = 30) -> str:
    return s[:n-1] + "…" if len(s) > n else s


def _regime() -> str:
    try:
        import json
        state = json.loads(Path("regime_state.json").read_text())
        return state.get("confirmed", "unknown")
    except Exception:
        return "unknown"


# ─── View builders ────────────────────────────────────────────────────────────

def _build_summary() -> str:
    br = _bankroll()
    stats = get_pnl_summary()
    pos = get_open_position_stats()
    clv = clv_report()
    peak = load_peak(br)
    dd = (peak - br) / peak if peak > 0 else 0.0
    pnl = br - START
    roi = pnl / START

    progress_pct = max((br - START) / (GOAL - START), 0.0)
    bar_len = 20
    filled = int(progress_pct * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    lines = [
        f"<b>POLYBOT TERMINAL</b>",
        f"<code>{_now()}</code>",
        "",
        f"<b>Goal: ₹1k → ₹30k</b>",
        f"<code>[{bar}] {progress_pct*100:.1f}%</code>",
        "",
        "<b>Portfolio</b>",
    ]

    tbl = [
        ["Bankroll",  f"${br:.2f}"],
        ["P&L",       _usd(pnl)],
        ["ROI",       _pct(roi)],
        ["Win rate",  f"{stats['win_rate']:.1f}%"],
        ["Bets",      f"{stats['wins']}W / {stats['losses']}L"],
    ]
    lines.append("<code>" + tabulate(tbl, tablefmt="plain") + "</code>")

    lines += ["", "<b>CLV</b>"]
    if clv["n"] > 0:
        sig = "✅" if (clv["avg_clv"] or 0) > 0 else "❌"
        clv_tbl = [
            ["Avg CLV",    _clv_str(clv["avg_clv"]) + f" {sig}"],
            ["Positive",   f"{(clv['positive_rate'] or 0)*100:.0f}%"],
            ["Sharpe",     f"{clv['clv_sharpe'] or 0:.3f}"],
            ["Resolved",   str(clv["n"])],
        ]
        lines.append("<code>" + tabulate(clv_tbl, tablefmt="plain") + "</code>")
    else:
        lines.append("<code>No CLV resolved yet</code>")

    lines += ["", "<b>Positions</b>"]
    pos_tbl = [
        ["Open bets",  str(pos["n_open"])],
        ["Avg hold",   f"{pos['avg_hold_hours']:.1f}h"],
        ["Stale",      str(pos["stale_count"])],
        ["Regime",     _regime()],
    ]
    lines.append("<code>" + tabulate(pos_tbl, tablefmt="plain") + "</code>")

    lines += ["", "<b>Risk</b>"]
    dd_ok = dd < MAX_DRAWDOWN_PCT
    risk_tbl = [
        ["Drawdown",  f"{dd*100:.1f}% {'✅' if dd_ok else '🚨 HALT'}"],
        ["Peak",      f"${peak:.2f}"],
        ["Open cap",  f"{pos['n_open']}/{MAX_OPEN_BETS}"],
    ]
    lines.append("<code>" + tabulate(risk_tbl, tablefmt="plain") + "</code>")

    return "\n".join(lines)


def _build_positions() -> str:
    bets = get_open_bets()
    if bets.empty:
        return "<b>OPEN POSITIONS</b>\n<code>No open bets</code>"

    rows = []
    for b in bets.to_dict("records"):
        from data.database import _hours_open
        hold = _hours_open(b.get("placed_at", ""))
        rows.append([
            _trunc(b["question"], 28),
            b["side"],
            b.get("strategy_tag", "?")[:8],
            f"{b['entry_price']:.3f}",
            f"{b.get('edge_est', 0)*100:.1f}%",
            f"${b['bet_size']:.2f}",
            f"{hold:.1f}h",
        ])

    table = tabulate(
        rows,
        headers=["Market", "Side", "Strat", "Entry", "Edge", "Size", "Hold"],
        tablefmt="simple",
    )
    return f"<b>OPEN POSITIONS ({len(bets)})</b>\n<code>{table}</code>"


def _build_history() -> str:
    bets = get_closed_bets(limit=20)
    if bets.empty:
        return "<b>CLOSED BETS</b>\n<code>No closed bets yet</code>"

    rows = []
    for b in bets.to_dict("records"):
        pnl_str = _usd(b.get("pnl"))
        clv_str = _clv_str(b.get("clv"))
        result = str(b.get("result", "?")).upper()
        rows.append([
            _trunc(b["question"], 26),
            result[:8],
            b.get("strategy_tag", "?")[:8],
            f"{b['entry_price']:.3f}",
            pnl_str,
            clv_str,
        ])

    table = tabulate(
        rows,
        headers=["Market", "Result", "Strat", "Entry", "P&L", "CLV"],
        tablefmt="simple",
    )
    return f"<b>CLOSED BETS (last {len(bets)})</b>\n<code>{table}</code>"


def _build_strategies() -> str:
    stats = get_all_strategy_stats()
    if not stats:
        return "<b>STRATEGY STATS</b>\n<code>No data yet (need 10+ closed bets per strategy)</code>"

    rows = []
    for s in stats:
        roi = f"{s['roi']*100:+.1f}%" if s.get("roi") is not None else "N/A"
        wr  = f"{s['win_rate']*100:.0f}%" if s.get("win_rate") is not None else "N/A"
        clv = _clv_str(s.get("avg_clv"))
        rows.append([
            s["strategy"][:12],
            str(s.get("n_bets", 0)),
            roi,
            wr,
            clv,
            str(s.get("resolved_clv_n", 0)),
        ])

    table = tabulate(
        rows,
        headers=["Strategy", "n", "ROI", "WR", "AvgCLV", "CLVn"],
        tablefmt="simple",
    )
    return f"<b>STRATEGY PERFORMANCE</b>\n<code>{table}</code>"


def _build_clv_report() -> str:
    """
    Honest CLV significance report.
    clv = (1/entry_price) - (1/closing_price) — not model_edge.
    """
    import math
    clv = clv_report()
    n = clv["n"]

    if n == 0:
        return (
            "<b>CLV REPORT</b>\n"
            "<code>No CLV resolved yet.\n"
            "CLV captures when positions settle near resolution.\n"
            "Timeout exits (6h) also record CLV.</code>"
        )

    avg = clv["avg_clv"] or 0.0
    std = 0.025  # typical CLV std for prediction markets
    se = std / math.sqrt(n)
    z = avg / se
    # approximate p-value
    p = 2 * (1 - _norm_cdf(abs(z)))
    sig = p < 0.05

    # Power analysis
    needed = {}
    for target in [0.005, 0.010, 0.015, 0.020]:
        n_needed = int(((1.96 + 0.842) * std / target) ** 2) + 1
        needed[f"{target*100:.1f}%"] = n_needed

    lines = [
        "<b>CLV SIGNIFICANCE REPORT</b>",
        f"<code>Formula: CLV = (1/entry) - (1/closing_price)</code>",
        "",
        "<code>",
        f"Mean CLV    {avg:+.5f}",
        f"95% CI      [{avg-1.96*se:+.5f}, {avg+1.96*se:+.5f}]",
        f"p-value     {p:.4f}  {'✅ significant' if sig else '❌ not significant'}",
        f"n resolved  {n}",
        f"Pos rate    {(clv['positive_rate'] or 0)*100:.0f}%",
        f"CLV Sharpe  {clv['clv_sharpe'] or 0:.3f}",
        "</code>",
        "",
        "<b>Verdict</b>",
    ]

    if sig and avg > 0:
        lines.append("✅ Real edge detected. Consider paper scaling.")
    elif sig and avg < 0:
        lines.append("❌ Significant negative CLV. Stop and fix features.")
    else:
        lines.append(f"⏳ Inconclusive. Accumulate more data.")

    lines += ["", "<b>Detection power (at current n=" + str(n) + ")</b>", "<code>"]
    for target, n_needed in needed.items():
        status = "✅" if n >= n_needed else f"need {n_needed}"
        lines.append(f"CLV={target}  {status}")
    lines.append("</code>")

    # Per-strategy CLV
    if clv.get("strategy_clv"):
        lines += ["", "<b>CLV by strategy</b>", "<code>"]
        for strat, val in clv["strategy_clv"].items():
            sign = "✅" if val > 0 else "❌"
            lines.append(f"{strat[:12]:12s}  {val:+.5f}  {sign}")
        lines.append("</code>")

    return "\n".join(lines)


def _norm_cdf(x: float) -> float:
    """Approximate normal CDF."""
    import math
    return (1.0 + math.erf(x / math.sqrt(2))) / 2


def _build_risk() -> str:
    br = _bankroll()
    peak = load_peak(br)
    dd = (peak - br) / peak if peak > 0 else 0.0
    pos = get_open_position_stats()
    dd_ok = dd < MAX_DRAWDOWN_PCT

    rows = [
        ["Max drawdown",   f"{MAX_DRAWDOWN_PCT*100:.0f}%"],
        ["Current DD",     f"{dd*100:.1f}%  {'✅' if dd_ok else '🚨 HALTED'}"],
        ["Peak bankroll",  f"${peak:.2f}"],
        ["Current",        f"${br:.2f}"],
        ["Open bets",      f"{pos['n_open']} / {MAX_OPEN_BETS}"],
        ["Avg hold",       f"{pos['avg_hold_hours']:.1f}h (max 6h)"],
        ["Stale bets",     str(pos["stale_count"])],
        ["Max bet",        "3% bankroll"],
        ["Kelly frac",     "25%"],
        ["Edge threshold", "4%"],
    ]
    table = tabulate(rows, tablefmt="plain")
    return f"<b>RISK CONTROLS</b>\n<code>{table}</code>"


# ─── Keyboard ─────────────────────────────────────────────────────────────────

def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Summary",    callback_data="summary"),
            InlineKeyboardButton("Positions",  callback_data="positions"),
            InlineKeyboardButton("History",    callback_data="history"),
        ],
        [
            InlineKeyboardButton("Strategies", callback_data="strategies"),
            InlineKeyboardButton("CLV",        callback_data="clv"),
            InlineKeyboardButton("Risk",       callback_data="risk"),
        ],
    ])


VIEW_BUILDERS = {
    "summary":    _build_summary,
    "positions":  _build_positions,
    "history":    _build_history,
    "strategies": _build_strategies,
    "clv":        _build_clv_report,
    "risk":       _build_risk,
}


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_terminal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send the live terminal and start 30s auto-refresh."""
    text = _build_summary()
    msg = await update.message.reply_html(text, reply_markup=_keyboard())
    ctx.chat_data[MESSAGE_ID_KEY] = msg.message_id

    if ctx.job_queue:
        # Cancel any existing refresh job
        existing_job = ctx.chat_data.get(REFRESH_JOB_KEY)
        if existing_job:
            existing_job.schedule_removal()

        new_job = ctx.job_queue.run_repeating(
            _auto_refresh,
            interval=REFRESH_INTERVAL,
            first=REFRESH_INTERVAL,
            name=REFRESH_JOB_KEY,
            chat_id=update.effective_chat.id,
            data={"view": "summary"},
        )
        ctx.chat_data[REFRESH_JOB_KEY] = new_job
    await update.message.reply_html(
        f"<i>Auto-refreshing every {REFRESH_INTERVAL}s. Use /stop to halt.</i>"
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.job_queue:
        existing_job = ctx.chat_data.get(REFRESH_JOB_KEY)
        if existing_job:
            existing_job.schedule_removal()
            del ctx.chat_data[REFRESH_JOB_KEY]
    await update.message.reply_html("<i>Auto-refresh stopped.</i>")


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(_build_positions(), reply_markup=_keyboard())


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(_build_history(), reply_markup=_keyboard())


async def cmd_strategies(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(_build_strategies(), reply_markup=_keyboard())


async def cmd_clv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(_build_clv_report(), reply_markup=_keyboard())


async def cmd_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(_build_risk(), reply_markup=_keyboard())


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard buttons — update the existing message."""
    query = update.callback_query
    await query.answer()

    view = query.data
    builder = VIEW_BUILDERS.get(view, _build_summary)
    text = builder()

    # Store current view for auto-refresh
    if ctx.job_queue:
        existing_job = ctx.chat_data.get(REFRESH_JOB_KEY)
        if existing_job:
            existing_job.data["view"] = view

    try:
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=_keyboard(),
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning("edit_message_text failed: %s", e)


async def _auto_refresh(ctx: ContextTypes.DEFAULT_TYPE):
    """Job that edits the terminal message every REFRESH_INTERVAL seconds."""
    data = ctx.job.data or {}
    view = data.get("view", "summary")
    chat_id = ctx.job.chat_id

    # Find the pinned message ID from chat_data
    chat_data = ctx.application.chat_data.get(chat_id, {})
    msg_id = chat_data.get(MESSAGE_ID_KEY)
    if not msg_id:
        return

    builder = VIEW_BUILDERS.get(view, _build_summary)
    text = builder()

    try:
        await ctx.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            parse_mode="HTML",
            reply_markup=_keyboard(),
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning("Auto-refresh edit failed: %s", e)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN not set. Export it as an environment variable.")
        sys.exit(1)

    init_db()

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("terminal",   cmd_terminal))
    app.add_handler(CommandHandler("stop",        cmd_stop))
    app.add_handler(CommandHandler("positions",   cmd_positions))
    app.add_handler(CommandHandler("history",     cmd_history))
    app.add_handler(CommandHandler("strategies",  cmd_strategies))
    app.add_handler(CommandHandler("clv",         cmd_clv))
    app.add_handler(CommandHandler("risk",        cmd_risk))
    app.add_handler(CallbackQueryHandler(on_button))

    logger.info("Polybot Telegram terminal starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
