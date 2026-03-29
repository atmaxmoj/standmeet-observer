"""Pipeline orchestrator — shared logic for sync callers (scheduler).

Each function takes explicit dependencies (settings, session).
No module-level state, no side effects beyond what's passed in.
"""

import logging

from sqlalchemy.orm import Session, sessionmaker

from engine.config import MODEL_FAST, Settings
from engine.domain.prompt.episode import EPISODE_PROMPT
from engine.infrastructure.persistence.sync_db import SyncDB
from engine.infrastructure.etl.collect import load_frames, store_episodes
from engine.infrastructure.pipeline.stages.extract import build_context
from engine.infrastructure.pipeline.stages.validate import validate_episodes, with_retry

logger = logging.getLogger(__name__)


def run_episode(
    settings: Settings,
    session: Session,
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
    source_ids: dict[str, list[int]] | None = None,
    prompt: str = EPISODE_PROMPT,
) -> tuple[list[dict], int]:
    """Sync episode pipeline: load → build → infer → validate → store.

    Returns (tasks, episode_count). Caller must session.commit().
    """
    from engine.infrastructure.agent.service import AgentService

    frames = load_frames(session, screen_ids, audio_ids, os_event_ids)
    if source_ids:
        from engine.infrastructure.etl.sources.manifest_registry import get_global_registry
        from engine.infrastructure.etl.repository import load_source_frames
        registry = get_global_registry()
        if registry:
            frames.extend(load_source_frames(session, registry, source_ids))
            frames.sort(key=lambda f: f.timestamp)
    if not frames:
        return [], 0

    db = SyncDB(session)
    agent = AgentService(settings)
    logger.info("run_episode: %d frames [%s -> %s]", len(frames), frames[0].timestamp, frames[-1].timestamp)

    prompt_text = prompt.format(context=build_context(frames))

    last_resp = [None]

    def _call_llm(retry_prompt):
        p = retry_prompt if retry_prompt else prompt_text
        resp = agent.complete(p, MODEL_FAST)
        last_resp[0] = resp
        return resp.text

    tasks = with_retry(_call_llm, validate_episodes, max_retries=1)
    resp = last_resp[0]

    store_episodes(session, tasks, frames)

    cost = resp.cost_usd or 0
    db.record_usage(MODEL_FAST, "episode", resp.input_tokens, resp.output_tokens, cost)
    db.insert_pipeline_log("episode", prompt_text, resp.text, MODEL_FAST, resp.input_tokens, resp.output_tokens, cost)

    logger.info("run_episode: created %d episodes, cost=$%.4f", len(tasks), cost)
    return tasks, len(tasks)


def run_distill(settings: Settings, session: Session) -> int:
    """Sync distill pipeline via agentic MCP.

    Returns count of entries created/updated. Caller must session.commit().
    """
    from engine.infrastructure.agent.service import AgentService
    from engine.domain.prompt.playbook import PLAYBOOK_PROMPT
    from engine.infrastructure.agent.tools.distill_mcp import create_distill_mcp_server

    db = SyncDB(session)
    episodes = db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("run_distill: no episodes, skipping")
        return 0

    agent = AgentService(settings)
    factory = sessionmaker(bind=session.get_bind())
    mcp_server = create_distill_mcp_server(factory)
    agent.run_with_mcp(PLAYBOOK_PROMPT, mcp_server, "distill", "distill_agentic", session)

    count = db.count_recent_playbooks()
    logger.info("run_distill: %d entries", count)
    return count


def run_routines(settings: Settings, session: Session) -> int:
    """Sync routine pipeline via agentic MCP.

    Returns count. Caller must session.commit().
    """
    from engine.infrastructure.agent.service import AgentService
    from engine.domain.prompt.routine import ROUTINE_PROMPT
    from engine.infrastructure.agent.tools.compose_mcp import create_compose_mcp_server

    db = SyncDB(session)
    episodes = db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("run_routines: no episodes, skipping")
        return 0

    agent = AgentService(settings)
    factory = sessionmaker(bind=session.get_bind())
    mcp_server = create_compose_mcp_server(factory)
    agent.run_with_mcp(ROUTINE_PROMPT, mcp_server, "compose", "compose_agentic", session)

    count = db.count_recent_routines()
    logger.info("run_routines: %d routines", count)
    return count
