"""Stage: extract episodes from frames via LLM.

Pure functions — no DB writes, no side effects.
Input: Frame[] + prompt + LLM → Episode dicts + response metadata.
"""

import json
import logging

from engine.config import MODEL_FAST
from engine.etl.entities import Frame
from engine.prompts.episode import EPISODE_PROMPT
from engine.llm.types import LLMResponse
from engine.pipeline.stages.validate import strip_fence

logger = logging.getLogger(__name__)


def build_context(frames: list[Frame]) -> str:
    """Build the text context from a list of frames (capture + audio + os_event + manifest sources)."""
    from engine.etl.sources.manifest_registry import get_global_registry

    registry = get_global_registry()

    lines = []
    for f in frames:
        text = f.text[:300].replace("\n", " ")

        # Try manifest-based formatting first
        if registry and registry.has(f.source):
            manifest = registry.get_manifest(f.source)
            fmt = manifest.context_format
            if fmt:
                try:
                    lines.append(fmt.format(
                        timestamp=f.timestamp,
                        app_name=f.app_name,
                        window_name=f.window_name,
                        text=text,
                        source=f.source,
                        command=f.text[:300].replace("\n", " "),
                    ))
                    continue
                except (KeyError, IndexError):
                    pass

        # Fallback: original format
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
    client,
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
