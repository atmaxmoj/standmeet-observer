"""Pipeline data access — decay, budget. Uses SQLAlchemy ORM."""

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from engine.storage.session import ago
from engine.storage.models import PlaybookEntry, Routine, TokenUsage, State


def get_all_playbooks_for_decay(session: Session) -> list[dict]:
    rows = session.execute(select(PlaybookEntry)).scalars().all()
    result = [
        {"id": r.id, "name": r.name, "confidence": r.confidence, "last_evidence_at": r.last_evidence_at}
        for r in rows
    ]
    return result


def update_confidence(session: Session, entry_id: int, confidence: float):
    entry = session.get(PlaybookEntry, entry_id)
    if entry:
        entry.confidence = confidence
        session.commit()


def get_all_routines_for_decay(session: Session) -> list[dict]:
    rows = session.execute(select(Routine)).scalars().all()
    return [
        {"id": r.id, "name": r.name, "confidence": r.confidence, "updated_at": r.updated_at}
        for r in rows
    ]


def update_routine_confidence(session: Session, routine_id: int, confidence: float):
    routine = session.get(Routine, routine_id)
    if routine:
        routine.confidence = confidence
        session.commit()


def get_daily_spend(session: Session) -> float:
    cutoff = ago(days=1)
    result = session.execute(
        select(func.coalesce(func.sum(TokenUsage.cost_usd), 0.0))
        .where(TokenUsage.created_at >= cutoff)
    ).scalar()
    return float(result)


def get_budget_cap(session: Session, default: float) -> float:
    row = session.execute(
        select(State.value).where(State.key == "daily_cost_cap_usd")
    ).scalar_one_or_none()
    return float(row) if row else default
