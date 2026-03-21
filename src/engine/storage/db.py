"""Async DB repository using SQLAlchemy ORM.

Used by FastAPI endpoints (async callers).
"""

import logging

from sqlalchemy import select, func, delete, update, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from engine.storage.session import ago
from engine.storage.models import (
    Base, Frame, AudioFrame, OsEvent, Episode, PlaybookEntry,
    TokenUsage, State, PipelineLog, PlaybookHistory, Routine, ChatMessage,
)

logger = logging.getLogger(__name__)

CHAT_WINDOW_SIZE = 20


class DB:
    def __init__(self, url: str):
        self.url = url
        self._engine = None
        self._session_factory = None

    async def connect(self):
        logger.debug("connecting to database at %s", self.url)
        self._engine = create_async_engine(self.url, echo=False)
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._session_factory = async_sessionmaker(
            bind=self._engine, expire_on_commit=False,
        )
        logger.info("database connected and schema initialized at %s", self.url)

    async def close(self):
        if self._engine:
            logger.debug("closing database connection")
            await self._engine.dispose()

    def _session(self) -> AsyncSession:
        return self._session_factory()

    # -- ingest --

    async def insert_frame(
        self, timestamp: str, app_name: str, window_name: str,
        text: str, display_id: int, image_hash: str, image_path: str = "",
    ) -> int:
        async with self._session() as s:
            frame = Frame(
                timestamp=timestamp, app_name=app_name, window_name=window_name,
                text=text, display_id=display_id, image_hash=image_hash, image_path=image_path,
            )
            s.add(frame)
            await s.commit()
            await s.refresh(frame)
            logger.debug("inserted frame id=%d display=%d app=%s", frame.id, display_id, app_name)
            return frame.id

    async def insert_audio_frame(
        self, timestamp: str, duration_seconds: float, text: str,
        language: str, source: str = "mic", chunk_path: str = "",
    ) -> int:
        async with self._session() as s:
            af = AudioFrame(
                timestamp=timestamp, duration_seconds=duration_seconds, text=text,
                language=language, source=source, chunk_path=chunk_path,
            )
            s.add(af)
            await s.commit()
            await s.refresh(af)
            logger.debug("inserted audio_frame id=%d duration=%.1fs lang=%s", af.id, duration_seconds, language)
            return af.id

    async def insert_os_event(
        self, timestamp: str, event_type: str, source: str, data: str,
    ) -> int:
        async with self._session() as s:
            ev = OsEvent(timestamp=timestamp, event_type=event_type, source=source, data=data)
            s.add(ev)
            await s.commit()
            await s.refresh(ev)
            logger.debug("inserted os_event id=%d type=%s source=%s", ev.id, event_type, source)
            return ev.id

    # -- query --

    async def get_frames(self, limit: int = 50, offset: int = 0, search: str = "") -> tuple[list[dict], int]:
        async with self._session() as s:
            q = select(Frame)
            cq = select(func.count()).select_from(Frame)
            if search:
                filt = Frame.app_name.contains(search) | Frame.window_name.contains(search) | Frame.text.contains(search)
                q = q.where(filt)
                cq = cq.where(filt)
            total = (await s.execute(cq)).scalar()
            rows = (await s.execute(
                q.order_by(Frame.id.desc()).limit(limit).offset(offset)
            )).scalars().all()
            return [
                {"id": r.id, "timestamp": r.timestamp, "app_name": r.app_name,
                 "window_name": r.window_name, "text": r.text[:500],
                 "display_id": r.display_id, "image_hash": r.image_hash, "image_path": r.image_path}
                for r in rows
            ], total

    async def get_audio_frames(self, limit: int = 50, offset: int = 0, search: str = "") -> tuple[list[dict], int]:
        async with self._session() as s:
            q = select(AudioFrame)
            cq = select(func.count()).select_from(AudioFrame)
            if search:
                filt = AudioFrame.text.contains(search)
                q = q.where(filt)
                cq = cq.where(filt)
            total = (await s.execute(cq)).scalar()
            rows = (await s.execute(
                q.order_by(AudioFrame.id.desc()).limit(limit).offset(offset)
            )).scalars().all()
            return [
                {"id": r.id, "timestamp": r.timestamp, "duration_seconds": r.duration_seconds,
                 "text": r.text, "language": r.language, "source": r.source}
                for r in rows
            ], total

    async def get_os_events(
        self, limit: int = 50, offset: int = 0, event_type: str = "", search: str = "",
    ) -> tuple[list[dict], int]:
        async with self._session() as s:
            q = select(OsEvent)
            cq = select(func.count()).select_from(OsEvent)
            if event_type:
                q = q.where(OsEvent.event_type == event_type)
                cq = cq.where(OsEvent.event_type == event_type)
            if search:
                filt = OsEvent.data.contains(search) | OsEvent.source.contains(search)
                q = q.where(filt)
                cq = cq.where(filt)
            total = (await s.execute(cq)).scalar()
            rows = (await s.execute(
                q.order_by(OsEvent.id.desc()).limit(limit).offset(offset)
            )).scalars().all()
            return [
                {"id": r.id, "timestamp": r.timestamp, "event_type": r.event_type,
                 "source": r.source, "data": r.data}
                for r in rows
            ], total

    async def get_last_os_event_data(self, event_type: str, source: str) -> str | None:
        async with self._session() as s:
            row = (await s.execute(
                select(OsEvent.data)
                .where(OsEvent.event_type == event_type, OsEvent.source == source)
                .order_by(OsEvent.id.desc()).limit(1)
            )).scalar_one_or_none()
            return row

    async def get_last_frame_hash(self, display_id: int) -> str | None:
        async with self._session() as s:
            return (await s.execute(
                select(Frame.image_hash)
                .where(Frame.display_id == display_id)
                .order_by(Frame.id.desc()).limit(1)
            )).scalar_one_or_none()

    async def row_exists(self, table: str, row_id: int) -> bool:
        """Check if a row exists in an allowed table."""
        allowed = {
            "frames": Frame, "audio_frames": AudioFrame, "os_events": OsEvent,
            "episodes": Episode, "playbook_entries": PlaybookEntry,
        }
        model = allowed.get(table)
        if not model:
            return False
        async with self._session() as s:
            return (await s.execute(
                select(model.id).where(model.id == row_id)
            )).scalar_one_or_none() is not None

    async def get_frame_image_path(self, frame_id: int) -> str | None:
        async with self._session() as s:
            return (await s.execute(
                select(Frame.image_path).where(Frame.id == frame_id)
            )).scalar_one_or_none()

    # -- state --

    async def get_state(self, key: str, default: int = 0) -> int:
        async with self._session() as s:
            row = (await s.execute(
                select(State.value).where(State.key == key)
            )).scalar_one_or_none()
            val = int(row) if row else default
            logger.debug("get_state(%s) = %d", key, val)
            return val

    async def set_state(self, key: str, value: int):
        async with self._session() as s:
            existing = (await s.execute(
                select(State).where(State.key == key)
            )).scalar_one_or_none()
            if existing:
                existing.value = str(value)
            else:
                s.add(State(key=key, value=str(value)))
            await s.commit()
            logger.debug("set_state(%s) = %d", key, value)

    async def get_state_float(self, key: str, default: float = 0.0) -> float:
        async with self._session() as s:
            row = (await s.execute(
                select(State.value).where(State.key == key)
            )).scalar_one_or_none()
            return float(row) if row else default

    async def set_state_float(self, key: str, value: float):
        async with self._session() as s:
            existing = (await s.execute(
                select(State).where(State.key == key)
            )).scalar_one_or_none()
            if existing:
                existing.value = str(value)
            else:
                s.add(State(key=key, value=str(value)))
            await s.commit()

    # -- episodes --

    async def insert_episode(
        self, summary: str, app_names: str, frame_count: int,
        started_at: str, ended_at: str,
        frame_id_min: int = 0, frame_id_max: int = 0, frame_source: str = "",
    ) -> int:
        async with self._session() as s:
            ep = Episode(
                summary=summary, app_names=app_names, frame_count=frame_count,
                started_at=started_at, ended_at=ended_at,
                frame_id_min=frame_id_min, frame_id_max=frame_id_max, frame_source=frame_source,
            )
            s.add(ep)
            await s.commit()
            await s.refresh(ep)
            logger.debug("inserted episode id=%d frame_count=%d", ep.id, frame_count)
            return ep.id

    async def get_recent_episodes(self, days: int = 7) -> list[dict]:
        async with self._session() as s:
            rows = (await s.execute(
                select(Episode)
                .where(Episode.created_at >= ago(days=days))
                .order_by(Episode.created_at)
            )).scalars().all()
            return [self._ep_dict(r) for r in rows]

    async def get_all_episodes(self, limit: int = 100, offset: int = 0, search: str = "") -> list[dict]:
        async with self._session() as s:
            q = select(Episode)
            if search:
                q = q.where(Episode.summary.contains(search) | Episode.app_names.contains(search))
            rows = (await s.execute(
                q.order_by(Episode.created_at.desc()).limit(limit).offset(offset)
            )).scalars().all()
            return [self._ep_dict(r) for r in rows]

    async def count_episodes(self, search: str = "") -> int:
        async with self._session() as s:
            q = select(func.count()).select_from(Episode)
            if search:
                q = q.where(Episode.summary.contains(search) | Episode.app_names.contains(search))
            return (await s.execute(q)).scalar()

    # -- playbook entries --

    async def upsert_playbook(
        self, name: str, context: str, action: str,
        confidence: float, evidence: str, maturity: str = "nascent",
    ):
        async with self._session() as s:
            existing = (await s.execute(
                select(PlaybookEntry).where(PlaybookEntry.name == name)
            )).scalar_one_or_none()
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
            await s.commit()
            logger.debug("upserted playbook name=%s confidence=%.2f maturity=%s", name, confidence, maturity)

    async def get_all_playbooks(self, search: str = "") -> list[dict]:
        async with self._session() as s:
            q = select(PlaybookEntry)
            if search:
                q = q.where(
                    PlaybookEntry.name.contains(search)
                    | PlaybookEntry.context.contains(search)
                    | PlaybookEntry.action.contains(search)
                )
            rows = (await s.execute(q.order_by(PlaybookEntry.confidence.desc()))).scalars().all()
            return [self._pb_dict(r) for r in rows]

    # -- playbook history --

    async def record_playbook_snapshot(
        self, playbook_name: str, confidence: float,
        maturity: str, evidence: str, change_reason: str = "",
    ):
        async with self._session() as s:
            s.add(PlaybookHistory(
                playbook_name=playbook_name, confidence=confidence,
                maturity=maturity, evidence=evidence, change_reason=change_reason,
            ))
            await s.commit()

    async def get_playbook_history(self, name: str) -> list[dict]:
        async with self._session() as s:
            rows = (await s.execute(
                select(PlaybookHistory)
                .where(PlaybookHistory.playbook_name == name)
                .order_by(PlaybookHistory.created_at)
            )).scalars().all()
            return [
                {"id": r.id, "playbook_name": r.playbook_name, "confidence": r.confidence,
                 "maturity": r.maturity, "evidence": r.evidence,
                 "change_reason": r.change_reason, "created_at": r.created_at}
                for r in rows
            ]

    # -- episode search --

    async def search_episodes_by_keyword(self, query: str, limit: int = 10) -> list[dict]:
        async with self._session() as s:
            rows = (await s.execute(
                select(Episode.id, Episode.summary, Episode.app_names, Episode.started_at, Episode.ended_at)
                .where(Episode.summary.contains(query))
                .order_by(Episode.id.desc()).limit(limit)
            )).all()
            return [{"id": r[0], "summary": r[1], "app_names": r[2], "started_at": r[3], "ended_at": r[4]} for r in rows]

    async def get_episodes_by_timerange(self, hours: int = 24) -> list[dict]:
        async with self._session() as s:
            rows = (await s.execute(
                select(Episode.id, Episode.summary, Episode.app_names, Episode.started_at, Episode.ended_at)
                .where(Episode.created_at >= ago(hours=hours))
                .order_by(Episode.created_at.desc())
            )).all()
            return [{"id": r[0], "summary": r[1], "app_names": r[2], "started_at": r[3], "ended_at": r[4]} for r in rows]

    # -- token usage --

    async def record_usage(
        self, model: str, layer: str,
        input_tokens: int, output_tokens: int, cost_usd: float,
    ):
        async with self._session() as s:
            s.add(TokenUsage(
                model=model, layer=layer,
                input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
            ))
            await s.commit()
            logger.debug("recorded usage: model=%s layer=%s cost=$%.4f", model, layer, cost_usd)

    async def get_daily_spend(self) -> float:
        async with self._session() as s:
            result = (await s.execute(
                select(func.coalesce(func.sum(TokenUsage.cost_usd), 0.0))
                .where(TokenUsage.created_at >= ago(days=1))
            )).scalar()
            return float(result)

    async def get_usage_summary(self, days: int = 7) -> dict:
        async with self._session() as s:
            cutoff = ago(days=days)
            by_layer = (await s.execute(text(
                "SELECT layer, model, "
                "SUM(input_tokens) as total_input, SUM(output_tokens) as total_output, "
                "SUM(cost_usd) as total_cost, COUNT(*) as call_count "
                "FROM token_usage WHERE created_at >= :cutoff "
                "GROUP BY layer, model ORDER BY total_cost DESC"
            ).bindparams(cutoff=cutoff))).mappings().all()

            by_day = (await s.execute(text(
                "SELECT date(created_at) as day, "
                "SUM(input_tokens) as total_input, SUM(output_tokens) as total_output, "
                "SUM(cost_usd) as total_cost, COUNT(*) as call_count "
                "FROM token_usage WHERE created_at >= :cutoff "
                "GROUP BY date(created_at) ORDER BY day"
            ).bindparams(cutoff=cutoff))).mappings().all()

            rows_layer = [dict(r) for r in by_layer]
            rows_day = [dict(r) for r in by_day]
            total_cost = sum(r["total_cost"] for r in rows_layer)
            total_input = sum(r["total_input"] for r in rows_layer)
            total_output = sum(r["total_output"] for r in rows_layer)
            total_calls = sum(r["call_count"] for r in rows_layer)

            return {
                "days": days,
                "total_cost_usd": round(total_cost, 4),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_calls": total_calls,
                "by_layer": rows_layer,
                "by_day": rows_day,
            }

    # -- pipeline logs --

    async def insert_pipeline_log(
        self, stage: str, prompt: str, response: str,
        model: str = "", input_tokens: int = 0,
        output_tokens: int = 0, cost_usd: float = 0.0,
    ) -> int:
        async with self._session() as s:
            log = PipelineLog(
                stage=stage, prompt=prompt, response=response,
                model=model, input_tokens=input_tokens,
                output_tokens=output_tokens, cost_usd=cost_usd,
            )
            s.add(log)
            await s.commit()
            await s.refresh(log)
            return log.id

    async def get_pipeline_logs(self, limit: int = 50, offset: int = 0, search: str = "") -> tuple[list[dict], int]:
        async with self._session() as s:
            q = select(PipelineLog)
            cq = select(func.count()).select_from(PipelineLog)
            if search:
                filt = (
                    PipelineLog.stage.contains(search) | PipelineLog.model.contains(search)
                    | PipelineLog.prompt.contains(search) | PipelineLog.response.contains(search)
                )
                q = q.where(filt)
                cq = cq.where(filt)
            total = (await s.execute(cq)).scalar()
            rows = (await s.execute(
                q.order_by(PipelineLog.id.desc()).limit(limit).offset(offset)
            )).scalars().all()
            return [
                {"id": r.id, "stage": r.stage, "prompt": r.prompt, "response": r.response,
                 "model": r.model, "input_tokens": r.input_tokens,
                 "output_tokens": r.output_tokens, "cost_usd": r.cost_usd, "created_at": r.created_at}
                for r in rows
            ], total

    # -- batch delete --

    async def delete_rows(self, table: str, ids: list[int]) -> int:
        allowed = {
            "frames": Frame, "audio_frames": AudioFrame, "os_events": OsEvent,
            "episodes": Episode, "playbook_entries": PlaybookEntry,
        }
        model = allowed.get(table)
        if not model:
            raise ValueError(f"delete not allowed on table: {table}")
        if not ids:
            return 0
        async with self._session() as s:
            result = await s.execute(delete(model).where(model.id.in_(ids)))
            await s.commit()
            return result.rowcount

    # -- stats --

    async def get_status(self) -> dict:
        async with self._session() as s:
            episode_count = (await s.execute(select(func.count()).select_from(Episode))).scalar()
            playbook_count = (await s.execute(select(func.count()).select_from(PlaybookEntry))).scalar()
            routine_count = (await s.execute(select(func.count()).select_from(Routine))).scalar()
            # Check both legacy frames table and new screen_data manifest table
            last_frame = (await s.execute(
                select(Frame.timestamp).order_by(Frame.id.desc()).limit(1)
            )).scalar_one_or_none()

            # Also check manifest screen_data table
            try:
                from sqlalchemy import text as sa_text
                screen_ts = (await s.execute(
                    sa_text("SELECT timestamp FROM screen_data ORDER BY id DESC LIMIT 1")
                )).scalar_one_or_none()
                if screen_ts and (not last_frame or str(screen_ts) > str(last_frame)):
                    last_frame = str(screen_ts)
            except Exception:
                pass

            capture_alive = False
            if last_frame:
                from datetime import datetime, timezone, timedelta
                try:
                    ts = datetime.fromisoformat(str(last_frame).replace(" ", "T"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    capture_alive = (datetime.now(timezone.utc) - ts) < timedelta(minutes=2)
                except Exception:
                    pass

            return {
                "episode_count": episode_count,
                "playbook_count": playbook_count,
                "routine_count": routine_count,
                "capture_alive": capture_alive,
                "last_frame_at": last_frame,
            }

    # -- routines --

    async def get_all_routines(self, search: str = "") -> list[dict]:
        async with self._session() as s:
            q = select(Routine)
            if search:
                q = q.where(
                    Routine.name.contains(search) | Routine.trigger.contains(search)
                    | Routine.goal.contains(search)
                )
            rows = (await s.execute(q.order_by(Routine.confidence.desc()))).scalars().all()
            return [
                {"id": r.id, "name": r.name, "trigger": r.trigger, "goal": r.goal,
                 "steps": r.steps, "uses": r.uses, "confidence": r.confidence,
                 "maturity": r.maturity, "created_at": r.created_at, "updated_at": r.updated_at}
                for r in rows
            ]

    # -- chat messages --

    async def append_chat_message(self, role: str, content: str, proposals: str = "[]"):
        async with self._session() as s:
            s.add(ChatMessage(role=role, content=content, proposals=proposals))
            # Trim to window size
            subq = select(ChatMessage.id).order_by(ChatMessage.id.desc()).limit(CHAT_WINDOW_SIZE)
            await s.execute(delete(ChatMessage).where(ChatMessage.id.not_in(subq)))
            await s.commit()

    async def get_chat_messages(self) -> list[dict]:
        async with self._session() as s:
            rows = (await s.execute(
                select(ChatMessage).order_by(ChatMessage.id.asc())
            )).scalars().all()
            return [
                {"id": r.id, "role": r.role, "content": r.content, "proposals": r.proposals}
                for r in rows
            ]

    async def update_chat_proposals(self, msg_id: int, proposals_json: str):
        async with self._session() as s:
            await s.execute(
                update(ChatMessage).where(ChatMessage.id == msg_id).values(proposals=proposals_json)
            )
            await s.commit()

    async def clear_chat_messages(self):
        async with self._session() as s:
            await s.execute(delete(ChatMessage))
            await s.commit()

    # -- helpers --

    @staticmethod
    def _ep_dict(e: Episode) -> dict:
        return {
            "id": e.id, "summary": e.summary, "app_names": e.app_names,
            "frame_count": e.frame_count, "started_at": e.started_at,
            "ended_at": e.ended_at, "frame_id_min": e.frame_id_min,
            "frame_id_max": e.frame_id_max, "frame_source": e.frame_source,
            "created_at": e.created_at,
        }

    @staticmethod
    def _pb_dict(p: PlaybookEntry) -> dict:
        return {
            "id": p.id, "name": p.name, "context": p.context,
            "action": p.action, "confidence": p.confidence,
            "maturity": p.maturity, "evidence": p.evidence,
            "last_evidence_at": p.last_evidence_at,
            "created_at": p.created_at, "updated_at": p.updated_at,
        }
