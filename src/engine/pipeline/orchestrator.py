"""Pipeline orchestrator — shared logic for sync and async callers.

Each function takes explicit dependencies (llm, conn/db, prompt).
No module-level state, no side effects beyond what's passed in.
"""

import json
import logging
import sqlite3

from engine.config import MODEL_FAST, MODEL_DEEP
from engine.domain.prompts.episode import EPISODE_PROMPT
from engine.domain.prompts.playbook import PLAYBOOK_PROMPT
from engine.domain.prompts.routine import ROUTINE_PROMPT
from engine.infra.llm import LLMClient
from engine.pipeline.stages.collect import load_frames, store_episodes
from engine.pipeline.stages.extract import build_context, parse_llm_json
from engine.pipeline.stages.distill import format_episodes, format_playbooks
from engine.pipeline.stages.compose import (
    format_playbooks_for_routines, format_routines, format_episodes_for_routines,
)
from engine.pipeline.stages.validate import validate_episodes, validate_playbooks, with_retry

logger = logging.getLogger(__name__)


def run_episode(
    llm: LLMClient,
    conn: sqlite3.Connection,
    screen_ids: list[int],
    audio_ids: list[int],
    os_event_ids: list[int] | None = None,
    prompt: str = EPISODE_PROMPT,
) -> tuple[list[dict], int]:
    """Sync episode pipeline: load → build → infer → validate → store.

    Returns (tasks, episode_count). Caller must conn.commit().
    """
    frames = load_frames(conn, screen_ids, audio_ids, os_event_ids)
    if not frames:
        return [], 0

    logger.info("run_episode: %d frames [%s -> %s]", len(frames), frames[0].timestamp, frames[-1].timestamp)

    prompt_text = prompt.format(context=build_context(frames))

    last_resp = [None]

    def _call_llm(retry_prompt):
        p = retry_prompt if retry_prompt else prompt_text
        resp = llm.complete(p, MODEL_FAST)
        last_resp[0] = resp
        return resp.text

    tasks = with_retry(_call_llm, validate_episodes, max_retries=1)
    resp = last_resp[0]

    store_episodes(conn, tasks, frames)

    cost = resp.cost_usd or 0
    conn.execute(
        "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?)",
        (MODEL_FAST, "episode", resp.input_tokens, resp.output_tokens, cost),
    )
    conn.execute(
        "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("episode", prompt_text, resp.text, MODEL_FAST, resp.input_tokens, resp.output_tokens, cost),
    )

    logger.info("run_episode: created %d episodes, cost=$%.4f", len(tasks), cost)
    return tasks, len(tasks)


def run_distill(
    llm: LLMClient,
    conn: sqlite3.Connection,
    prompt_template: str = PLAYBOOK_PROMPT,
    agentic: bool = False,
) -> int:
    """Sync distill pipeline: read episodes → infer → store playbooks.

    If agentic=True, uses multi-turn tool-use loop (LLM investigates data autonomously).
    If agentic=False, uses one-shot prompt (backwards compat).

    Returns count of entries created/updated. Caller must conn.commit().
    """
    episodes = conn.execute(
        "SELECT * FROM episodes WHERE created_at >= datetime('now', '-1 days') ORDER BY created_at",
    ).fetchall()
    if not episodes:
        logger.info("run_distill: no episodes, skipping")
        return 0

    if agentic:
        return _run_distill_agentic(llm, conn)

    return _run_distill_oneshot(llm, conn, episodes, prompt_template)


def _run_distill_agentic(llm: LLMClient, conn: sqlite3.Connection) -> int:
    """Agentic distill: LLM uses MCP tools to investigate episodes and write playbook entries.

    Uses Agent SDK query() with in-process MCP server — works with OAuth tokens + Opus.
    """
    import asyncio
    import os
    from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions, ResultMessage
    from engine.domain.prompts.playbook_agent import PLAYBOOK_AGENT_PROMPT
    from engine.pipeline.stages.distill_mcp import create_distill_mcp_server

    mcp_server = create_distill_mcp_server(conn)
    logger.info("run_distill (agentic): starting with MCP server")

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env.pop("ANTHROPIC_API_KEY", None)

    result_text = ""
    cost_usd = None
    usage: dict = {}

    async def _run():
        nonlocal result_text, cost_usd, usage
        async for msg in sdk_query(
            prompt=PLAYBOOK_AGENT_PROMPT,
            options=ClaudeAgentOptions(
                model=MODEL_DEEP,
                max_turns=15,
                permission_mode="bypassPermissions",
                mcp_servers={
                    "distill": {
                        "type": "sdk",
                        "name": "distill-tools",
                        "instance": mcp_server._mcp_server,
                    },
                },
                env=env,
            ),
        ):
            if isinstance(msg, ResultMessage):
                result_text = msg.result or ""
                cost_usd = msg.total_cost_usd
                usage = msg.usage or {}

    asyncio.run(_run())

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cost = cost_usd or 0

    conn.execute(
        "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?)",
        (MODEL_DEEP, "distill_agentic", input_tokens, output_tokens, cost),
    )
    conn.execute(
        "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("distill_agentic", PLAYBOOK_AGENT_PROMPT, result_text[:5000], MODEL_DEEP,
         input_tokens, output_tokens, cost),
    )

    count = conn.execute(
        "SELECT COUNT(*) FROM playbook_entries WHERE updated_at >= datetime('now', '-1 hours')",
    ).fetchone()[0]

    logger.info("run_distill (agentic): %d entries, cost=$%.4f", count, cost)
    return count


