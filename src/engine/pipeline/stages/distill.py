"""Stage: distill episodes into playbook entries via LLM.

Pure function — takes episodes + existing playbooks, returns new entries.
No DB writes, no side effects.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from engine.config import MODEL_DEEP
from engine.prompts.playbook import PLAYBOOK_PROMPT
from engine.llm.types import LLMResponse
from engine.pipeline.stages.extract import parse_llm_json

if TYPE_CHECKING:
    from engine.agents.service import AgentService

logger = logging.getLogger(__name__)


def format_episodes(episodes: list[dict]) -> str:
    """Format episode dicts for the distill prompt."""
    return "\n\n".join(
        f"Episode #{e.get('id', i)} ({e.get('started_at', '?')} to {e.get('ended_at', '?')}):\n{e.get('summary', '')}"
        for i, e in enumerate(episodes)
    )


def format_playbooks(playbooks: list[dict]) -> str:
    """Format existing playbook entries for the distill prompt."""
    if not playbooks:
        return "(none yet — this is the first distillation)"
    return "\n\n".join(
        f"- **{p['name']}** (confidence: {p['confidence']}, maturity: {p.get('maturity', 'nascent')})\n"
        f"  Context: {p['context']}\n"
        f"  Action: {p['action']}\n"
        f"  Evidence: {p['evidence']}"
        for p in playbooks
    )


async def distill_playbook(
    client: AgentService,
    episodes: list[dict],
    existing_playbooks: list[dict],
    prompt_template: str = PLAYBOOK_PROMPT,
    model: str = MODEL_DEEP,
) -> tuple[list[dict], LLMResponse]:
    """Pure LLM call: episodes + existing playbooks → new/updated playbook entries.

    Returns (entries, response).
    """
    prompt = prompt_template.format(
        playbooks=format_playbooks(existing_playbooks),
        episodes=format_episodes(episodes),
    )
    resp = await client.acomplete(prompt, model)
    entries = parse_llm_json(resp.text)
    logger.debug("distill returned %d playbook entries", len(entries))
    return entries, resp
