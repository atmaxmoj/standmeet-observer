"""SQLAlchemy engine + session factories."""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker, Session

from engine.storage.models import Base


def create_sync_engine(db_path: str):
    """Create a sync SQLAlchemy engine for SQLite."""
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(engine)
    return engine


def create_async_engine_sqlite(db_path: str):
    """Create an async SQLAlchemy engine for SQLite (aiosqlite)."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )
    return engine


def get_sync_session_factory(db_path: str) -> sessionmaker[Session]:
    """Create a sync session factory."""
    engine = create_sync_engine(db_path)
    return sessionmaker(bind=engine)


def get_async_session_factory(db_path: str) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory."""
    engine = create_async_engine_sqlite(db_path)
    return async_sessionmaker(bind=engine, expire_on_commit=False)
