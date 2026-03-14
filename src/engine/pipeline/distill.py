"""Weekly: Opus analyzes episodes and generates/updates playbook entries."""

import json
import logging

import anthropic

from engine.config import MODEL_WEEKLY, TOKEN_COSTS
from engine.db import DB

logger = logging.getLogger(__name__)

DISTILL_PROMPT = """\
You are a master craftsman studying an apprentice's work journal to understand \
how they think, decide, and act — not what they did, but how and why.

Your goal: distill recurring behavioral patterns into Playbook entries. \
A Playbook entry is a 情境-行動對 (situation-action pair) — not a description \
of what someone is, but a recipe for reproducing how they behave in a specific context.

## Existing Playbook
{playbooks}

## This week's episodes
{episodes}

## How to analyze

**Phase 1 — Pattern detection**
Scan all episodes. Look for:
- Recurring sequences: same type of situation → same approach (≥2 occurrences)
- Turning points: moments of correction, choice, or hesitation that reveal preference
- Avoidance patterns: tools/features/steps available but consistently NOT used — \
"never" reveals more than "always"
- Pressure-revealed behavior: what they do under time pressure vs normal. \
Habits dropped under pressure = learned discipline. Habits kept = internalized.

**Phase 2 — Cross-validation**
For each candidate pattern, ask:
- Does this appear across different apps/contexts? (cross-domain = high confidence)
- Are there counter-examples this week? If so, what was different? (boundary conditions)
- Does this confirm, contradict, or extend an existing Playbook entry?

**Phase 3 — Output**
For each pattern, produce a Playbook entry in 情境-行動對 format:

Output valid JSON array:
[
  {{
    "name": "kebab-case-name",
    "context": "The specific situation/trigger (be precise: WHEN does this apply?)",
    "intuition": "Their first/instinctive reaction in this context",
    "action": "What they consistently do (the reproducible sequence)",
    "why": "Inferred reason — what value or constraint drives this choice",
    "counterexample": "Any episode where they did NOT follow this pattern, and why (null if none)",
    "confidence": 0.0,
    "maturity": "nascent|developing|mature|mastered",
    "evidence": [1, 2, 3]
  }}
]

## Confidence & maturity rules
- confidence: 0.3 = weak signal (2 episodes), 0.6 = clear pattern (3-4), 0.8+ = very consistent (5+)
- nascent: < 3 evidence episodes or confidence < 0.6
- developing: 3-8 evidence, confidence mostly 0.6-0.8
- mature: > 8 evidence, confidence mostly > 0.8
- mastered: mature + has counterexamples with identified boundary conditions + survives pressure

## Rules
- Patterns, not one-offs. Minimum 2 episodes as evidence.
- Update existing entries when you see confirming or contradicting evidence. \
Increment confidence for confirmation, note counterexamples for contradiction.
- Create new entries only for clearly recurring patterns.
- If an episode shows behavior UNDER PRESSURE (marked under_pressure=true), \
compare it to the normal pattern. This is gold — it shows what's truly internalized.
- Look for cross-domain patterns: if someone does the same thing across debugging, \
writing, and communication, that's a value, not just a habit.

Output ONLY the JSON array, nothing else."""


async def weekly_distill(
    client: anthropic.AsyncAnthropic,
    db: DB,
) -> int:
    """
    Run weekly distillation: episodes → playbook entries.
    Returns number of playbook entries created/updated.
    """
    logger.info("starting weekly distillation")
    episodes = await db.get_recent_episodes(days=7)
    if not episodes:
        logger.info("no episodes in the past week, skipping distillation")
        return 0

    existing = await db.get_all_playbooks()
    logger.debug(
        "distillation input: %d episodes, %d existing playbooks",
        len(episodes), len(existing),
    )

    episodes_text = "\n\n".join(
        f"Episode #{e['id']} ({e['started_at']} to {e['ended_at']}):\n{e['summary']}"
        for e in episodes
    )

    playbooks_text = (
        "\n\n".join(
            f"- **{p['name']}** (confidence: {p['confidence']}, maturity: {p.get('maturity', 'nascent')})\n"
            f"  Context: {p['context']}\n"
            f"  Action: {p['action']}\n"
            f"  Evidence: {p['evidence']}"
            for p in existing
        )
        if existing
        else "(none yet — this is the first distillation)"
    )

    try:
        response = await client.messages.create(
            model=MODEL_WEEKLY,  # Opus — expensive, runs once/week
            max_tokens=8192,
            messages=[
                {
                    "role": "user",
                    "content": DISTILL_PROMPT.format(
                        playbooks=playbooks_text, episodes=episodes_text
                    ),
                }
            ],
        )
        raw = response.content[0].text
        usage = response.usage
        logger.debug("opus response: %d chars, usage: %s", len(raw), usage)

        # Record token usage
        costs = TOKEN_COSTS.get(MODEL_WEEKLY, {"input": 0, "output": 0})
        cost_usd = usage.input_tokens * costs["input"] + usage.output_tokens * costs["output"]
        await db.record_usage(
            model=MODEL_WEEKLY,
            layer="distill",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd,
        )
        logger.debug("recorded usage: model=%s cost=$%.6f", MODEL_WEEKLY, cost_usd)

        # Parse JSON (handle markdown code fences)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        entries = json.loads(text)
        if not isinstance(entries, list):
            entries = [entries]
        logger.debug("opus returned %d playbook entries", len(entries))

        count = 0
        for entry in entries:
            # Store the rich 情境-行動對 as JSON in the action field
            rich_action = json.dumps(
                {
                    "intuition": entry.get("intuition", ""),
                    "action": entry.get("action", ""),
                    "why": entry.get("why", ""),
                    "counterexample": entry.get("counterexample"),
                },
                ensure_ascii=False,
            )
            await db.upsert_playbook(
                name=entry["name"],
                context=entry.get("context", ""),
                action=rich_action,
                confidence=entry.get("confidence", 0.5),
                evidence=json.dumps(entry.get("evidence", [])),
                maturity=entry.get("maturity", "nascent"),
            )
            count += 1

        logger.info(
            "Weekly distillation: %d entries from %d episodes",
            count,
            len(episodes),
        )
        return count

    except Exception:
        logger.exception("Weekly distillation failed")
        return 0
