"""Use case: autonomous DA insights via agentic MCP."""

import logging
import os
import uuid

from engine.config import Settings
from engine.infrastructure.persistence.db import DB

logger = logging.getLogger(__name__)


async def run_da(settings: Settings, db: DB) -> int:
    """Run DA analysis: playbooks + routines + episodes -> insights via agentic MCP.

    Returns number of insights created.
    """
    logger.info("starting DA analysis")

    from engine.infrastructure.agent.service import AgentService
    from engine.infrastructure.agent.tools.da_mcp import create_da_mcp_server
    from engine.domain.prompt.da import DA_PROMPT
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    sync_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not sync_url:
        logger.error("DATABASE_URL_SYNC not configured")
        return 0

    custom_prompt = await db.get_state_str("prompt:da")
    base_prompt = custom_prompt or DA_PROMPT
    run_id = uuid.uuid4().hex[:12]
    prompt = base_prompt.replace("{run_id}", run_id)

    session_factory = get_sync_session_factory(sync_url)
    session = session_factory()
    try:
        agent = AgentService(settings)
        mcp_server = create_da_mcp_server(session_factory)
        await agent.arun_with_mcp(
            prompt, mcp_server, "da", "da_agentic", session,
        )
        session.commit()
    finally:
        session.close()

    count = await db.count_insights(run_id=run_id)
    logger.info("DA analysis: %d insights (run_id=%s)", count, run_id)
    return count
