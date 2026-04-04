"""Use case: autonomous Scrum Master task tracking via agentic MCP."""

import logging
import os
import uuid

from engine.config import Settings
from engine.infrastructure.persistence.db import DB

logger = logging.getLogger(__name__)


async def run_scm(settings: Settings, db: DB) -> int:
    """Run Scrum Master: scan episodes → create/update tasks via agentic MCP.

    Returns number of tasks created or updated.
    """
    logger.info("starting Scrum Master")

    from engine.infrastructure.agent.service import AgentService
    from engine.infrastructure.agent.tools.scm_mcp import create_scm_mcp_server
    from engine.domain.prompt.scm import SCM_PROMPT
    from engine.infrastructure.persistence.engine import get_sync_session_factory

    sync_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not sync_url:
        logger.error("DATABASE_URL_SYNC not configured")
        return 0

    custom_prompt = await db.get_state_str("prompt:scm")
    base_prompt = custom_prompt or SCM_PROMPT
    run_id = uuid.uuid4().hex[:12]
    prompt = base_prompt.replace("{run_id}", run_id)

    session_factory = get_sync_session_factory(sync_url)
    session = session_factory()
    try:
        agent = AgentService(settings)
        mcp_server = create_scm_mcp_server(session_factory)
        await agent.arun_with_mcp(
            prompt, mcp_server, "scm", "scm_agentic", session,
        )
        session.commit()
    finally:
        session.close()

    count = await db.count_scm_tasks()
    logger.info("Scrum Master: %d total tasks", count)
    return count
