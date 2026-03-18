"""Agents data access — episode search, playbook/routine CRUD, audit, dedup, trend.

All queries that agent tools need, centralized here. Uses SQLAlchemy ORM.
"""

import json
import logging
import os
import sqlite3

from sqlalchemy import select, func, delete

from engine.storage.session import get_session, ago
from engine.storage.models import (
    Frame as FrameModel, AudioFrame, OsEvent, Episode,
    PlaybookEntry, PlaybookHistory, Routine, PipelineLog,
)

logger = logging.getLogger(__name__)


# ── Episode queries ──


def search_episodes(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    s = get_session(conn)
    words = query.strip().split()
    stmt = select(Episode.id, Episode.summary, Episode.app_names, Episode.started_at, Episode.ended_at)
    if len(words) > 1:
        for w in words:
            stmt = stmt.where(Episode.summary.contains(w))
    else:
        stmt = stmt.where(Episode.summary.contains(query))
    rows = s.execute(stmt.order_by(Episode.id.desc()).limit(limit)).all()
    s.close()
    return [{"id": r[0], "summary": r[1], "app_names": r[2], "started_at": r[3], "ended_at": r[4]} for r in rows]


def get_recent_episodes(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(Episode.id, Episode.summary, Episode.app_names, Episode.started_at, Episode.ended_at)
        .where(Episode.created_at >= ago(hours=hours))
        .order_by(Episode.created_at.desc())
    ).all()
    s.close()
    return [{"id": r[0], "summary": r[1], "app_names": r[2], "started_at": r[3], "ended_at": r[4]} for r in rows]


def get_episodes_by_app(conn: sqlite3.Connection, app_name: str) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(Episode.id, Episode.summary, Episode.app_names, Episode.started_at, Episode.ended_at)
        .where(Episode.app_names.contains(app_name))
        .order_by(Episode.id.desc()).limit(20)
    ).all()
    s.close()
    return [{"id": r[0], "summary": r[1], "app_names": r[2], "started_at": r[3], "ended_at": r[4]} for r in rows]


def get_episode_detail(conn: sqlite3.Connection, episode_id: int) -> dict | None:
    s = get_session(conn)
    row = s.execute(select(Episode).where(Episode.id == episode_id)).scalar_one_or_none()
    if not row:
        s.close()
        return None
    result = _ep_dict(row)
    s.close()
    return result


def get_episode_frames(conn: sqlite3.Connection, episode_id: int, limit: int = 10) -> list[dict]:
    s = get_session(conn)
    ep = s.execute(
        select(Episode.frame_id_min, Episode.frame_id_max).where(Episode.id == episode_id)
    ).one_or_none()
    if not ep:
        s.close()
        return []
    rows = s.execute(
        select(FrameModel.id, FrameModel.timestamp, FrameModel.app_name,
               FrameModel.window_name, func.substr(FrameModel.text, 1, 200).label("text"))
        .where(FrameModel.id.between(ep[0], ep[1]))
        .order_by(FrameModel.id).limit(limit)
    ).all()
    s.close()
    return [{"id": r[0], "timestamp": r[1], "app_name": r[2], "window_name": r[3], "text": r[4]} for r in rows]


# ── Raw capture queries ──


def get_recent_frames(conn: sqlite3.Connection, hours: int = 24, limit: int = 50) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(FrameModel.id, FrameModel.timestamp, FrameModel.app_name,
               FrameModel.window_name, func.substr(FrameModel.text, 1, 300).label("text"),
               FrameModel.display_id)
        .where(FrameModel.created_at >= ago(hours=hours))
        .order_by(FrameModel.id.desc()).limit(limit)
    ).all()
    s.close()
    return [{"id": r[0], "timestamp": r[1], "app_name": r[2], "window_name": r[3],
             "text": r[4], "display_id": r[5]} for r in rows]


