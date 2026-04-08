import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd

from data import database, price_history
from tracking import clv


class PositionTimeoutTests(unittest.TestCase):
    def test_stale_open_bet_is_closed_and_returns_capital(self):
        db_path = os.path.join(os.getcwd(), "timeout_test_temp.db")
        for path in (db_path, f"{db_path}-journal"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass

        try:
            with patch.object(database, "DB_PATH", db_path), patch.object(price_history, "DB_PATH", db_path):
                database.init_db()
                bet_id = database.record_paper_bet(
                    market_id="m-timeout",
                    question="Timeout test?",
                    strategy_tag="momentum",
                    side="YES",
                    entry_price=0.40,
                    bet_size=20.0,
                    bankroll=1000.0,
                    kelly_raw=0.10,
                    edge_est=0.05,
                    confidence=0.60,
                    reason="test",
                )

                stale_ts = (datetime.now(UTC) - timedelta(hours=7)).replace(tzinfo=None).isoformat()
                with database._conn() as con:
                    con.execute("UPDATE paper_bets SET placed_at=? WHERE id=?", (stale_ts, bet_id))
                    con.commit()

                current_markets = pd.DataFrame(
                    [
                        {
                            "market_id": "m-timeout",
                            "yes_price": 0.52,
                            "no_price": 0.48,
                            "end_date": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
                        }
                    ]
                )

                with patch.object(clv, "fetch_markets", return_value=current_markets):
                    bankroll, stats = clv.settle_and_compute_clv(980.0)

                closed = database.get_closed_bets(limit=10)
                self.assertEqual(len(database.get_open_bets()), 0)
                self.assertEqual(len(closed), 1)
                self.assertEqual(closed.iloc[0]["result"], "timeout_win")
                self.assertAlmostEqual(float(closed.iloc[0]["exit_price"]), 0.52, places=5)
                self.assertGreater(bankroll, 980.0)
                self.assertEqual(stats["closed_count"], 1)
                self.assertEqual(stats["timeout_closed_count"], 1)
                self.assertEqual(stats["clv_resolved_count"], 1)
        finally:
            for path in (db_path, f"{db_path}-journal"):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except PermissionError:
                        pass


if __name__ == "__main__":
    unittest.main()
