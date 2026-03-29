"""Use case: compose routines from playbooks + episodes via agentic MCP."""

import logging
import os

from engine.config import Settings
from engine.infrastructure.persistence.db import DB

logger = logging.getLogger(__name__)


async def compose_routines(settings: Settings, db: DB) -> int:
    """Run routine composition: playbooks + episodes → routines via agentic MCP.

    Returns number of routines.
    """
    logger.info("starting routine extraction")
    episodes = await db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("no episodes today, skipping routine extraction")
        return 0

    from engine.infrastructure.agent.service import AgentService
    from engine.infrastructure.agent.tools.compose_mcp import create_compose_mcp_server
    from engine.domain.prompt.routine import ROUTINE_PROMPT
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    sync_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not sync_url:
        logger.error("DATABASE_URL_SYNC not configured")
        return 0

    session_factory = get_sync_session_factory(sync_url)
    session = session_factory()
    try:
        agent = AgentService(settings)
        mcp_server = create_compose_mcp_server(session_factory)
        await agent.arun_with_mcp(
            ROUTINE_PROMPT, mcp_server, "compose", "compose_agentic", session,
        )
        session.commit()
    finally:
        session.close()

    count = len(await db.get_all_routines())
    logger.info("Routine extraction: %d routines from %d episodes", count, len(episodes))
    return count