def get_frames_by_app(conn: sqlite3.Connection, app_name: str, limit: int = 30) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(FrameModel.id, FrameModel.timestamp, FrameModel.app_name,
               FrameModel.window_name, func.substr(FrameModel.text, 1, 300).label("text"),
               FrameModel.display_id)
        .where(FrameModel.app_name.contains(app_name))
        .order_by(FrameModel.id.desc()).limit(limit)
    ).all()
    s.close()
    return [{"id": r[0], "timestamp": r[1], "app_name": r[2], "window_name": r[3],
             "text": r[4], "display_id": r[5]} for r in rows]


def get_recent_audio(conn: sqlite3.Connection, hours: int = 24, limit: int = 50) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(AudioFrame.id, AudioFrame.timestamp, AudioFrame.text,
               AudioFrame.language, AudioFrame.duration_seconds, AudioFrame.source)
        .where(AudioFrame.created_at >= ago(hours=hours))
        .order_by(AudioFrame.id.desc()).limit(limit)
    ).all()
    s.close()
    return [{"id": r[0], "timestamp": r[1], "text": r[2], "language": r[3],
             "duration_seconds": r[4], "source": r[5]} for r in rows]


def get_recent_os_events(conn: sqlite3.Connection, hours: int = 24, limit: int = 50) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(OsEvent.id, OsEvent.timestamp, OsEvent.event_type, OsEvent.source, OsEvent.data)
        .where(OsEvent.created_at >= ago(hours=hours))
        .order_by(OsEvent.id.desc()).limit(limit)
    ).all()
    s.close()
    return [{"id": r[0], "timestamp": r[1], "event_type": r[2], "source": r[3], "data": r[4]} for r in rows]


def get_os_events_by_type(conn: sqlite3.Connection, event_type: str, limit: int = 30) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(OsEvent.id, OsEvent.timestamp, OsEvent.event_type, OsEvent.source, OsEvent.data)
        .where(OsEvent.event_type == event_type)
        .order_by(OsEvent.id.desc()).limit(limit)
    ).all()
    s.close()
    return [{"id": r[0], "timestamp": r[1], "event_type": r[2], "source": r[3], "data": r[4]} for r in rows]


# ── Playbook CRUD ──


def get_all_playbook_entries(conn: sqlite3.Connection) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(PlaybookEntry.name, PlaybookEntry.context, PlaybookEntry.action,
               PlaybookEntry.confidence, PlaybookEntry.maturity, PlaybookEntry.evidence)
        .order_by(PlaybookEntry.confidence.desc())
    ).all()
    s.close()
    return [{"name": r[0], "context": r[1], "action": r[2], "confidence": r[3],
             "maturity": r[4], "evidence": r[5]} for r in rows]


def get_playbook_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    s = get_session(conn)
    row = s.execute(select(PlaybookEntry).where(PlaybookEntry.name == name)).scalar_one_or_none()
    result = _pb_dict(row) if row else None
    s.close()
    return result


def get_playbook_by_id(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    s = get_session(conn)
    row = s.get(PlaybookEntry, entry_id)
    result = _pb_dict(row) if row else None
    s.close()
    return result


def write_playbook_entry(
    conn: sqlite3.Connection,
    name: str, context: str, action: str,
    confidence: float, maturity: str, evidence: str,
):
    s = get_session(conn)
    existing = s.execute(select(PlaybookEntry).where(PlaybookEntry.name == name)).scalar_one_or_none()
    if existing:
        existing.context = context
        existing.action = action
        existing.confidence = confidence
        existing.maturity = maturity
        existing.evidence = evidence
        existing.updated_at = func.now()
    else:
        s.add(PlaybookEntry(
            name=name, context=context, action=action,
            confidence=confidence, maturity=maturity, evidence=evidence,
        ))
    s.flush()
    s.close()


def delete_playbook_entry(conn: sqlite3.Connection, entry_id: int):
    s = get_session(conn)
    s.execute(delete(PlaybookEntry).where(PlaybookEntry.id == entry_id))
    s.flush()
    s.close()


# ── Playbook history ──


def get_playbook_history(conn: sqlite3.Connection, name: str) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(PlaybookHistory).where(PlaybookHistory.playbook_name == name)
        .order_by(PlaybookHistory.created_at)
    ).scalars().all()
    result = [
        {"id": r.id, "playbook_name": r.playbook_name, "confidence": r.confidence,
         "maturity": r.maturity, "evidence": r.evidence,
         "change_reason": r.change_reason, "created_at": r.created_at}
        for r in rows
    ]
    s.close()
    return result


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
    s = get_session(conn)
    s.add(PlaybookHistory(
        playbook_name=name, confidence=confidence,
        maturity=maturity, evidence=evidence, change_reason=reason,
    ))
    s.commit()
    s.close()


