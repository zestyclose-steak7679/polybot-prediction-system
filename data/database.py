"""data/database.py — full schema with CLV support"""
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from datetime import UTC, datetime, timedelta
from config import DB_PATH, ALERT_COOLDOWN_HOURS, MAX_POSITION_AGE_HOURS
from data.price_history import init_price_history

logger = logging.getLogger(__name__)
_MEMORY_ANCHOR = None

def _conn():
    global _MEMORY_ANCHOR
    is_uri = isinstance(DB_PATH, str) and DB_PATH.startswith("file:")
    if is_uri and "mode=memory" in DB_PATH and _MEMORY_ANCHOR is None:
        _MEMORY_ANCHOR = sqlite3.connect(DB_PATH, uri=True)
    con = sqlite3.connect(DB_PATH, uri=is_uri)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    return con


def _utc_now() -> datetime:
    """Return a naive UTC datetime for compatibility with existing storage."""
    return datetime.now(UTC).replace(tzinfo=None)


def _hours_open(placed_at: str) -> float:
    try:
        opened = datetime.fromisoformat(str(placed_at).replace("Z", "").split("+")[0])
        return max((_utc_now() - opened).total_seconds() / 3600, 0.0)
    except Exception:
        return 0.0


def _rebind_db_path(new_path: str):
    global DB_PATH, _MEMORY_ANCHOR
    DB_PATH = new_path
    try:
        import config as _config
        _config.DB_PATH = new_path
    except Exception:
        pass
    if isinstance(new_path, str) and new_path.startswith("file:") and "mode=memory" in new_path:
        _MEMORY_ANCHOR = sqlite3.connect(new_path, uri=True)
        _MEMORY_ANCHOR.execute("PRAGMA journal_mode=WAL")
        _MEMORY_ANCHOR.execute("PRAGMA synchronous=NORMAL")
        _MEMORY_ANCHOR.execute("PRAGMA temp_store=MEMORY")
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith(("data.", "models.", "learning.", "backtest.", "dashboard.", "risk.", "tracking.")):
            continue
        if hasattr(module, "DB_PATH"):
            setattr(module, "DB_PATH", new_path)

