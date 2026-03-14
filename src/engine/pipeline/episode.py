"""Task-level: Haiku analyzes a time window, identifies tasks, and creates episodes."""

import base64
import json
import logging
from pathlib import Path

import anthropic

from engine.config import MODEL_TASK, TOKEN_COSTS
from engine.db import DB
from engine.pipeline.collector import Frame

logger = logging.getLogger(__name__)

EPISODE_PROMPT = """\
You are an apprentice learning how your master works by observing their screen activity.
A good apprentice watches the whole thing before summarizing — not step by step.

Analyze this activity window and identify the distinct tasks the user performed.

A "task" is a coherent unit of work toward one goal. The user may switch apps \
(VSCode → Chrome → Terminal) while working on the same task — that's still one task. \
A new task starts when the user's GOAL changes, not when they switch apps.

For each task, observe these dimensions:

1. **What they did** — tools, sequence, outcome
2. **Turning points** — moments of correction (wrote then deleted then rewrote), \
choice (had options, picked one), hesitation (long pause then sudden action), \
or abandonment (started something then switched direction)
3. **What they DIDN'T do** — tools/features available but not used, \
steps that seem standard but were skipped. "Never" reveals more than "always".
4. **Pressure signals** — if you see: rapid app switching, skipping usual steps, \
working at unusual hours, or frequency spikes — mark the task as under_pressure=true. \
Habits dropped under pressure = learned discipline. Habits kept = internalized.

Screen activity log:
{context}

Output valid JSON array (one object per task):
[
  {{
    "summary": "2-4 sentences: what they did, what tools, key decisions, outcome",
    "method": "the sequence/approach they followed (e.g. 'logs first, then code' or 'google → stackoverflow → source code')",
    "turning_points": ["corrections, choices, hesitations, or abandonments observed"],
    "avoidance": ["tools/features/steps available but not used, if any"],
    "under_pressure": false,
    "apps": ["App1", "App2"],
    "started_at": "...",
    "ended_at": "..."
  }}
]

Output ONLY the JSON array, nothing else."""


def _sample_images(
    frames: list[Frame],
    frames_base_dir: str,
    max_images: int = 5,
) -> list[tuple[int, str, bytes]]:
    """
    Sample up to max_images from the window, evenly spaced.
    Returns [(frame_id, media_type, base64_bytes), ...].
    Only includes frames that have image files on disk.
    """
    frames_with_images = [
        f for f in frames if f.image_path
    ]
    if not frames_with_images:
        return []

    # Evenly sample
    step = max(1, len(frames_with_images) // max_images)
    sampled = frames_with_images[::step][:max_images]

    result = []
    for f in sampled:
        path = Path(frames_base_dir) / f.image_path
        if not path.exists():
            continue
        image_bytes = path.read_bytes()
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        result.append((f.id, "image/webp", b64))

    logger.debug(
        "sampled %d images from %d frames with images (of %d total)",
        len(result), len(frames_with_images), len(frames),
    )
    return result


async def process_window(
    client: anthropic.AsyncAnthropic,
    db: DB,
    frames: list[Frame],
    frames_base_dir: str = "",
) -> list[int]:
    """
    Send a time window of frames to Haiku (with sampled screenshots).
    Haiku identifies task boundaries and summarizes each task with rich signals.
    Returns list of created episode IDs.
    """
    if not frames:
        logger.debug("process_window called with empty frames, skipping")
        return []

    logger.debug(
        "process_window: %d frames, time range [%s, %s]",
        len(frames), frames[0].timestamp, frames[-1].timestamp,
    )

    context_lines = []
    for f in frames:
        text = f.text[:300].replace("\n", " ")
        source_tag = f"[{f.source}]" if f.source != "screenpipe" else ""
        context_lines.append(
            f"[{f.timestamp}] {f.app_name}/{f.window_name}{source_tag}: {text}"
        )
    context = "\n".join(context_lines)
    logger.debug("built context for haiku: %d lines, %d chars", len(context_lines), len(context))

    # Build multimodal message content: text + sampled images
    content = []
    sampled_images = _sample_images(frames, frames_base_dir) if frames_base_dir else []
    if sampled_images:
        for frame_id, media_type, b64_data in sampled_images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64_data},
            })
        logger.debug("attached %d sampled screenshots to haiku request", len(sampled_images))

    content.append({
        "type": "text",
        "text": EPISODE_PROMPT.format(context=context),
    })

    try:
        logger.debug("sending %d frames to haiku model=%s", len(frames), MODEL_TASK)
        response = await client.messages.create(
            model=MODEL_TASK,  # Haiku — cheap, ~$0.01-0.03 per window
            max_tokens=2048,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text
        usage = response.usage
        logger.debug("haiku response: %d chars, usage: %s", len(raw), usage)

        # Record token usage
        costs = TOKEN_COSTS.get(MODEL_TASK, {"input": 0, "output": 0})
        cost_usd = usage.input_tokens * costs["input"] + usage.output_tokens * costs["output"]
        await db.record_usage(
            model=MODEL_TASK,
            layer="episode",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd,
        )
        logger.debug("recorded usage: model=%s cost=$%.6f", MODEL_TASK, cost_usd)

        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]

        tasks = json.loads(text)
        if not isinstance(tasks, list):
            tasks = [tasks]
        logger.debug("haiku identified %d tasks in window", len(tasks))

        # Compute frame ID range for this window
        frame_id_min = min(f.id for f in frames)
        frame_id_max = max(f.id for f in frames)
        # Determine primary source
        sources = set(f.source for f in frames)
        frame_source = ",".join(sorted(sources))

        episode_ids = []
        for task in tasks:
            # Store the full rich summary as JSON
            summary = json.dumps(
                {
                    "summary": task.get("summary", ""),
                    "method": task.get("method", ""),
                    "turning_points": task.get("turning_points", []),
                    "avoidance": task.get("avoidance", []),
                    "under_pressure": task.get("under_pressure", False),
                },
                ensure_ascii=False,
            )

            episode_id = await db.insert_episode(
                summary=summary,
                app_names=json.dumps(task.get("apps", [])),
                frame_count=len(frames),
                started_at=task.get("started_at", frames[0].timestamp),
                ended_at=task.get("ended_at", frames[-1].timestamp),
                frame_id_min=frame_id_min,
                frame_id_max=frame_id_max,
                frame_source=frame_source,
            )
            episode_ids.append(episode_id)
            logger.info(
                "Created episode #%d: %s",
                episode_id,
                task.get("summary", "")[:80],
            )

        return episode_ids

    except Exception:
        logger.exception("Failed to process window (%d frames)", len(frames))
        return []