# ── Routines ──


def get_all_routines(conn: sqlite3.Connection) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(Routine.name, Routine.trigger, Routine.goal, Routine.steps,
               Routine.uses, Routine.confidence, Routine.maturity)
        .order_by(Routine.confidence.desc())
    ).all()
    s.close()
    return [{"name": r[0], "trigger": r[1], "goal": r[2], "steps": r[3],
             "uses": r[4], "confidence": r[5], "maturity": r[6]} for r in rows]


def write_routine(
    conn: sqlite3.Connection,
    name: str, trigger: str, goal: str,
    steps: str, uses: str, confidence: float, maturity: str,
):
    s = get_session(conn)
    existing = s.execute(select(Routine).where(Routine.name == name)).scalar_one_or_none()
    if existing:
        existing.trigger = trigger
        existing.goal = goal
        existing.steps = steps
        existing.uses = uses
        existing.confidence = confidence
        existing.maturity = maturity
        existing.updated_at = func.now()
    else:
        s.add(Routine(
            name=name, trigger=trigger, goal=goal,
            steps=steps, uses=uses, confidence=confidence, maturity=maturity,
        ))
    s.flush()
    s.close()


# ── Trend queries ──


def get_stale_entries(conn: sqlite3.Connection, days: int = 14) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(PlaybookEntry)
        .where((PlaybookEntry.last_evidence_at.is_(None))
               | (PlaybookEntry.last_evidence_at < ago(days=days)))
        .order_by(PlaybookEntry.confidence.desc())
    ).scalars().all()
    result = [
        {"id": r.id, "name": r.name, "confidence": r.confidence, "maturity": r.maturity,
         "evidence": r.evidence, "last_evidence_at": r.last_evidence_at, "updated_at": r.updated_at}
        for r in rows
    ]
    s.close()
    return result


def get_similar_entries(conn: sqlite3.Connection, name: str) -> list[dict]:
    target_words = set(name.split("-"))
    if not target_words:
        return []
    s = get_session(conn)
    rows = s.execute(
        select(PlaybookEntry).where(PlaybookEntry.name != name)
        .order_by(PlaybookEntry.confidence.desc())
    ).scalars().all()
    results = []
    for r in rows:
        other_words = set(r.name.split("-"))
        intersection = target_words & other_words
        union = target_words | other_words
        sim = len(intersection) / len(union) if union else 0
        if sim > 0.3:
            entry = _pb_dict(r)
            entry["similarity"] = round(sim, 2)
            results.append(entry)
    s.close()
    return sorted(results, key=lambda x: x["similarity"], reverse=True)


# ── Dedup ──


def find_similar_pairs(conn: sqlite3.Connection, threshold: float = 0.8) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(
        select(PlaybookEntry.id, PlaybookEntry.name, PlaybookEntry.confidence,
               PlaybookEntry.maturity, PlaybookEntry.context)
        .order_by(PlaybookEntry.confidence.desc())
    ).all()
    s.close()
    entries = [({"id": r[0], "name": r[1], "confidence": r[2]}, set(r[1].split("-"))) for r in rows]
    pairs = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            e1, w1 = entries[i]
            e2, w2 = entries[j]
            sim = len(w1 & w2) / len(w1 | w2) if (w1 | w2) else 0
            if sim >= threshold:
                pairs.append({"entry_a": e1, "entry_b": e2, "similarity": round(sim, 2)})
    return pairs