def init_db():
    if not Path(DB_PATH).exists():
        open(DB_PATH, "w").close()

    schema = """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT, question TEXT, side TEXT,
            strategy TEXT, score REAL, alerted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS paper_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT, question TEXT, strategy_tag TEXT,
            side TEXT, entry_price REAL, bet_size REAL,
            bankroll_at REAL, kelly_raw REAL, edge_est REAL,
            confidence REAL, reason TEXT, placed_at TEXT,
            result TEXT DEFAULT 'open',
            exit_price REAL, closing_price REAL,
            pnl REAL, roi REAL, clv REAL, closed_at TEXT,
            price_5m REAL, price_15m REAL, price_60m REAL,


            clv_5m REAL, clv_15m REAL, clv_60m REAL
        );
        CREATE TABLE IF NOT EXISTS market_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT, question TEXT, yes_price REAL,
            liquidity REAL, volume REAL, one_day_change REAL,
            strategy TEXT, signal_edge REAL, regime TEXT,
            logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS feature_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER, market_id TEXT,
            features_json TEXT, snapshot_at TEXT
        );
        CREATE TABLE IF NOT EXISTS clv_predictions (
            market_id TEXT PRIMARY KEY,
            entry_price REAL,
            predicted_clv REAL,
            signal_edge REAL,
            strategy TEXT,
            cycle_ts TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS alpha_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_ts TEXT NOT NULL,
            market_id TEXT NOT NULL,
            question TEXT,
            alpha_name TEXT NOT NULL,
            score REAL,
            predicted_clv REAL,
            direction TEXT,
            reason TEXT,
            shadow_only INTEGER DEFAULT 1,
            regime TEXT,
            entry_price REAL,
            passed_live_threshold INTEGER DEFAULT 0,
            feature_payload TEXT,
            closing_price REAL,
            resolved_clv REAL,
            resolution_state TEXT,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            question TEXT,
            strategy TEXT,
            side TEXT,
            entry_price REAL,
            exit_price REAL,
            bet_size REAL,
            pnl REAL,
            roi_pct REAL,
            clv REAL,
            edge_at_entry REAL,
            confidence REAL,
            regime TEXT,
            placed_at TEXT,
            closed_at TEXT,
            close_reason TEXT,
            hold_hours REAL,
            bankroll_at_entry REAL,
            bankroll_at_exit REAL
        );
        CREATE TABLE IF NOT EXISTS decision_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT,
            agent_id TEXT,
            decision TEXT,
            reason TEXT,
            confidence REAL,
            bet_size_before REAL,
            bet_size_after REAL,
            timestamp TEXT,
            clv_5m REAL,
            clv_15m REAL,
            clv_60m REAL,
            decision_quality_score REAL
        );
        CREATE INDEX IF NOT EXISTS idx_pb_strategy ON paper_bets(strategy_tag);
        CREATE INDEX IF NOT EXISTS idx_pb_result ON paper_bets(result);
        CREATE INDEX IF NOT EXISTS idx_alpha_market ON alpha_signals(market_id, cycle_ts);
        CREATE INDEX IF NOT EXISTS idx_alpha_name ON alpha_signals(alpha_name, cycle_ts);
        CREATE INDEX IF NOT EXISTS idx_alpha_resolved ON alpha_signals(resolved_clv);
        """
    try:
        with _conn() as con:
            con.executescript(schema)
            # Check and add columns for db upgrades
            try:
                con.execute("ALTER TABLE alpha_signals ADD COLUMN closing_price REAL")
                con.execute("ALTER TABLE alpha_signals ADD COLUMN resolved_clv REAL")
                con.execute("ALTER TABLE alpha_signals ADD COLUMN resolution_state TEXT")
                con.execute("ALTER TABLE alpha_signals ADD COLUMN resolved_at TEXT")
            except sqlite3.OperationalError:
                pass
            for col in ["price_5m", "price_15m", "price_60m", "clv_5m", "clv_15m", "clv_60m"]:
                try:
                    con.execute(f"ALTER TABLE paper_bets ADD COLUMN {col} REAL")
                except sqlite3.OperationalError:
                    pass
            try:
                con.execute("ALTER TABLE paper_bets ADD COLUMN mode TEXT DEFAULT 'ACTIVE'")
            except Exception:
                pass
            con.commit()
    except sqlite3.OperationalError as exc:
        if "disk I/O error" not in str(exc):
            raise
        journal_path = f"{DB_PATH}-journal"
        if os.path.exists(journal_path):
            logger.warning("Removing stale SQLite journal: %s", journal_path)
            try:
                os.remove(journal_path)
                with _conn() as con:
                    con.executescript(schema)
                    con.commit()
                init_price_history()
                logger.info("DB initialised.")
                return
            except PermissionError:
                logger.warning("Journal file is locked; falling back to a recovery DB.")
        if os.path.exists(DB_PATH):
            backup_path = f"{DB_PATH}.corrupt-{_utc_now().strftime('%Y%m%d%H%M%S')}.bak"
            logger.warning("DB disk I/O error detected. Backing up %s -> %s", DB_PATH, backup_path)
            try:
                os.replace(DB_PATH, backup_path)
                with _conn() as con:
                    con.executescript(schema)
                    con.commit()
            except PermissionError:
                root = os.path.splitext(os.path.basename(DB_PATH))[0] or "polybot"
                recovery_path = f"file:{root}_recovery?mode=memory&cache=shared"
                logger.warning("Primary DB is locked; switching this process to in-memory recovery DB %s", recovery_path)
                _rebind_db_path(recovery_path)
                with _conn() as con:
                    con.executescript(schema)
                    con.commit()
        else:
            raise
    init_price_history()
    logger.info("DB initialised.")

