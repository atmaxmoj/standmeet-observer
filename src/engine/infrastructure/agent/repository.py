"""Agents data access — episode search, playbook/routine CRUD, audit, dedup, trend.

All queries that agent tools need, centralized here. Uses SQLAlchemy ORM.
"""

import json
import logging
import os

from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session

from engine.infrastructure.persistence.session import ago
from engine.infrastructure.persistence.models import (
    Frame as FrameModel, AudioFrame, OsEvent, Episode,
    PlaybookEntry, PlaybookHistory, Routine, PipelineLog,
)

logger = logging.getLogger(__name__)


# ── Episode queries ──


def search_episodes(session: Session, query: str, limit: int = 10) -> list[dict]:
    words = query.strip().split()
    stmt = select(Episode.id, Episode.summary, Episode.app_names, Episode.started_at, Episode.ended_at)
    if len(words) > 1:
        for w in words:
            stmt = stmt.where(Episode.summary.contains(w))
    else:
        stmt = stmt.where(Episode.summary.contains(query))
    rows = session.execute(stmt.order_by(Episode.id.desc()).limit(limit)).all()
    return [{"id": r[0], "summary": r[1], "app_names": r[2], "started_at": r[3], "ended_at": r[4]} for r in rows]


def get_recent_episodes(session: Session, hours: int = 24) -> list[dict]:
    rows = session.execute(
        select(Episode.id, Episode.summary, Episode.app_names, Episode.started_at, Episode.ended_at)
        .where(Episode.created_at >= ago(hours=hours))
        .order_by(Episode.created_at.desc())
    ).all()
    return [{"id": r[0], "summary": r[1], "app_names": r[2], "started_at": r[3], "ended_at": r[4]} for r in rows]



def get_episode_detail(session: Session, episode_id: int) -> dict | None:
    row = session.execute(select(Episode).where(Episode.id == episode_id)).scalar_one_or_none()
    if not row:
        return None
    result = _ep_dict(row)
    return result


def get_episode_frames(session: Session, episode_id: int, limit: int = 10) -> list[dict]:
    ep = session.execute(
        select(Episode.frame_id_min, Episode.frame_id_max).where(Episode.id == episode_id)
    ).one_or_none()
    if not ep:
        return []
    rows = session.execute(
        select(FrameModel.id, FrameModel.timestamp, FrameModel.app_name,
               FrameModel.window_name, func.substr(FrameModel.text, 1, 200).label("text"))
        .where(FrameModel.id.between(ep[0], ep[1]))
        .order_by(FrameModel.id).limit(limit)
    ).all()
    return [{"id": r[0], "timestamp": r[1], "app_name": r[2], "window_name": r[3], "text": r[4]} for r in rows]


# ── Raw capture queries ──


def get_recent_frames(session: Session, hours: int = 24, limit: int = 50) -> list[dict]:
    rows = session.execute(
        select(FrameModel.id, FrameModel.timestamp, FrameModel.app_name,
               FrameModel.window_name, func.substr(FrameModel.text, 1, 300).label("text"),
               FrameModel.display_id)
        .where(FrameModel.created_at >= ago(hours=hours))
        .order_by(FrameModel.id.desc()).limit(limit)
    ).all()
    return [{"id": r[0], "timestamp": r[1], "app_name": r[2], "window_name": r[3],
             "text": r[4], "display_id": r[5]} for r in rows]


def get_recent_os_events(session: Session, hours: int = 24, limit: int = 50) -> list[dict]:
    rows = session.execute(
        select(OsEvent.id, OsEvent.timestamp, OsEvent.event_type, OsEvent.source, OsEvent.data)
        .where(OsEvent.created_at >= ago(hours=hours))
        .order_by(OsEvent.id.desc()).limit(limit)
    ).all()
    return [{"id": r[0], "timestamp": r[1], "event_type": r[2], "source": r[3], "data": r[4]} for r in rows]


def get_os_events_by_type(session: Session, event_type: str, limit: int = 30) -> list[dict]:
    rows = session.execute(
        select(OsEvent.id, OsEvent.timestamp, OsEvent.event_type, OsEvent.source, OsEvent.data)
        .where(OsEvent.event_type == event_type)
        .order_by(OsEvent.id.desc()).limit(limit)
    ).all()
    return [{"id": r[0], "timestamp": r[1], "event_type": r[2], "source": r[3], "data": r[4]} for r in rows]


