"""Deterministic daily cost budget checking.

Layer 2 (architectural constraints): hard cap on daily LLM spend.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def get_daily_spend(conn: sqlite3.Connection) -> float:
    """Sum today's LLM costs from token_usage table."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) as total "
        "FROM token_usage "
        "WHERE created_at >= datetime('now', '-1 days')",
    ).fetchone()
    return float(row["total"] if isinstance(row, sqlite3.Row) else row[0])


def get_budget_cap(conn: sqlite3.Connection, default: float) -> float:
    """Read budget cap from state table, fallback to default."""
    row = conn.execute(
        "SELECT value FROM state WHERE key = 'daily_cost_cap_usd'",
    ).fetchone()
    if row:
        return float(row["value"] if isinstance(row, sqlite3.Row) else row[0])
    return default


def check_daily_budget(conn: sqlite3.Connection, cap_usd: float) -> bool:
    """Return True if today's spend is under the cap, False otherwise.

    Reads actual cap from DB state table (UI-settable), falls back to cap_usd.
    """
    actual_cap = get_budget_cap(conn, cap_usd)
    spend = get_daily_spend(conn)
    if spend >= actual_cap:
        logger.warning(
            "Daily budget exceeded: $%.4f >= $%.2f cap", spend, actual_cap,
        )
        return False
    return True
