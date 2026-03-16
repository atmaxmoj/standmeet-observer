"""Daily: Opus analyzes episodes + playbook entries → routines (composed workflows)."""

import json
import logging

from engine.config import MODEL_DEEP
from engine.db import DB
from engine.llm import LLMClient
from engine.pipeline.memory_file import write_routine

logger = logging.getLogger(__name__)

ROUTINE_PROMPT = """\
You are studying someone's daily work journal and their known behavioral patterns (Playbook) \
to identify **Routines** — recurring multi-step workflows they follow in specific situations.

A Routine is NOT a single habit (that's a Playbook entry). \
A Routine is a **composed sequence of steps** that this person repeats when a specific \
trigger/situation occurs. Think of it as their personal SOP (standard operating procedure).

## Existing Playbook entries (atomic behaviors)
{playbooks}

## Existing Routines
{routines}

## Today's episodes
{episodes}

## How to analyze

**Phase 1 — Sequence detection**
Look for multi-step sequences that repeat across episodes:
- Same trigger → same sequence of actions (≥2 occurrences across different days)
- Steps that always appear together in a specific order
- "Warm-up" sequences: what someone does before starting a task type

**Phase 2 — Compose from Playbook**
Each Routine should reference existing Playbook entries where applicable. \
The Routine adds the **ordering, branching, and context** that individual entries lack.

**Phase 3 — Output**
Output valid JSON array:
[
  {{
    "name": "kebab-case-name",
    "trigger": "When/what situation triggers this routine",
    "goal": "What this routine achieves",
    "steps": [
      "Step 1 description",
      "Step 2 description",
      "IF condition THEN step 3a ELSE step 3b",
      "Step 4 description"
    ],
    "uses": ["playbook-entry-name-1", "playbook-entry-name-2"],
    "confidence": 0.0,
    "maturity": "nascent|developing|mature"
  }}
]

## Rules
- A Routine must have ≥3 steps (otherwise it's just a Playbook entry)
- A Routine must be observed ≥2 times to be created
- Update existing Routines when you see confirming evidence (bump confidence) \
or variations (update steps to capture the common core)
- `uses` should list Playbook entry names that correspond to steps in this Routine
- Steps can include simple branching: "IF x THEN y ELSE z"
- Keep step descriptions concise — one line each

## Confidence & maturity rules
- confidence: 0.4 = seen twice, 0.6 = clear pattern (3-4 times), 0.8+ = very consistent
- nascent: < 3 observations
- developing: 3-5 observations
- mature: > 5 observations with consistent steps

Output ONLY the JSON array, nothing else."""


async def daily_routines(client: LLMClient, db: DB) -> int:
    """Run daily routine extraction: episodes + playbook → routines."""
    logger.info("starting routine extraction")
    episodes = await db.get_recent_episodes(days=1)
    if not episodes:
        logger.info("no episodes today, skipping routine extraction")
        return 0

    playbooks = await db.get_all_playbooks()
    existing_routines = await db.get_all_routines()

    logger.debug(
        "routine input: %d episodes, %d playbooks, %d existing routines",
        len(episodes), len(playbooks), len(existing_routines),
    )

    episodes_text = "\n\n".join(
        f"Episode #{e['id']} ({e['started_at']} to {e['ended_at']}):\n{e['summary']}"
        for e in episodes
    )

    playbooks_text = (
        "\n".join(
            f"- **{p['name']}** ({p['confidence']:.1f}): {p['context']} → {p['action']}"
            for p in playbooks
        )
        if playbooks
        else "(no playbook entries yet)"
    )

    routines_text = (
        "\n\n".join(
            f"- **{r['name']}** (confidence: {r['confidence']}, maturity: {r['maturity']})\n"
            f"  Trigger: {r['trigger']}\n"
            f"  Goal: {r['goal']}\n"
            f"  Steps: {r['steps']}\n"
            f"  Uses: {r['uses']}"
            for r in existing_routines
        )
        if existing_routines
        else "(none yet)"
    )

    try:
        prompt = ROUTINE_PROMPT.format(
            playbooks=playbooks_text,
            routines=routines_text,
            episodes=episodes_text,
        )
        resp = await client.acomplete(prompt, MODEL_DEEP)
        logger.debug("opus response: %d chars", len(resp.text))

        cost_usd = resp.cost_usd or 0
        await db.record_usage(
            model=MODEL_DEEP, layer="routines",
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost_usd=cost_usd,
        )
        await db.insert_pipeline_log(
            stage="routines",
            prompt=prompt, response=resp.text, model=MODEL_DEEP,
            input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
            cost_usd=cost_usd,
        )

        # Parse JSON
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        entries = json.loads(text)
        if not isinstance(entries, list):
            entries = [entries]
        logger.debug("opus returned %d routines", len(entries))

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

    except Exception:
        logger.exception("Routine extraction failed")
        return 0