# ── Playbook CRUD ──


def get_all_playbook_entries(session: Session) -> list[dict]:
    rows = session.execute(
        select(PlaybookEntry.name, PlaybookEntry.context, PlaybookEntry.action,
               PlaybookEntry.confidence, PlaybookEntry.maturity, PlaybookEntry.evidence)
        .order_by(PlaybookEntry.confidence.desc())
    ).all()
    return [{"name": r[0], "context": r[1], "action": r[2], "confidence": r[3],
             "maturity": r[4], "evidence": r[5]} for r in rows]


def get_playbook_by_name(session: Session, name: str) -> dict | None:
    row = session.execute(select(PlaybookEntry).where(PlaybookEntry.name == name)).scalar_one_or_none()
    result = _pb_dict(row) if row else None
    return result


def write_playbook_entry(
    session: Session,
    name: str, context: str, action: str,
    confidence: float, maturity: str, evidence: str,
):
    existing = session.execute(select(PlaybookEntry).where(PlaybookEntry.name == name)).scalar_one_or_none()
    if existing:
        existing.context = context
        existing.action = action
        existing.confidence = confidence
        existing.base_confidence = confidence
        existing.maturity = maturity
        existing.evidence = evidence
        existing.updated_at = func.now()
    else:
        session.add(PlaybookEntry(
            name=name, context=context, action=action,
            confidence=confidence, base_confidence=confidence,
            maturity=maturity, evidence=evidence,
        ))
    session.flush()


# ── Playbook history ──


def get_playbook_history(session: Session, name: str) -> list[dict]:
    rows = session.execute(
        select(PlaybookHistory).where(PlaybookHistory.playbook_name == name)
        .order_by(PlaybookHistory.created_at)
    ).scalars().all()
    result = [
        {"id": r.id, "playbook_name": r.playbook_name, "confidence": r.confidence,
         "maturity": r.maturity, "evidence": r.evidence,
         "change_reason": r.change_reason, "created_at": r.created_at}
        for r in rows
    ]
    return result


def record_snapshot(session: Session, name: str, reason: str = "") -> dict:
    """Record snapshot of a playbook entry (convenience wrapper)."""
    entry = get_playbook_by_name(session, name)
    if not entry:
        return {"error": f"Entry '{name}' not found"}
    record_playbook_snapshot(
        session, name, entry["confidence"], entry.get("maturity") or "nascent",
        entry.get("evidence") or "[]", reason,
    )
    return {"name": name, "snapshot_confidence": entry["confidence"],
            "snapshot_maturity": entry.get("maturity"), "reason": reason}


def record_playbook_snapshot(
    session: Session, name: str,
    confidence: float, maturity: str, evidence: str, reason: str = "",
):
    session.add(PlaybookHistory(
        playbook_name=name, confidence=confidence,
        maturity=maturity, evidence=evidence, change_reason=reason,
    ))
    session.commit()


# ── Routines ──


def get_all_routines(session: Session) -> list[dict]:
    rows = session.execute(
        select(Routine.name, Routine.trigger, Routine.goal, Routine.steps,
               Routine.uses, Routine.confidence, Routine.maturity)
        .order_by(Routine.confidence.desc())
    ).all()
    return [{"name": r[0], "trigger": r[1], "goal": r[2], "steps": r[3],
             "uses": r[4], "confidence": r[5], "maturity": r[6]} for r in rows]


def write_routine(
    session: Session,
    name: str, trigger: str, goal: str,
    steps: str, uses: str, confidence: float, maturity: str,
):
    existing = session.execute(select(Routine).where(Routine.name == name)).scalar_one_or_none()
    if existing:
        existing.trigger = trigger
        existing.goal = goal
        existing.steps = steps
        existing.uses = uses
        existing.confidence = confidence
        existing.base_confidence = confidence
        existing.maturity = maturity
        existing.updated_at = func.now()
    else:
        session.add(Routine(
            name=name, trigger=trigger, goal=goal,
            steps=steps, uses=uses, confidence=confidence,
            base_confidence=confidence, maturity=maturity,
        ))
    session.flush()


# ── Dedup ──


