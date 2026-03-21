"""Pipeline orchestrator — shared logic for sync and async callers.

Each function takes explicit dependencies (settings/agent, session/db, prompt).
No module-level state, no side effects beyond what's passed in.
"""

import json
import logging

from sqlalchemy.orm import Session

from engine.config import MODEL_FAST, MODEL_DEEP, Settings
from engine.prompts.episode import EPISODE_PROMPT
from engine.prompts.playbook import PLAYBOOK_PROMPT
from engine.prompts.routine import ROUTINE_PROMPT
from engine.storage.sync_db import SyncDB
from engine.etl.collect import load_frames, store_episodes
from engine.pipeline.stages.extract import build_context, parse_llm_json
from engine.pipeline.stages.distill import format_episodes, format_playbooks
from engine.pipeline.stages.compose import (
    format_playbooks_for_routines, format_routines, format_episodes_for_routines,
)
from engine.pipeline.stages.validate import validate_episodes, validate_playbooks, with_retry

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
    from engine.agents.service import AgentService

    frames = load_frames(session, screen_ids, audio_ids, os_event_ids)
    if source_ids:
        from engine.etl.sources.manifest_registry import get_global_registry
        from engine.etl.repository import load_source_frames
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


def run_distill(
    settings: Settings,
    session: Session,
    prompt_template: str = PLAYBOOK_PROMPT,
) -> int:
    """Sync distill pipeline: read episodes → infer → store playbooks.

    Returns count of entries created/updated. Caller must session.commit().
    """
    from engine.agents.service import AgentService

    db = SyncDB(session)
    episodes = db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("run_distill: no episodes, skipping")
        return 0

    agent = AgentService(settings)
    if agent.uses_sdk:
        return _run_distill_agentic(agent, session)
    return _run_distill_oneshot(agent, session, db, episodes, prompt_template)


def _run_distill_agentic(agent, session: Session) -> int:
    """Agentic distill: multi-turn tool loop via MCP."""
    from engine.prompts.playbook_agent import PLAYBOOK_AGENT_PROMPT
    from engine.agents.tools.distill_mcp import create_distill_mcp_server

    mcp_server = create_distill_mcp_server(session)
    agent.run_with_mcp(PLAYBOOK_AGENT_PROMPT, mcp_server, "distill", "distill_agentic", session)

    count = SyncDB(session).count_recent_playbooks()
    logger.info("run_distill (agentic): %d entries", count)
    return count


def _run_distill_oneshot(agent, session, db: SyncDB, episodes, prompt_template) -> int:
    """One-shot distill: single prompt → JSON response."""
    existing = db.get_all_playbooks()

    prompt = prompt_template.format(
        playbooks=format_playbooks(existing),
        episodes=format_episodes(episodes),
    )

    last_resp = [None]

    def _call_llm(retry_prompt):
        p = retry_prompt if retry_prompt else prompt
        resp = agent.complete(p, MODEL_DEEP)
        last_resp[0] = resp
        return resp.text

    entries = with_retry(_call_llm, validate_playbooks, max_retries=1)
    resp = last_resp[0]

    cost = resp.cost_usd or 0
    db.record_usage(MODEL_DEEP, "distill", resp.input_tokens, resp.output_tokens, cost)
    db.insert_pipeline_log("distill", prompt, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost)

    count = 0
    for entry in entries:
        rich_action = json.dumps({
            "when": entry.get("when", ""),
            "then": entry.get("then", ""),
            "because": entry.get("because", ""),
            "boundary": entry.get("boundary"),
        }, ensure_ascii=False)
        db.upsert_playbook(
            name=entry["name"],
            context=entry.get("when", ""),
            action=rich_action,
            confidence=entry.get("confidence", 0.5),
            maturity=entry.get("maturity", "nascent"),
            evidence=json.dumps(entry.get("evidence", [])),
        )
        count += 1

    logger.info("run_distill: %d entries from %d episodes, cost=$%.4f", count, len(episodes), cost)
    return count


def run_routines(
    settings: Settings,
    session: Session,
    prompt_template: str = ROUTINE_PROMPT,
) -> int:
    """Sync routine pipeline: read episodes+playbooks → infer → store routines.

    Returns count. Caller must session.commit().
    """
    from engine.agents.service import AgentService

    db = SyncDB(session)
    episodes = db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("run_routines: no episodes, skipping")
        return 0

    agent = AgentService(settings)
    if agent.uses_sdk:
        return _run_compose_agentic(agent, session)
    return _run_routines_oneshot(agent, session, db, episodes, prompt_template)


def _run_compose_agentic(agent, session: Session) -> int:
    """Agentic routine composition via MCP."""
    from engine.prompts.compose_agent import ROUTINE_AGENT_PROMPT
    from engine.agents.tools.compose_mcp import create_compose_mcp_server

    mcp_server = create_compose_mcp_server(session)
    agent.run_with_mcp(ROUTINE_AGENT_PROMPT, mcp_server, "compose", "compose_agentic", session)

    count = SyncDB(session).count_recent_routines()
    logger.info("run_routines (agentic): %d routines", count)
    return count


def _run_routines_oneshot(agent, session, db: SyncDB, episodes, prompt_template) -> int:
    """One-shot routine composition: single prompt → JSON response."""
    playbooks = db.get_all_playbooks()
    existing_routines = db.get_all_routines()

    prompt = prompt_template.format(
        playbooks=format_playbooks_for_routines(playbooks),
        routines=format_routines(existing_routines),
        episodes=format_episodes_for_routines(episodes),
    )

    resp = agent.complete(prompt, MODEL_DEEP)
    cost = resp.cost_usd or 0

    db.record_usage(MODEL_DEEP, "compose", resp.input_tokens, resp.output_tokens, cost)
    db.insert_pipeline_log("compose", prompt, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost)

    entries = parse_llm_json(resp.text)
    count = 0
    for entry in entries:
        db.upsert_routine(
            name=entry["name"],
            trigger=entry.get("trigger", ""),
            goal=entry.get("goal", ""),
            steps=json.dumps(entry.get("steps", []), ensure_ascii=False),
            uses=json.dumps(entry.get("uses", []), ensure_ascii=False),
            confidence=entry.get("confidence", 0.4),
            maturity=entry.get("maturity", "nascent"),
        )
        count += 1

    logger.info("run_routines: %d routines from %d episodes, cost=$%.4f", count, len(episodes), cost)
    return count
