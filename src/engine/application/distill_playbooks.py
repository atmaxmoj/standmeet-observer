"""Use case: distill episodes into playbook entries via agentic MCP."""

import logging
import os

from engine.config import Settings
from engine.infrastructure.persistence.db import DB

logger = logging.getLogger(__name__)


async def distill_playbooks(settings: Settings, db: DB) -> int:
    """Run playbook distillation: episodes → playbook entries via agentic MCP.

    Returns number of playbook entries.
    """
    logger.info("starting daily distillation")
    episodes = await db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("no episodes today, skipping distillation")
        return 0

    from engine.infrastructure.agent.service import AgentService
    from engine.infrastructure.agent.tools.distill_mcp import create_distill_mcp_server
    from engine.domain.prompt.playbook import PLAYBOOK_PROMPT
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    sync_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not sync_url:
        logger.error("DATABASE_URL_SYNC not configured")
        return 0

    session_factory = get_sync_session_factory(sync_url)
    session = session_factory()
    try:
        agent = AgentService(settings)
        mcp_server = create_distill_mcp_server(session_factory)
        await agent.arun_with_mcp(
            PLAYBOOK_PROMPT, mcp_server, "distill", "distill_agentic", session,
        )
        session.commit()
    finally:
        session.close()

    count = len(await db.get_all_playbooks())
    logger.info("Daily distillation: %d entries from %d episodes", count, len(episodes))
    return count