def find_similar_pairs(session: Session, threshold: float = 0.8) -> list[dict]:
    rows = session.execute(
        select(PlaybookEntry.id, PlaybookEntry.name, PlaybookEntry.confidence,
               PlaybookEntry.maturity, PlaybookEntry.context)
        .order_by(PlaybookEntry.confidence.desc())
    ).all()
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


def merge_entries(session: Session, keep_id: int, remove_id: int) -> dict:
    keep = session.get(PlaybookEntry, keep_id)
    remove = session.get(PlaybookEntry, remove_id)
    if not keep or not remove:
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
    new_conf = max(keep.base_confidence, remove.base_confidence)
    keep.confidence = new_conf
    keep.base_confidence = new_conf
    keep.evidence = json.dumps(merged)
    keep.updated_at = func.now()
    session.delete(remove)
    session.commit()
    logger.info("Merged: kept %s (id=%d), removed %s (id=%d)", keep.name, keep_id, remove.name, remove_id)
    result = {"kept": keep.name, "removed": remove.name, "new_confidence": new_conf, "merged_evidence": merged}
    return result


# ── Audit / GC ──


def check_evidence_exists(session: Session, entry_name: str) -> dict:
    row = session.execute(select(PlaybookEntry).where(PlaybookEntry.name == entry_name)).scalar_one_or_none()
    if not row:
        return {"error": f"Entry '{entry_name}' not found"}
    try:
        ids = json.loads(row.evidence) if row.evidence else []
    except (json.JSONDecodeError, TypeError):
        ids = []
    if not ids:
        return {"name": entry_name, "evidence_ids": [], "missing": [], "all_exist": True}
    existing = session.execute(select(Episode.id).where(Episode.id.in_(ids))).scalars().all()
    existing_set = set(existing)
    missing = [eid for eid in ids if eid not in existing_set]
    return {"name": entry_name, "evidence_ids": ids, "missing": missing, "all_exist": len(missing) == 0}


def check_maturity_consistency(session: Session) -> list[dict]:
    rows = session.execute(select(PlaybookEntry)).scalars().all()
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
    return inconsistent


def deprecate_entry(session: Session, entry_id: int, reason: str = "") -> dict:
    row = session.get(PlaybookEntry, entry_id)
    if not row:
        return {"error": f"Entry id={entry_id} not found"}
    record_playbook_snapshot(session, row.name, row.confidence, row.maturity or "nascent",
                             row.evidence or "[]", reason=f"deprecated: {reason}")
    row.confidence = 0.0
    row.base_confidence = 0.0
    row.maturity = "nascent"
    row.updated_at = func.now()
    session.commit()
    logger.info("Deprecated %s (id=%d): %s", row.name, entry_id, reason)
    return {"name": row.name, "deprecated": True, "reason": reason}


def get_data_stats(session: Session) -> dict:
    stats = {}
    for model, name, has_processed in [
        (FrameModel, "frames", True), (AudioFrame, "audio_frames", True),
        (OsEvent, "os_events", True), (PipelineLog, "pipeline_logs", False),
    ]:
        total = session.execute(select(func.count()).select_from(model)).scalar()
        if has_processed:
            processed = session.execute(
                select(func.count()).select_from(model).where(model.processed == 1)
            ).scalar()
            stats[name] = {"total": total, "processed": processed, "unprocessed": total - processed}
        else:
            stats[name] = {"total": total}

    # Add manifest source stats
    from engine.infrastructure.etl.sources.manifest_registry import get_global_registry
    from sqlalchemy import text as sa_text
    registry = get_global_registry()
    if registry:
        for manifest in registry.all_manifests():
            if not manifest.db_table:
                continue
            try:
                total = session.execute(sa_text(f"SELECT COUNT(*) FROM {manifest.db_table}")).scalar()
                processed = session.execute(sa_text(f"SELECT COUNT(*) FROM {manifest.db_table} WHERE processed = 1")).scalar()
                stats[manifest.db_table] = {"total": total, "processed": processed, "unprocessed": total - processed}
            except Exception:
                pass  # Table may not exist yet

    return stats


