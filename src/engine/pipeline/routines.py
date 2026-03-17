"""Backwards compatibility + orchestration for routine composition.

Pure stage functions moved to pipeline.stages.compose.
This file keeps daily_routines (async orchestration with DB writes).
"""

import json
import logging

from engine.config import MODEL_DEEP
from engine.db import DB
from engine.domain.prompts.routine import ROUTINE_PROMPT  # noqa: F401
from engine.llm import LLMClient
from engine.infra.memory_file import write_routine
from engine.pipeline.stages.compose import compose_routines

logger = logging.getLogger(__name__)


async def daily_routines(
    client: LLMClient,
    db: DB,
    prompt_template: str = ROUTINE_PROMPT,
) -> int:
    """Run daily routine extraction: episodes + playbook → routines."""
    logger.info("starting routine extraction")
    episodes = await db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("no episodes today, skipping routine extraction")
        return 0

    playbooks = await db.get_all_playbooks()
    existing_routines = await db.get_all_routines()

    entries, resp = await compose_routines(
        client, episodes, playbooks, existing_routines,
        prompt_template=prompt_template,
    )

    cost_usd = resp.cost_usd or 0
    await db.record_usage(
        model=MODEL_DEEP, layer="routines",
        input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
        cost_usd=cost_usd,
    )
    await db.insert_pipeline_log(
        stage="routines", prompt="...", response=resp.text,
        model=MODEL_DEEP, input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens, cost_usd=cost_usd,
    )

    count = 0
    for entry in entries:
        await db.upsert_routine(
            name=entry["name"],
            trigger=entry.get("trigger", ""),
            goal=entry.get("goal", ""),
            steps=json.dumps(entry.get("steps", []), ensure_ascii=False),
            uses=json.dumps(entry.get("uses", []), ensure_ascii=False),
            confidence=entry.get("confidence", 0.4),
            maturity=entry.get("maturity", "nascent"),
        )
        routines_after = await db.get_all_routines()
        rt = next((r for r in routines_after if r["name"] == entry["name"]), None)
        if rt:
            write_routine(rt)
        count += 1

    logger.info("Routine extraction: %d routines from %d episodes", count, len(episodes))
    return count
