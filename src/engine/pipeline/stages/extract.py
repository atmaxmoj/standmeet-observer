"""Stage: extract episodes from frames via LLM.

Pure functions — no DB writes, no side effects.
Input: Frame[] + prompt + LLM → Episode dicts + response metadata.
"""

import json
import logging

from engine.config import MODEL_FAST
from engine.domain.entities.frame import Frame
from engine.domain.prompts.episode import EPISODE_PROMPT
from engine.llm import LLMClient, LLMResponse
from engine.pipeline.stages.validate import strip_fence

logger = logging.getLogger(__name__)


def build_context(frames: list[Frame]) -> str:
    """Build the text context from a list of frames (capture + audio + os_event)."""
    lines = []
    for f in frames:
        text = f.text[:300].replace("\n", " ")
        source_tag = f"[{f.source}]" if f.source != "screenpipe" else ""
        lines.append(f"[{f.timestamp}] {f.app_name}/{f.window_name}{source_tag}: {text}")
    return "\n".join(lines)


def build_context_from_dicts(
    frames: list[dict],
    audio: list[dict] | None = None,
    os_events: list[dict] | None = None,
) -> str:
    """Build context from raw API dicts (for experiments/tests)."""
    lines = []
    for f in frames:
        text = f["text"][:300].replace("\n", " ")
        lines.append(f"[{f['timestamp']}] {f['app_name']}/{f['window_name']}[capture]: {text}")
    for a in (audio or []):
        lines.append(f"[{a['timestamp']}] [audio]: {a['text'][:300]}")
    for e in (os_events or []):
        lines.append(f"[{e['timestamp']}] [os_event/{e['event_type']}]: {e['data'][:300]}")
    lines.sort()
    return "\n".join(lines)


def parse_llm_json(text: str) -> list[dict]:
    """Parse JSON from LLM response, handling markdown code fences."""
    result = json.loads(strip_fence(text))
    if not isinstance(result, list):
        result = [result]
    return result


async def extract_episodes(
    client: LLMClient,
    context: str,
    prompt: str = EPISODE_PROMPT,
    model: str = MODEL_FAST,
) -> tuple[list[dict], LLMResponse]:
    """Pure LLM call: context + prompt → parsed episodes + response metadata.

    No DB writes. Reusable for experiments with different prompts.
    """
    prompt_text = prompt.format(context=context)
    resp = await client.acomplete(prompt_text, model)
    tasks = parse_llm_json(resp.text)
    return tasks, resp
