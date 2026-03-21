"""Use case: extract episodes from observation frames."""

import json
import logging

from engine.config import MODEL_FAST, Settings
from engine.domain.observation.entity import Frame
from engine.domain.prompt.episode import EPISODE_PROMPT
from engine.infrastructure.pipeline.stages.extract import build_context, extract_episodes
from engine.infrastructure.persistence.db import DB

logger = logging.getLogger(__name__)


async def process_window(
    settings: Settings,
    db: DB,
    frames: list[Frame],
    prompt: str = EPISODE_PROMPT,
) -> list[int]:
    """Full pipeline: frames → context → LLM → parse → save to DB.

    Returns list of created episode IDs.
    """
    if not frames:
        return []

    from engine.infrastructure.agent.service import AgentService

    context = build_context(frames)
    agent = AgentService(settings)

    try:
        tasks, resp = await extract_episodes(agent, context, prompt=prompt)

        cost_usd = resp.cost_usd or 0
        await db.record_usage(
            model=MODEL_FAST, layer="episode",
            input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
            cost_usd=cost_usd,
        )
        await db.insert_pipeline_log(
            stage="episode", prompt=prompt.format(context=context), response=resp.text,
            model=MODEL_FAST, input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens, cost_usd=cost_usd,
        )

        frame_id_min = min(f.id for f in frames)
        frame_id_max = max(f.id for f in frames)
        frame_source = ",".join(sorted({f.source for f in frames}))

        episode_ids = []
        for task in tasks:
            summary = json.dumps({
                "summary": task.get("summary", ""),
                "method": task.get("method", ""),
                "turning_points": task.get("turning_points", []),
                "avoidance": task.get("avoidance", []),
                "under_pressure": task.get("under_pressure", False),
            }, ensure_ascii=False)
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

        return episode_ids

    except Exception:
        logger.exception("Failed to process window (%d frames)", len(frames))
        return []
