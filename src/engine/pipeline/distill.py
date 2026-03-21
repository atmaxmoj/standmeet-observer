"""Backwards compatibility + orchestration for playbook distillation.

Pure stage functions moved to pipeline.stages.distill.
This file keeps daily_distill (async orchestration with DB writes).
"""

import json
import logging

from engine.config import MODEL_DEEP, Settings
from engine.storage.db import DB
from engine.prompts.playbook import PLAYBOOK_PROMPT
from engine.storage.memory_file import write_playbook
from engine.pipeline.stages.distill import distill_playbook

logger = logging.getLogger(__name__)


async def daily_distill(
    settings: Settings,
    db: DB,
    prompt_template: str = PLAYBOOK_PROMPT,
) -> int:
    """Run daily distillation: episodes → playbook entries.
    Returns number of playbook entries created/updated.
    """
    logger.info("starting daily distillation")
    episodes = await db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("no episodes today, skipping distillation")
        return 0

    existing = await db.get_all_playbooks()

    from engine.agents.service import AgentService
    agent = AgentService(settings)
    entries, resp = await distill_playbook(
        agent, episodes, existing, prompt_template=prompt_template,
    )

    cost_usd = resp.cost_usd or 0
    await db.record_usage(
        model=MODEL_DEEP, layer="distill",
        input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
        cost_usd=cost_usd,
    )
    prompt = prompt_template.format(
        playbooks="...", episodes="...",  # summarized for log
    )
    await db.insert_pipeline_log(
        stage="distill", prompt=prompt, response=resp.text,
        model=MODEL_DEEP, input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens, cost_usd=cost_usd,
    )

    count = 0
    for entry in entries:
        rich_action = json.dumps({
            "when": entry.get("when", ""),
            "then": entry.get("then", ""),
            "because": entry.get("because", ""),
            "boundary": entry.get("boundary"),
        }, ensure_ascii=False)
        await db.upsert_playbook(
            name=entry["name"],
            context=entry.get("when", ""),
            action=rich_action,
            confidence=entry.get("confidence", 0.5),
            evidence=json.dumps(entry.get("evidence", [])),
            maturity=entry.get("maturity", "nascent"),
        )
        playbooks_after = await db.get_all_playbooks()
        pb = next((p for p in playbooks_after if p["name"] == entry["name"]), None)
        if pb:
            write_playbook(pb)
        count += 1

    logger.info("Daily distillation: %d entries from %d episodes", count, len(episodes))
    return count
