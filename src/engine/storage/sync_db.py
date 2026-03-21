"""Synchronous DB repository using SQLAlchemy ORM.

Used by pipeline/scheduler/tools (sync callers).
"""

import logging

from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from engine.storage.session import ago
from engine.storage.models import (
    Frame, AudioFrame, OsEvent, Episode, PlaybookEntry,
    TokenUsage, State, PipelineLog, Routine,
)

logger = logging.getLogger(__name__)


class SyncDB:
    """Sync repository wrapping a SQLAlchemy Session.

    Accepts a SQLAlchemy Session or falls back to get_session for other inputs.
    """

    def __init__(self, session_or_conn):
        if isinstance(session_or_conn, Session):
            self.session = session_or_conn
            self._owns_session = False
        else:
            # Other DBAPI connections (psycopg, etc.): use get_session
            from engine.storage.session import get_session
            self.session = get_session(session_or_conn)
            self._owns_session = True

    # ── Token usage ──

    def record_usage(
        self, model: str, layer: str,
        input_tokens: int, output_tokens: int, cost_usd: float,
    ):
        self.session.add(TokenUsage(
            model=model, layer=layer,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost_usd,
        ))
        self.session.flush()

    # ── Pipeline logs ──

    def insert_pipeline_log(
        self, stage: str, prompt: str, response: str,
        model: str = "", input_tokens: int = 0,
        output_tokens: int = 0, cost_usd: float = 0.0,
    ):
        self.session.add(PipelineLog(
            stage=stage, prompt=prompt, response=response,
            model=model, input_tokens=input_tokens,
            output_tokens=output_tokens, cost_usd=cost_usd,
        ))
        self.session.flush()

    # ── Episodes ──

    def get_recent_episodes(self, days: int = 1) -> list[dict]:
        stmt = (
            select(Episode)
            .where(Episode.created_at >= ago(days=days))
            .order_by(Episode.created_at)
        )
        rows = self.session.execute(stmt).scalars().all()
        return [self._episode_to_dict(r) for r in rows]

    # ── Playbook entries ──

    def get_all_playbooks(self) -> list[dict]:
        stmt = select(PlaybookEntry).order_by(PlaybookEntry.confidence.desc())
        rows = self.session.execute(stmt).scalars().all()
        return [self._playbook_to_dict(r) for r in rows]

    def upsert_playbook(
        self, name: str, context: str, action: str,
        confidence: float, maturity: str, evidence: str,
    ):
        existing = self.session.execute(
            select(PlaybookEntry).where(PlaybookEntry.name == name)
        ).scalar_one_or_none()
        if existing:
            existing.context = context
            existing.action = action
            existing.confidence = confidence
            existing.maturity = maturity
            existing.evidence = evidence
            existing.updated_at = func.now()
        else:
            self.session.add(PlaybookEntry(
                name=name, context=context, action=action,
                confidence=confidence, maturity=maturity, evidence=evidence,
            ))
        self.session.flush()

    def count_recent_playbooks(self, hours: int = 1) -> int:
        stmt = select(func.count()).select_from(PlaybookEntry).where(
            PlaybookEntry.updated_at >= ago(hours=hours)
        )
        return self.session.execute(stmt).scalar() or 0

    # ── Routines ──

    def get_all_routines(self) -> list[dict]:
        stmt = select(Routine).order_by(Routine.confidence.desc())
        rows = self.session.execute(stmt).scalars().all()
        return [self._routine_to_dict(r) for r in rows]

    def count_recent_routines(self, hours: int = 1) -> int:
        stmt = select(func.count()).select_from(Routine).where(
            Routine.updated_at >= ago(hours=hours)
        )
        return self.session.execute(stmt).scalar() or 0

    # ── Processed marking ──

    def mark_processed(
        self,
        screen_ids: set[int],
        audio_ids: set[int],
        os_event_ids: set[int] | None = None,
    ):
        if screen_ids:
            self.session.execute(
                update(Frame).where(Frame.id.in_(screen_ids)).values(processed=1)
            )
        if audio_ids:
            self.session.execute(
                update(AudioFrame).where(AudioFrame.id.in_(audio_ids)).values(processed=1)
            )
        if os_event_ids:
            self.session.execute(
                update(OsEvent).where(OsEvent.id.in_(os_event_ids)).values(processed=1)
            )
        self.session.commit()

    # ── Budget ──

    def get_daily_spend(self) -> float:
        stmt = select(func.coalesce(func.sum(TokenUsage.cost_usd), 0.0)).where(
            TokenUsage.created_at >= ago(days=1)
        )
        return float(self.session.execute(stmt).scalar())

    def get_budget_cap(self, default: float) -> float:
        row = self.session.execute(
            select(State.value).where(State.key == "daily_cost_cap_usd")
        ).scalar_one_or_none()
        return float(row) if row else default

    # ── Helpers ──

    @staticmethod
    def _episode_to_dict(e: Episode) -> dict:
        return {
            "id": e.id, "summary": e.summary, "app_names": e.app_names,
            "frame_count": e.frame_count, "started_at": e.started_at,
            "ended_at": e.ended_at, "frame_id_min": e.frame_id_min,
            "frame_id_max": e.frame_id_max, "frame_source": e.frame_source,
            "created_at": e.created_at,
        }

    @staticmethod
    def _playbook_to_dict(p: PlaybookEntry) -> dict:
        return {
            "id": p.id, "name": p.name, "context": p.context,
            "action": p.action, "confidence": p.confidence,
            "maturity": p.maturity, "evidence": p.evidence,
            "created_at": p.created_at, "updated_at": p.updated_at,
        }

    @staticmethod
    def _routine_to_dict(r: Routine) -> dict:
        return {
            "id": r.id, "name": r.name, "trigger": r.trigger,
            "goal": r.goal, "steps": r.steps, "uses": r.uses,
            "confidence": r.confidence, "maturity": r.maturity,
            "created_at": r.created_at, "updated_at": r.updated_at,
        }