def merge_entries(conn: sqlite3.Connection, keep_id: int, remove_id: int) -> dict:
    s = get_session(conn)
    keep = s.get(PlaybookEntry, keep_id)
    remove = s.get(PlaybookEntry, remove_id)
    if not keep or not remove:
        s.close()
        return {"error": "One or both entries not found"}
    try:
        keep_ev = json.loads(keep.evidence) if keep.evidence else []
    except (json.JSONDecodeError, TypeError):
        keep_ev = []
    try:
        remove_ev = json.loads(remove.evidence) if remove.evidence else []
    except (json.JSONDecodeError, TypeError):
        remove_ev = []
    merged = sorted(set(keep_ev + remove_ev))
    new_conf = max(keep.confidence, remove.confidence)
    keep.confidence = new_conf
    keep.evidence = json.dumps(merged)
    keep.updated_at = func.now()
    s.delete(remove)
    s.commit()
    logger.info("Merged: kept %s (id=%d), removed %s (id=%d)", keep.name, keep_id, remove.name, remove_id)
    result = {"kept": keep.name, "removed": remove.name, "new_confidence": new_conf, "merged_evidence": merged}
    s.close()
    return result


# ── Audit / GC ──


def check_evidence_exists(conn: sqlite3.Connection, entry_name: str) -> dict:
    s = get_session(conn)
    row = s.execute(select(PlaybookEntry).where(PlaybookEntry.name == entry_name)).scalar_one_or_none()
    if not row:
        s.close()
        return {"error": f"Entry '{entry_name}' not found"}
    try:
        ids = json.loads(row.evidence) if row.evidence else []
    except (json.JSONDecodeError, TypeError):
        ids = []
    if not ids:
        s.close()
        return {"name": entry_name, "evidence_ids": [], "missing": [], "all_exist": True}
    existing = s.execute(select(Episode.id).where(Episode.id.in_(ids))).scalars().all()
    existing_set = set(existing)
    missing = [eid for eid in ids if eid not in existing_set]
    s.close()
    return {"name": entry_name, "evidence_ids": ids, "missing": missing, "all_exist": len(missing) == 0}


def check_maturity_consistency(conn: sqlite3.Connection) -> list[dict]:
    s = get_session(conn)
    rows = s.execute(select(PlaybookEntry)).scalars().all()
    inconsistent = []
    for r in rows:
        try:
            evidence = json.loads(r.evidence) if r.evidence else []
        except (json.JSONDecodeError, TypeError):
            evidence = []
        count = len(evidence)
        mat = r.maturity or "nascent"
        issue = None
        if mat in ("mature", "mastered") and count < 8:
            issue = f"{mat} with only {count} evidence episodes (expected >= 8)"
        elif mat == "developing" and count < 3:
            issue = f"developing with only {count} evidence episodes (expected >= 3)"
        if issue:
            inconsistent.append({
                "id": r.id, "name": r.name, "maturity": mat,
                "evidence_count": count, "confidence": r.confidence, "issue": issue,
            })
    s.close()
    return inconsistent


def deprecate_entry(conn: sqlite3.Connection, entry_id: int, reason: str = "") -> dict:
    s = get_session(conn)
    row = s.get(PlaybookEntry, entry_id)
    if not row:
        s.close()
        return {"error": f"Entry id={entry_id} not found"}
    record_playbook_snapshot(conn, row.name, row.confidence, row.maturity or "nascent",
                             row.evidence or "[]", reason=f"deprecated: {reason}")
    row.confidence = 0.0
    row.maturity = "nascent"
    row.updated_at = func.now()
    s.commit()
    logger.info("Deprecated %s (id=%d): %s", row.name, entry_id, reason)
    s.close()
    return {"name": row.name, "deprecated": True, "reason": reason}


