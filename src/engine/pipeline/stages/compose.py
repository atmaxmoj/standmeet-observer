"""Stage: compose playbook entries + episodes into routines via LLM.

Pure function — returns routine dicts, no DB writes.
"""

import logging

from engine.config import MODEL_DEEP
from engine.prompts.routine import ROUTINE_PROMPT
from engine.llm.types import LLMResponse
from engine.pipeline.stages.extract import parse_llm_json

logger = logging.getLogger(__name__)


def format_playbooks_for_routines(playbooks: list[dict]) -> str:
    if not playbooks:
        return "(no playbook entries yet)"
    return "\n".join(
        f"- **{p['name']}** ({p.get('confidence', 0):.1f}): "
        f"{p.get('context', '')} → {p.get('action', '')}"
        for p in playbooks
    )


def format_routines(routines: list[dict]) -> str:
    if not routines:
        return "(none yet)"
    return "\n\n".join(
        f"- **{r['name']}** (confidence: {r.get('confidence', 0)}, maturity: {r.get('maturity', 'nascent')})\n"
        f"  Trigger: {r.get('trigger', '')}\n  Goal: {r.get('goal', '')}\n"
        f"  Steps: {r.get('steps', '[]')}\n  Uses: {r.get('uses', '[]')}"
        for r in routines
    )


def format_episodes_for_routines(episodes: list[dict]) -> str:
    return "\n\n".join(
        f"Episode #{e.get('id', i)} ({e.get('started_at', '?')} to {e.get('ended_at', '?')}):\n{e.get('summary', '')}"
        for i, e in enumerate(episodes)
    )


async def compose_routines(
    client,
    episodes: list[dict],
    playbooks: list[dict],
    existing_routines: list[dict],
    prompt_template: str = ROUTINE_PROMPT,
    model: str = MODEL_DEEP,
) -> tuple[list[dict], LLMResponse]:
    """Pure LLM call: episodes + playbooks + existing routines → new/updated routines.

    Returns (routines, response).
    """
    prompt = prompt_template.format(
        playbooks=format_playbooks_for_routines(playbooks),
        routines=format_routines(existing_routines),
        episodes=format_episodes_for_routines(episodes),
    )
    resp = await client.acomplete(prompt, model)
    entries = parse_llm_json(resp.text)
    logger.debug("compose returned %d routines", len(entries))
    return entries, resp