def was_recently_alerted(market_id):
    cutoff = (_utc_now() - timedelta(hours=ALERT_COOLDOWN_HOURS)).isoformat()
    with _conn() as con:
        return con.execute(
            "SELECT 1 FROM alerts WHERE market_id=? AND alerted_at>? LIMIT 1",
            (market_id, cutoff)).fetchone() is not None

def record_alert(market_id, question, side, strategy, score):
    with _conn() as con:
        con.execute(
            "INSERT INTO alerts (market_id,question,side,strategy,score,alerted_at) VALUES (?,?,?,?,?,?)",
            (market_id, question, side, strategy, score, _utc_now().isoformat()))
        con.commit()

def record_paper_bet(market_id, question, strategy_tag, side, entry_price,
                     bet_size, bankroll, kelly_raw, edge_est, confidence, reason):
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO paper_bets
               (market_id,question,strategy_tag,side,entry_price,bet_size,
                bankroll_at,kelly_raw,edge_est,confidence,reason,placed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (market_id, question, strategy_tag, side, entry_price, bet_size,
             bankroll, kelly_raw, edge_est, confidence, reason,
             _utc_now().isoformat()))
        con.commit()
        return cur.lastrowid

def save_feature_snapshot(trade_id, market_id, features_json):
    with _conn() as con:
        con.execute(
            "INSERT INTO feature_snapshots (trade_id,market_id,features_json,snapshot_at) VALUES (?,?,?,?)",
            (trade_id, market_id, features_json, _utc_now().isoformat()))
        con.commit()


