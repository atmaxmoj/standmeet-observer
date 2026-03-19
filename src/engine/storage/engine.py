"""SQLAlchemy engine + session factories."""

from sqlalchemy import create_engine as _create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker, Session

from engine.storage.models import Base


def create_sync_engine(url: str):
    """Create a sync SQLAlchemy engine from a URL."""
    engine = _create_engine(url, echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_sync_session_factory(url: str) -> sessionmaker[Session]:
    """Create a sync session factory from a URL."""
    engine = create_sync_engine(url)
    return sessionmaker(bind=engine)


def get_async_session_factory(url: str) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory from a URL."""
    engine = create_async_engine(url, echo=False)
    return async_sessionmaker(bind=engine, expire_on_commit=False)