def _run_distill_oneshot(llm, conn, episodes, prompt_template) -> int:
    """One-shot distill: single prompt → JSON response."""
    existing = conn.execute("SELECT * FROM playbook_entries ORDER BY confidence DESC").fetchall()

    episodes_list = [dict(e) for e in episodes]
    existing_list = [dict(e) for e in existing]

    prompt = prompt_template.format(
        playbooks=format_playbooks(existing_list),
        episodes=format_episodes(episodes_list),
    )

    last_resp = [None]

    def _call_llm(retry_prompt):
        p = retry_prompt if retry_prompt else prompt
        resp = llm.complete(p, MODEL_DEEP)
        last_resp[0] = resp
        return resp.text

    entries = with_retry(_call_llm, validate_playbooks, max_retries=1)
    resp = last_resp[0]

    cost = resp.cost_usd or 0
    conn.execute(
        "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?)",
        (MODEL_DEEP, "distill", resp.input_tokens, resp.output_tokens, cost),
    )
    conn.execute(
        "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("distill", prompt, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost),
    )

    count = 0
    for entry in entries:
        rich_action = json.dumps({
            "intuition": entry.get("intuition", ""),
            "action": entry.get("action", ""),
            "why": entry.get("why", ""),
            "counterexample": entry.get("counterexample"),
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET "
            "context=excluded.context, action=excluded.action, "
            "confidence=excluded.confidence, maturity=excluded.maturity, "
            "evidence=excluded.evidence, updated_at=datetime('now')",
            (entry["name"], entry.get("context", ""), rich_action,
             entry.get("confidence", 0.5), entry.get("maturity", "nascent"),
             json.dumps(entry.get("evidence", []))),
        )
        count += 1

    logger.info("run_distill: %d entries from %d episodes, cost=$%.4f", count, len(episodes), cost)
    return count


def run_routines(
    llm: LLMClient,
    conn: sqlite3.Connection,
    prompt_template: str = ROUTINE_PROMPT,
) -> int:
    """Sync routine pipeline: read episodes+playbooks → infer → store routines.

    Returns count. Caller must conn.commit().
    """
    episodes = conn.execute(
        "SELECT * FROM episodes WHERE created_at >= datetime('now', '-1 days') ORDER BY created_at",
    ).fetchall()
    if not episodes:
        logger.info("run_routines: no episodes, skipping")
        return 0

    playbooks = conn.execute("SELECT * FROM playbook_entries ORDER BY confidence DESC").fetchall()
    existing_routines = conn.execute("SELECT * FROM routines ORDER BY confidence DESC").fetchall()

    episodes_list = [dict(e) for e in episodes]
    playbooks_list = [dict(p) for p in playbooks]
    routines_list = [dict(r) for r in existing_routines]

    prompt = prompt_template.format(
        playbooks=format_playbooks_for_routines(playbooks_list),
        routines=format_routines(routines_list),
        episodes=format_episodes_for_routines(episodes_list),
    )

    resp = llm.complete(prompt, MODEL_DEEP)
    cost = resp.cost_usd or 0

    conn.execute(
        "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?)",
        (MODEL_DEEP, "routines", resp.input_tokens, resp.output_tokens, cost),
    )
    conn.execute(
        "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("routines", prompt, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost),
    )

    entries = parse_llm_json(resp.text)
    count = 0
    for entry in entries:
        conn.execute(
            "INSERT INTO routines (name, trigger, goal, steps, uses, confidence, maturity, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET "
            "trigger=excluded.trigger, goal=excluded.goal, steps=excluded.steps, "
            "uses=excluded.uses, confidence=excluded.confidence, maturity=excluded.maturity, "
            "updated_at=datetime('now')",
            (entry["name"], entry.get("trigger", ""), entry.get("goal", ""),
             json.dumps(entry.get("steps", []), ensure_ascii=False),
             json.dumps(entry.get("uses", []), ensure_ascii=False),
             entry.get("confidence", 0.4), entry.get("maturity", "nascent")),
        )
        count += 1

    logger.info("run_routines: %d routines from %d episodes, cost=$%.4f", count, len(episodes), cost)
    return count
