"""Pipeline data access — decay, budget."""

import sqlite3

from engine.storage.session import ago


def get_all_playbooks_for_decay(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, confidence, last_evidence_at FROM playbook_entries"
    ).fetchall()
    return [dict(r) for r in rows]


def update_confidence(conn: sqlite3.Connection, entry_id: int, confidence: float):
    conn.execute(
        "UPDATE playbook_entries SET confidence = ? WHERE id = ?",
        (confidence, entry_id),
    )


def get_daily_spend(conn: sqlite3.Connection) -> float:
    cutoff = ago(days=1)
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) as total "
        "FROM token_usage WHERE created_at >= ?",
        (cutoff,),
    ).fetchone()
    return float(row["total"] if isinstance(row, sqlite3.Row) else row[0])


def get_budget_cap(conn: sqlite3.Connection, default: float) -> float:
    row = conn.execute(
        "SELECT value FROM state WHERE key = 'daily_cost_cap_usd'",
    ).fetchone()
    if row:
        return float(row["value"] if isinstance(row, sqlite3.Row) else row[0])
    return default
