"""Agents data access — episode search, playbook/routine CRUD, audit, dedup, trend.

All queries that agent tools need, centralized here.
"""

import json
import logging
import os
import sqlite3

logger = logging.getLogger(__name__)


# ── Episode queries ──


def search_episodes(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    """Search episode summaries. Splits multi-word queries into individual LIKE clauses."""
    words = query.strip().split()
    if len(words) > 1:
        where = " AND ".join("summary LIKE ?" for _ in words)
        params = [f"%{w}%" for w in words]
    else:
        where = "summary LIKE ?"
        params = [f"%{query}%"]
    rows = conn.execute(
        f"SELECT id, summary, app_names, started_at, ended_at "
        f"FROM episodes WHERE {where} ORDER BY id DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_episodes(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    rows = conn.execute(
        "SELECT id, summary, app_names, started_at, ended_at "
        "FROM episodes WHERE created_at >= datetime('now', ?) ORDER BY created_at DESC",
        (f"-{hours} hours",),
    ).fetchall()
    return [dict(r) for r in rows]


def get_episodes_by_app(conn: sqlite3.Connection, app_name: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, summary, app_names, started_at, ended_at "
        "FROM episodes WHERE app_names LIKE ? ORDER BY id DESC LIMIT 20",
        (f"%{app_name}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def get_episode_detail(conn: sqlite3.Connection, episode_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    return dict(row) if row else None


def get_episode_frames(conn: sqlite3.Connection, episode_id: int, limit: int = 10) -> list[dict]:
    ep = conn.execute(
        "SELECT frame_id_min, frame_id_max FROM episodes WHERE id = ?", (episode_id,),
    ).fetchone()
    if not ep:
        return []
    rows = conn.execute(
        "SELECT id, timestamp, app_name, window_name, substr(text, 1, 200) as text "
        "FROM frames WHERE id BETWEEN ? AND ? ORDER BY id LIMIT ?",
        (ep["frame_id_min"], ep["frame_id_max"], limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Raw capture queries ──


def get_recent_frames(conn: sqlite3.Connection, hours: int = 24, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, timestamp, app_name, window_name, "
        "substr(text, 1, 300) as text, display_id "
        "FROM frames WHERE created_at >= datetime('now', ?) ORDER BY id DESC LIMIT ?",
        (f"-{hours} hours", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_frames_by_app(conn: sqlite3.Connection, app_name: str, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT id, timestamp, app_name, window_name, "
        "substr(text, 1, 300) as text, display_id "
        "FROM frames WHERE app_name LIKE ? ORDER BY id DESC LIMIT ?",
        (f"%{app_name}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_audio(conn: sqlite3.Connection, hours: int = 24, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, timestamp, text, language, duration_seconds, source "
        "FROM audio_frames WHERE created_at >= datetime('now', ?) ORDER BY id DESC LIMIT ?",
        (f"-{hours} hours", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_os_events(conn: sqlite3.Connection, hours: int = 24, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, timestamp, event_type, source, data "
        "FROM os_events WHERE created_at >= datetime('now', ?) ORDER BY id DESC LIMIT ?",
        (f"-{hours} hours", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_os_events_by_type(conn: sqlite3.Connection, event_type: str, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT id, timestamp, event_type, source, data "
        "FROM os_events WHERE event_type = ? ORDER BY id DESC LIMIT ?",
        (event_type, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Playbook CRUD ──


def get_all_playbook_entries(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT name, context, action, confidence, maturity, evidence "
        "FROM playbook_entries ORDER BY confidence DESC",
    ).fetchall()
    return [dict(r) for r in rows]


def get_playbook_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM playbook_entries WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def get_playbook_by_id(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM playbook_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def write_playbook_entry(
    conn: sqlite3.Connection,
    name: str, context: str, action: str,
    confidence: float, maturity: str, evidence: str,
):
    conn.execute(
        "INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(name) DO UPDATE SET "
        "context=excluded.context, action=excluded.action, "
        "confidence=excluded.confidence, maturity=excluded.maturity, "
        "evidence=excluded.evidence, updated_at=datetime('now')",
        (name, context, action, confidence, maturity, evidence),
    )


def delete_playbook_entry(conn: sqlite3.Connection, entry_id: int):
    conn.execute("DELETE FROM playbook_entries WHERE id = ?", (entry_id,))


def update_playbook_confidence(conn: sqlite3.Connection, entry_id: int, confidence: float):
    conn.execute(
        "UPDATE playbook_entries SET confidence = ? WHERE id = ?",
        (confidence, entry_id),
    )


# ── Playbook history ──


def get_playbook_history(conn: sqlite3.Connection, name: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM playbook_history WHERE playbook_name = ? ORDER BY created_at",
        (name,),
    ).fetchall()
    return [dict(r) for r in rows]


def record_snapshot(conn: sqlite3.Connection, name: str, reason: str = "") -> dict:
    """Record snapshot of a playbook entry (convenience wrapper)."""
    entry = get_playbook_by_name(conn, name)
    if not entry:
        return {"error": f"Entry '{name}' not found"}
    record_playbook_snapshot(
        conn, name, entry["confidence"], entry.get("maturity") or "nascent",
        entry.get("evidence") or "[]", reason,
    )
    return {"name": name, "snapshot_confidence": entry["confidence"],
            "snapshot_maturity": entry.get("maturity"), "reason": reason}


def record_playbook_snapshot(
    conn: sqlite3.Connection, name: str,
    confidence: float, maturity: str, evidence: str, reason: str = "",
):
    conn.execute(
        "INSERT INTO playbook_history (playbook_name, confidence, maturity, evidence, change_reason) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, confidence, maturity, evidence, reason),
    )
    conn.commit()


# ── Routines ──


def get_all_routines(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT name, trigger, goal, steps, uses, confidence, maturity "
        "FROM routines ORDER BY confidence DESC",
    ).fetchall()
    return [dict(r) for r in rows]


def write_routine(
    conn: sqlite3.Connection,
    name: str, trigger: str, goal: str,
    steps: str, uses: str, confidence: float, maturity: str,
):
    conn.execute(
        "INSERT INTO routines (name, trigger, goal, steps, uses, confidence, maturity, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(name) DO UPDATE SET "
        "trigger=excluded.trigger, goal=excluded.goal, steps=excluded.steps, "
        "uses=excluded.uses, confidence=excluded.confidence, maturity=excluded.maturity, "
        "updated_at=datetime('now')",
        (name, trigger, goal, steps, uses, confidence, maturity),
    )


# ── Trend queries ──


def get_stale_entries(conn: sqlite3.Connection, days: int = 14) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, confidence, maturity, evidence, last_evidence_at, updated_at "
        "FROM playbook_entries "
        "WHERE last_evidence_at IS NULL OR last_evidence_at < datetime('now', ?) "
        "ORDER BY confidence DESC",
        (f"-{days} days",),
    ).fetchall()
    return [dict(r) for r in rows]


def get_similar_entries(conn: sqlite3.Connection, name: str) -> list[dict]:
    """Find entries with similar names (Jaccard on hyphen-split words, > 0.3)."""
    target_words = set(name.split("-"))
    if not target_words:
        return []
    rows = conn.execute(
        "SELECT id, name, confidence, maturity, context, evidence FROM playbook_entries "
        "WHERE name != ? ORDER BY confidence DESC",
        (name,),
    ).fetchall()
    results = []
    for r in rows:
        other_words = set(r["name"].split("-"))
        intersection = target_words & other_words
        union = target_words | other_words
        similarity = len(intersection) / len(union) if union else 0
        if similarity > 0.3:
            entry = dict(r)
            entry["similarity"] = round(similarity, 2)
            results.append(entry)
    return sorted(results, key=lambda x: x["similarity"], reverse=True)


# ── Dedup ──


def find_similar_pairs(conn: sqlite3.Connection, threshold: float = 0.8) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, confidence, maturity, context FROM playbook_entries ORDER BY confidence DESC"
    ).fetchall()
    entries = [(dict(r), set(r["name"].split("-"))) for r in rows]
    pairs = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            e1, w1 = entries[i]
            e2, w2 = entries[j]
            sim = len(w1 & w2) / len(w1 | w2) if (w1 | w2) else 0
            if sim >= threshold:
                pairs.append({
                    "entry_a": {"id": e1["id"], "name": e1["name"], "confidence": e1["confidence"]},
                    "entry_b": {"id": e2["id"], "name": e2["name"], "confidence": e2["confidence"]},
                    "similarity": round(sim, 2),
                })
    return pairs


def merge_entries(conn: sqlite3.Connection, keep_id: int, remove_id: int) -> dict:
    keep = conn.execute("SELECT * FROM playbook_entries WHERE id = ?", (keep_id,)).fetchone()
    remove = conn.execute("SELECT * FROM playbook_entries WHERE id = ?", (remove_id,)).fetchone()
    if not keep or not remove:
        return {"error": "One or both entries not found"}
    try:
        keep_ev = json.loads(keep["evidence"]) if keep["evidence"] else []
    except (json.JSONDecodeError, TypeError):
        keep_ev = []
    try:
        remove_ev = json.loads(remove["evidence"]) if remove["evidence"] else []
    except (json.JSONDecodeError, TypeError):
        remove_ev = []
    merged = sorted(set(keep_ev + remove_ev))
    new_conf = max(keep["confidence"], remove["confidence"])
    conn.execute(
        "UPDATE playbook_entries SET confidence = ?, evidence = ?, updated_at = datetime('now') WHERE id = ?",
        (new_conf, json.dumps(merged), keep_id),
    )
    conn.execute("DELETE FROM playbook_entries WHERE id = ?", (remove_id,))
    conn.commit()
    logger.info("Merged: kept %s (id=%d), removed %s (id=%d)", keep["name"], keep_id, remove["name"], remove_id)
    return {"kept": keep["name"], "removed": remove["name"], "new_confidence": new_conf, "merged_evidence": merged}


# ── Audit / GC ──


def check_evidence_exists(conn: sqlite3.Connection, entry_name: str) -> dict:
    row = conn.execute("SELECT id, name, evidence FROM playbook_entries WHERE name = ?", (entry_name,)).fetchone()
    if not row:
        return {"error": f"Entry '{entry_name}' not found"}
    try:
        ids = json.loads(row["evidence"]) if row["evidence"] else []
    except (json.JSONDecodeError, TypeError):
        ids = []
    if not ids:
        return {"name": entry_name, "evidence_ids": [], "missing": [], "all_exist": True}
    ph = ",".join("?" * len(ids))
    existing = conn.execute(f"SELECT id FROM episodes WHERE id IN ({ph})", ids).fetchall()
    existing_ids = {r["id"] for r in existing}
    missing = [eid for eid in ids if eid not in existing_ids]
    return {"name": entry_name, "evidence_ids": ids, "missing": missing, "all_exist": len(missing) == 0}


def check_maturity_consistency(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, confidence, maturity, evidence FROM playbook_entries").fetchall()
    inconsistent = []
    for r in rows:
        try:
            evidence = json.loads(r["evidence"]) if r["evidence"] else []
        except (json.JSONDecodeError, TypeError):
            evidence = []
        count = len(evidence)
        mat = r["maturity"] or "nascent"
        issue = None
        if mat in ("mature", "mastered") and count < 8:
            issue = f"{mat} with only {count} evidence episodes (expected >= 8)"
        elif mat == "developing" and count < 3:
            issue = f"developing with only {count} evidence episodes (expected >= 3)"
        if issue:
            inconsistent.append({
                "id": r["id"], "name": r["name"], "maturity": mat,
                "evidence_count": count, "confidence": r["confidence"], "issue": issue,
            })
    return inconsistent


def deprecate_entry(conn: sqlite3.Connection, entry_id: int, reason: str = "") -> dict:
    row = conn.execute(
        "SELECT name, confidence, maturity, evidence FROM playbook_entries WHERE id = ?", (entry_id,),
    ).fetchone()
    if not row:
        return {"error": f"Entry id={entry_id} not found"}
    record_playbook_snapshot(conn, row["name"], row["confidence"], row["maturity"] or "nascent",
                             row["evidence"] or "[]", reason=f"deprecated: {reason}")
    conn.execute(
        "UPDATE playbook_entries SET confidence = 0.0, maturity = 'nascent', updated_at = datetime('now') WHERE id = ?",
        (entry_id,),
    )
    conn.commit()
    logger.info("Deprecated %s (id=%d): %s", row["name"], entry_id, reason)
    return {"name": row["name"], "deprecated": True, "reason": reason}


def get_data_stats(conn: sqlite3.Connection) -> dict:
    stats = {}
    for table, has_processed in [("frames", True), ("audio_frames", True), ("os_events", True), ("pipeline_logs", False)]:
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if has_processed:
            processed = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE processed = 1").fetchone()[0]
            stats[table] = {"total": total, "processed": processed, "unprocessed": total - processed}
        else:
            stats[table] = {"total": total}
    return stats


def get_oldest_processed(conn: sqlite3.Connection) -> dict:
    result = {}
    for table in ("frames", "audio_frames", "os_events"):
        row = conn.execute(f"SELECT MIN(created_at) as oldest FROM {table} WHERE processed = 1").fetchone()
        result[table] = row["oldest"] if row and row["oldest"] else None
    row = conn.execute("SELECT MIN(created_at) as oldest FROM pipeline_logs").fetchone()
    result["pipeline_logs"] = row["oldest"] if row and row["oldest"] else None
    return result


def purge_processed_frames(conn: sqlite3.Connection, older_than_days: int) -> dict:
    rows = conn.execute(
        "SELECT id, image_path FROM frames WHERE processed = 1 AND created_at < datetime('now', ?)",
        (f"-{older_than_days} days",),
    ).fetchall()
    if not rows:
        return {"deleted": 0, "files_deleted": 0}
    files_deleted = 0
    for r in rows:
        if r["image_path"]:
            try:
                os.remove(r["image_path"])
                files_deleted += 1
            except OSError:
                pass
    ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM frames WHERE id IN ({ph})", ids)
    conn.commit()
    return {"deleted": len(ids), "files_deleted": files_deleted}


def purge_processed_audio(conn: sqlite3.Connection, older_than_days: int) -> dict:
    rows = conn.execute(
        "SELECT id, chunk_path FROM audio_frames WHERE processed = 1 AND created_at < datetime('now', ?)",
        (f"-{older_than_days} days",),
    ).fetchall()
    if not rows:
        return {"deleted": 0, "files_deleted": 0}
    files_deleted = 0
    for r in rows:
        if r["chunk_path"]:
            try:
                os.remove(r["chunk_path"])
                files_deleted += 1
            except OSError:
                pass
    ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM audio_frames WHERE id IN ({ph})", ids)
    conn.commit()
    return {"deleted": len(ids), "files_deleted": files_deleted}


def purge_processed_os_events(conn: sqlite3.Connection, older_than_days: int) -> dict:
    cur = conn.execute(
        "DELETE FROM os_events WHERE processed = 1 AND created_at < datetime('now', ?)",
        (f"-{older_than_days} days",),
    )
    conn.commit()
    return {"deleted": cur.rowcount}


def purge_pipeline_logs(conn: sqlite3.Connection, older_than_days: int) -> dict:
    cur = conn.execute(
        "DELETE FROM pipeline_logs WHERE created_at < datetime('now', ?)",
        (f"-{older_than_days} days",),
    )
    conn.commit()
    return {"deleted": cur.rowcount}
