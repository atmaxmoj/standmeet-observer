"""SQLAlchemy ORM models for all engine tables."""

from datetime import datetime, timezone

from sqlalchemy import (
    Integer, Float, Text, Index,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Frame(Base):
    __tablename__ = "frames"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    app_name: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    window_name: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    display_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    image_hash: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    image_path: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_frames_id", "id"),
        Index("idx_frames_processed", "processed"),
    )


class AudioFrame(Base):
    __tablename__ = "audio_frames"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    language: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="mic", server_default="mic")
    chunk_path: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_audio_frames_id", "id"),
        Index("idx_audio_frames_processed", "processed"),
    )


class OsEvent(Base):
    __tablename__ = "os_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    data: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_os_events_id", "id"),
        Index("idx_os_events_type", "event_type"),
        Index("idx_os_events_processed", "processed"),
    )


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    app_names: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    ended_at: Mapped[str] = mapped_column(Text, nullable=False)
    frame_id_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    frame_id_max: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    frame_source: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())


class PlaybookEntry(Base):
    __tablename__ = "playbook_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    context: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    action: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    base_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    maturity: Mapped[str] = mapped_column(Text, nullable=False, default="nascent", server_default="nascent")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    last_evidence_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_token_usage_created_at", "created_at"),
    )


class State(Base):
    __tablename__ = "state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    response: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    model: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_pipeline_logs_stage", "stage"),
        Index("idx_pipeline_logs_created_at", "created_at"),
    )


class PlaybookHistory(Base):
    __tablename__ = "playbook_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    playbook_name: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    maturity: Mapped[str] = mapped_column(Text, nullable=False, default="nascent", server_default="nascent")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    change_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_playbook_history_name", "playbook_name"),
    )


class Routine(Base):
    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    trigger: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    steps: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    uses: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    base_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    maturity: Mapped[str] = mapped_column(Text, nullable=False, default="nascent", server_default="nascent")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    category: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    data: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    run_id: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_insights_created_at", "created_at"),
        Index("idx_insights_run_id", "run_id"),
    )


class DaGoal(Base):
    __tablename__ = "da_goals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    progress_notes: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    proposals: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=func.now())