def get_oldest_processed(session: Session) -> dict:
    result = {}
    for model, name in [(FrameModel, "frames"), (AudioFrame, "audio_frames"), (OsEvent, "os_events")]:
        oldest = session.execute(
            select(func.min(model.created_at)).where(model.processed == 1)
        ).scalar()
        result[name] = oldest
    result["pipeline_logs"] = session.execute(select(func.min(PipelineLog.created_at))).scalar()

    # Add manifest source oldest processed
    from engine.infrastructure.etl.sources.manifest_registry import get_global_registry
    from sqlalchemy import text as sa_text
    registry = get_global_registry()
    if registry:
        for manifest in registry.all_manifests():
            if not manifest.db_table:
                continue
            try:
                oldest = session.execute(sa_text(
                    f"SELECT MIN(created_at) FROM {manifest.db_table} WHERE processed = 1"
                )).scalar()
                result[manifest.db_table] = oldest
            except Exception:
                pass

    return result


def purge_processed_frames(session: Session, older_than_days: int) -> dict:
    rows = session.execute(
        select(FrameModel.id, FrameModel.image_path)
        .where(FrameModel.processed == 1,
               FrameModel.created_at < ago(days=older_than_days))
    ).all()
    if not rows:
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
    session.execute(delete(FrameModel).where(FrameModel.id.in_(ids)))
    session.commit()
    return {"deleted": len(ids), "files_deleted": files_deleted}


def purge_processed_audio(session: Session, older_than_days: int) -> dict:
    rows = session.execute(
        select(AudioFrame.id, AudioFrame.chunk_path)
        .where(AudioFrame.processed == 1,
               AudioFrame.created_at < ago(days=older_than_days))
    ).all()
    if not rows:
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
    session.execute(delete(AudioFrame).where(AudioFrame.id.in_(ids)))
    session.commit()
    return {"deleted": len(ids), "files_deleted": files_deleted}


def purge_processed_os_events(session: Session, older_than_days: int) -> dict:
    result = session.execute(
        delete(OsEvent).where(
            OsEvent.processed == 1,
            OsEvent.created_at < ago(days=older_than_days))
    )
    session.commit()
    count = result.rowcount
    return {"deleted": count}


def purge_pipeline_logs(session: Session, older_than_days: int) -> dict:
    result = session.execute(
        delete(PipelineLog).where(
            PipelineLog.created_at < ago(days=older_than_days))
    )
    session.commit()
    count = result.rowcount
    return {"deleted": count}


# ── Sensitive data detection ──

SENSITIVE_PATTERNS = [
    "sk-ant-", "sk-", "ghp_", "gho_", "github_pat_",
    "AKIA", "aws_secret", "Bearer ", "token=",
    "password=", "passwd=", "secret=",
    "-----BEGIN", "-----END",
    "api_key=", "apikey=", "api-key:",
]


def search_frames_for_sensitive(session: Session, limit: int = 100) -> list[dict]:
    """Scan frame text for common secret/key patterns. Returns matching frames."""
    results = []
    for pattern in SENSITIVE_PATTERNS:
        rows = session.execute(
            select(FrameModel.id, FrameModel.timestamp, FrameModel.app_name,
                   func.substr(FrameModel.text, 1, 200).label("text"))
            .where(FrameModel.text.contains(pattern))
            .limit(limit)
        ).all()
        for r in rows:
            results.append({
                "id": r[0], "timestamp": r[1], "app_name": r[2],
                "preview": r[3][:100] if r[3] else "", "matched_pattern": pattern,
            })
    # Also check episodes and pipeline_logs
    for pattern in SENSITIVE_PATTERNS:
        ep_rows = session.execute(
            select(Episode.id, Episode.summary)
            .where(Episode.summary.contains(pattern))
            .limit(20)
        ).all()
        for r in ep_rows:
            results.append({
                "id": r[0], "table": "episodes", "matched_pattern": pattern,
                "preview": r[1][:100] if r[1] else "",
            })
    # Deduplicate by id
    seen = set()
    unique = []
    for r in results:
        key = (r.get("table", "frames"), r["id"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def purge_sensitive_frames(session: Session, frame_ids: list[int]) -> dict:
    """Delete frames containing sensitive data by ID."""
    if not frame_ids:
        return {"deleted": 0}
    session.execute(delete(FrameModel).where(FrameModel.id.in_(frame_ids)))
    session.commit()
    logger.info("Purged %d sensitive frames", len(frame_ids))
    return {"deleted": len(frame_ids)}


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