def get_data_stats(conn: sqlite3.Connection) -> dict:
    s = get_session(conn)
    stats = {}
    for model, name, has_processed in [
        (FrameModel, "frames", True), (AudioFrame, "audio_frames", True),
        (OsEvent, "os_events", True), (PipelineLog, "pipeline_logs", False),
    ]:
        total = s.execute(select(func.count()).select_from(model)).scalar()
        if has_processed:
            processed = s.execute(
                select(func.count()).select_from(model).where(model.processed == 1)
            ).scalar()
            stats[name] = {"total": total, "processed": processed, "unprocessed": total - processed}
        else:
            stats[name] = {"total": total}
    s.close()
    return stats


def get_oldest_processed(conn: sqlite3.Connection) -> dict:
    s = get_session(conn)
    result = {}
    for model, name in [(FrameModel, "frames"), (AudioFrame, "audio_frames"), (OsEvent, "os_events")]:
        oldest = s.execute(
            select(func.min(model.created_at)).where(model.processed == 1)
        ).scalar()
        result[name] = oldest
    result["pipeline_logs"] = s.execute(select(func.min(PipelineLog.created_at))).scalar()
    s.close()
    return result


def purge_processed_frames(conn: sqlite3.Connection, older_than_days: int) -> dict:
    s = get_session(conn)
    rows = s.execute(
        select(FrameModel.id, FrameModel.image_path)
        .where(FrameModel.processed == 1,
               FrameModel.created_at < ago(days=older_than_days))
    ).all()
    if not rows:
        s.close()
        return {"deleted": 0, "files_deleted": 0}
    files_deleted = 0
    for r in rows:
        if r[1]:
            try:
                os.remove(r[1])
                files_deleted += 1
            except OSError:
                pass
    ids = [r[0] for r in rows]
    s.execute(delete(FrameModel).where(FrameModel.id.in_(ids)))
    s.commit()
    s.close()
    return {"deleted": len(ids), "files_deleted": files_deleted}


def purge_processed_audio(conn: sqlite3.Connection, older_than_days: int) -> dict:
    s = get_session(conn)
    rows = s.execute(
        select(AudioFrame.id, AudioFrame.chunk_path)
        .where(AudioFrame.processed == 1,
               AudioFrame.created_at < ago(days=older_than_days))
    ).all()
    if not rows:
        s.close()
        return {"deleted": 0, "files_deleted": 0}
    files_deleted = 0
    for r in rows:
        if r[1]:
            try:
                os.remove(r[1])
                files_deleted += 1
            except OSError:
                pass
    ids = [r[0] for r in rows]
    s.execute(delete(AudioFrame).where(AudioFrame.id.in_(ids)))
    s.commit()
    s.close()
    return {"deleted": len(ids), "files_deleted": files_deleted}


def purge_processed_os_events(conn: sqlite3.Connection, older_than_days: int) -> dict:
    s = get_session(conn)
    result = s.execute(
        delete(OsEvent).where(
            OsEvent.processed == 1,
            OsEvent.created_at < ago(days=older_than_days))
    )
    s.commit()
    count = result.rowcount
    s.close()
    return {"deleted": count}


def purge_pipeline_logs(conn: sqlite3.Connection, older_than_days: int) -> dict:
    s = get_session(conn)
    result = s.execute(
        delete(PipelineLog).where(
            PipelineLog.created_at < ago(days=older_than_days))
    )
    s.commit()
    count = result.rowcount
    s.close()
    return {"deleted": count}


# ── Helpers ──


def _ep_dict(e: Episode) -> dict:
    return {
        "id": e.id, "summary": e.summary, "app_names": e.app_names,
        "frame_count": e.frame_count, "started_at": e.started_at,
        "ended_at": e.ended_at, "frame_id_min": e.frame_id_min,
        "frame_id_max": e.frame_id_max, "frame_source": e.frame_source,
        "created_at": e.created_at,
    }


def _pb_dict(p: PlaybookEntry) -> dict:
    return {
        "id": p.id, "name": p.name, "context": p.context,
        "action": p.action, "confidence": p.confidence,
        "maturity": p.maturity, "evidence": p.evidence,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }
