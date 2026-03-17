"""Tests for daily budget checking."""

import sqlite3
import pytest
from engine.pipeline.budget import check_daily_budget, get_daily_spend, get_budget_cap


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            layer TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_created_at ON token_usage(created_at)")
    c.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    c.commit()
    yield c
    c.close()


class TestCheckDailyBudget:
    def test_no_usage_passes(self, conn):
        assert check_daily_budget(conn, cap_usd=2.0) is True

    def test_under_cap_passes(self, conn):
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            ("haiku", "episode", 100, 50, 0.50),
        )
        conn.commit()
        assert check_daily_budget(conn, cap_usd=2.0) is True

    def test_over_cap_rejected(self, conn):
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            ("opus", "distill", 1000, 500, 2.50),
        )
        conn.commit()
        assert check_daily_budget(conn, cap_usd=2.0) is False

    def test_exactly_at_cap_rejected(self, conn):
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            ("opus", "distill", 1000, 500, 2.00),
        )
        conn.commit()
        assert check_daily_budget(conn, cap_usd=2.0) is False

    def test_multiple_entries_sum(self, conn):
        for cost in [0.5, 0.6, 0.7]:
            conn.execute(
                "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                ("haiku", "episode", 100, 50, cost),
            )
        conn.commit()
        # Total = 1.8, under 2.0
        assert check_daily_budget(conn, cap_usd=2.0) is True
        # Total = 1.8, over 1.5
        assert check_daily_budget(conn, cap_usd=1.5) is False

    def test_old_usage_not_counted(self, conn):
        # Insert old record (2 days ago)
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now', '-2 days'))",
            ("opus", "distill", 1000, 500, 5.00),
        )
        conn.commit()
        assert check_daily_budget(conn, cap_usd=2.0) is True


class TestGetDailySpend:
    def test_no_usage(self, conn):
        assert get_daily_spend(conn) == 0.0

    def test_sums_today(self, conn):
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            ("haiku", "episode", 100, 50, 0.75),
        )
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            ("opus", "distill", 200, 100, 1.25),
        )
        conn.commit()
        assert get_daily_spend(conn) == pytest.approx(2.0)

    def test_excludes_old(self, conn):
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            ("haiku", "episode", 100, 50, 0.50),
        )
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now', '-2 days'))",
            ("opus", "distill", 200, 100, 3.00),
        )
        conn.commit()
        assert get_daily_spend(conn) == pytest.approx(0.50)


class TestGetBudgetCap:
    def test_default_when_no_state(self, conn):
        assert get_budget_cap(conn, default=2.0) == 2.0

    def test_reads_from_state_table(self, conn):
        conn.execute(
            "INSERT INTO state (key, value) VALUES ('daily_cost_cap_usd', '5.0')"
        )
        conn.commit()
        assert get_budget_cap(conn, default=2.0) == 5.0

    def test_check_budget_uses_db_cap(self, conn):
        """check_daily_budget should use DB cap over the passed default."""
        conn.execute(
            "INSERT INTO state (key, value) VALUES ('daily_cost_cap_usd', '10.0')"
        )
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES ('opus', 'distill', 1000, 500, 5.0)",
        )
        conn.commit()
        # Default cap=2.0 would reject, but DB cap=10.0 allows
        assert check_daily_budget(conn, cap_usd=2.0) is True

    def test_check_budget_falls_back_to_default(self, conn):
        """No DB state → use passed default."""
        conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES ('opus', 'distill', 1000, 500, 5.0)",
        )
        conn.commit()
        assert check_daily_budget(conn, cap_usd=2.0) is False