def log_alpha_signals(alpha_signals: list, cycle_ts: str | None = None) -> int:
    if not alpha_signals:
        return 0

    cycle_ts = cycle_ts or _utc_now().isoformat()
    rows = []
    for signal in alpha_signals:
        payload = signal.feature_payload
        if not isinstance(payload, str):
            payload = json.dumps(payload, sort_keys=True)
        rows.append(
            (
                cycle_ts,
                signal.market_id,
                signal.question,
                signal.alpha_name,
                signal.score,
                signal.predicted_clv,
                signal.direction,
                signal.reason,
                int(signal.shadow_only),
                signal.regime,
                signal.entry_price,
                int(signal.passed_live_threshold),
                payload,
            )
        )

    with _conn() as con:
        con.executemany(
            """INSERT INTO alpha_signals
               (cycle_ts,market_id,question,alpha_name,score,predicted_clv,direction,
                reason,shadow_only,regime,entry_price,passed_live_threshold,feature_payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        con.commit()
    return len(rows)


def get_unresolved_alpha_signals(limit: int = 2000):
    with _conn() as con:
        return pd.read_sql(
            f"""SELECT *
                FROM alpha_signals
                WHERE resolved_clv IS NULL
                ORDER BY cycle_ts ASC
                LIMIT {limit}""",
            con,
        )


def resolve_alpha_signal(signal_id: int, closing_price: float, resolved_clv: float, resolution_state: str):
    with _conn() as con:
        con.execute(
            """UPDATE alpha_signals
               SET closing_price=?, resolved_clv=?, resolution_state=?, resolved_at=?
               WHERE id=?""",
            (
                closing_price,
                resolved_clv,
                resolution_state,
                _utc_now().isoformat(),
                signal_id,
            ),
        )
        con.commit()


def get_alpha_outcomes(limit: int = 5000):
    with _conn() as con:
        return pd.read_sql(
            f"""SELECT *
                FROM alpha_signals
                WHERE resolved_clv IS NOT NULL
                ORDER BY cycle_ts DESC
                LIMIT {limit}""",
            con,
        )


def get_recent_alpha_signals(limit: int = 50):
    with _conn() as con:
        return pd.read_sql(
            f"SELECT * FROM alpha_signals ORDER BY cycle_ts DESC LIMIT {limit}",
            con,
        )

def update_mid_price(bet_id: int, period: str, price: float, clv: float):
    if period not in ("5m", "15m", "60m"):
        return
    try:
        with _conn() as con:
            con.execute(
                f"UPDATE paper_bets SET price_{period}=?, clv_{period}=? WHERE id=?",
                (price, clv, bet_id)
            )
            con.commit()
    except Exception as e:
        logger.error(f"Error updating mid price for bet {bet_id}: {e}")

def get_open_bets():
    try:
        with _conn() as con:
            return pd.read_sql("SELECT * FROM paper_bets WHERE result='open'", con)
    except Exception as e:
        logger.error(f"Error getting open bets: {e}")
        return pd.DataFrame()


def get_open_position_stats() -> dict:
    open_bets = get_open_bets()
    if open_bets.empty:
        return {
            "n_open": 0,
            "avg_hold_hours": 0.0,
            "oldest_hold_hours": 0.0,
            "stale_count": 0,
        }

    hold_hours = open_bets["placed_at"].apply(_hours_open)
    return {
        "n_open": int(len(open_bets)),
        "avg_hold_hours": round(float(hold_hours.mean()), 2),
        "oldest_hold_hours": round(float(hold_hours.max()), 2),
        "stale_count": int((hold_hours >= MAX_POSITION_AGE_HOURS).sum()),
    }

def close_bet(bet_id, exit_price, closing_price, result, pnl, clv=None):
    try:
        with _conn() as con:
            bet = con.execute("SELECT bet_size FROM paper_bets WHERE id=?", (bet_id,)).fetchone()
            roi = round(pnl / bet[0], 4) if bet and bet[0] > 0 else 0.0
            con.execute(
                """UPDATE paper_bets SET result=?,exit_price=?,closing_price=?,
                   pnl=?,roi=?,clv=?,closed_at=? WHERE id=?""",
                (result, exit_price, closing_price, round(pnl,2), roi,
                 clv, _utc_now().isoformat(), bet_id))
            con.commit()
    except Exception as e:
        logger.error(f"Error closing bet {bet_id}: {e}")

def get_closed_bets(limit=500):
    try:
        with _conn() as con:
            df = pd.read_sql(f"SELECT * FROM paper_bets WHERE result!='open' ORDER BY placed_at DESC LIMIT {limit}", con)
            return df if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.error(f"Error getting closed bets: {e}")
        return pd.DataFrame()

def get_pnl_summary():
    with _conn() as con:
        total_bets = con.execute("SELECT COUNT(*) FROM paper_bets").fetchone()[0]

    rows = get_closed_bets()
    if rows.empty:
        return {
            "total_bets": total_bets,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "roi": 0.0,
            "avg_clv": None,
            "clv_resolved_bets": 0,
        }
    staked = rows["bet_size"].sum()
    wins = rows["result"].isin(["win", "timeout_win"])
    losses = rows["result"].isin(["loss", "timeout_loss"])
    clv_resolved = rows["clv"].notna()
    total_closed = len(rows)
    wins_count = int(wins.sum())
    win_rate = (wins_count / total_closed * 100) if total_closed > 0 else 0.0
    return {
        "total_bets": total_bets,
        "wins":       wins_count,
        "losses":     int(losses.sum()),
        "total_pnl":  round(rows["pnl"].sum(), 2),
        "win_rate":   round(win_rate, 1),
        "roi":        round(rows["pnl"].sum()/staked*100, 2) if staked>0 else 0.0,
        "avg_clv":    round(rows["clv"].dropna().mean(), 4) if rows["clv"].notna().any() else None,
        "clv_resolved_bets": int(clv_resolved.sum()),
    }

def log_market(market_id, question, yes_price, liquidity, volume,
               one_day_change, strategy, signal_edge, regime="unknown"):
    with _conn() as con:
        con.execute(
            """INSERT INTO market_log
               (market_id,question,yes_price,liquidity,volume,
                one_day_change,strategy,signal_edge,regime,logged_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (market_id, question, yes_price, liquidity, volume,
             one_day_change, strategy, signal_edge, regime,
             _utc_now().isoformat()))
        con.commit()

def record_trade_close(market_id: str, exit_price: float,
                        pnl: float, close_reason: str,
                        bankroll_at_exit: float) -> None:
    """Record trade closure to history."""
    try:
        with _conn() as conn:
            conn.execute("""
                UPDATE trade_history
                SET exit_price=?, pnl=?,
                    roi_pct=ROUND((? / bet_size) * 100, 2),
                    closed_at=datetime('now'),
                    close_reason=?,
                    hold_hours=ROUND((julianday('now') - julianday(placed_at)) * 24, 2),
                    bankroll_at_exit=?
                WHERE market_id=? AND closed_at IS NULL
            """, (exit_price, pnl, pnl, close_reason, bankroll_at_exit, market_id))
    except Exception as e:
        logger.error("record_trade_close failed: %s", e)

def get_trade_history(limit: int = 50) -> pd.DataFrame:
    """Get full trade history sorted by most recent."""
    try:
        with _conn() as conn:
            return pd.read_sql("""
                SELECT market_id, question, strategy, side,
                       entry_price, exit_price, bet_size, pnl,
                       roi_pct, clv, regime, placed_at, closed_at,
                       close_reason, hold_hours
                FROM trade_history
                ORDER BY placed_at DESC
                LIMIT ?
            """, conn, params=(limit,))
    except Exception as e:
        logger.error("get_trade_history failed: %s", e)
        return pd.DataFrame()

def get_open_positions_detail() -> pd.DataFrame:
    """Get all open positions with current market context."""
    try:
        with _conn() as conn:
            return pd.read_sql("""
                SELECT
                    pb.market_id,
                    pb.question,
                    pb.strategy_tag as strategy,
                    pb.side,
                    pb.entry_price,
                    pb.bet_size,
                    pb.edge_est,
                    pb.confidence,
                    pb.placed_at,
                    ROUND((julianday('now') - julianday(pb.placed_at)) * 24, 1) as hold_hours,
                    ph.yes_price as current_price,
                    ROUND(
                        CASE pb.side
                            WHEN 'YES' THEN (ph.yes_price - pb.entry_price) * pb.bet_size
                            ELSE (pb.entry_price - ph.yes_price) * pb.bet_size
                        END, 2
                    ) as unrealised_pnl
                FROM paper_bets pb
                LEFT JOIN (
                    SELECT market_id, yes_price,
                           ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY logged_at DESC) as rn
                    FROM price_history
                ) ph ON pb.market_id = ph.market_id AND ph.rn = 1
                WHERE pb.result = 'open'
                ORDER BY pb.placed_at DESC
            """, conn)
    except Exception as e:
        logger.error("get_open_positions_detail failed: %s", e)
        return pd.DataFrame()

def record_decision(
    market_id: str,
    agent_id: str,
    decision: str,
    reason: str,
    confidence: float,
    bet_size_before: float,
    bet_size_after: float
):
    try:
        ts = datetime.now(UTC).replace(tzinfo=None).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO decision_log
                (market_id, agent_id, decision, reason, confidence, bet_size_before, bet_size_after, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (market_id, agent_id, decision, reason, confidence, bet_size_before, bet_size_after, ts)
            )
    except Exception as e:
        logger.error(f"Error logging decision for {market_id}: {e}")

def get_unscored_decisions() -> pd.DataFrame:
    query = """
        SELECT * FROM decision_log
        WHERE decision_quality_score IS NULL
    """
    return query_to_df(query)

def update_decision_score(decision_id: int, clv_5m: float, clv_15m: float, clv_60m: float, score: float):
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE decision_log
                SET clv_5m = ?, clv_15m = ?, clv_60m = ?, decision_quality_score = ?
                WHERE id = ?
                """,
                (clv_5m, clv_15m, clv_60m, score, decision_id)
            )
    except Exception as e:
        logger.error(f"Error updating decision score for {decision_id}: {e}")
