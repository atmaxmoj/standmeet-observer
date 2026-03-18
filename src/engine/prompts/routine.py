"""Routine composition prompt template."""

ROUTINE_PROMPT = """\
You are composing executable PROGRAMS from behavioral rules and episodes.

Your output must be good enough that an AI agent could read it and autonomously execute the workflow end-to-end without human intervention. Think of each routine as a program.md for an autonomous agent.

## Routine types

**deep-work**: Systematic multi-step workflows with clear inputs, outputs, and verification at each step. An agent COULD run this.
**strategic**: Preparation/investigation workflows that produce a decision or plan. Agent could run this to gather context.
**recovery**: NOT a routine — recovery behaviors are atomic, not multi-step. Do NOT create recovery routines.
**avoidance**: Recurring failure loops. Document the ACTUAL behavior (not the ideal). Useful for self-awareness, NOT for agent execution.
**displacement**: Fake-productivity spirals. Document the ACTUAL behavior. NOT for agent execution.

## Quality bar: program.md

For deep-work and strategic routines, every step must be:
- **Concrete**: "Run the full test suite" not "verify things work"
- **Observable**: an agent can tell when the step is done
- **Conditional**: IF/ELSE for decision points, not vague "handle as needed"
- **Verifiable**: each step has a success/failure signal

Bad: "Review the code and make sure it's good"
Good: "Run linter. IF violations > 0 THEN apply auto-fix and re-run. IF still failing THEN fix top 3 by hand. Verify: linter exits 0."

For avoidance/displacement routines, describe the ACTUAL loop pattern so the human can recognize when they're in it.

## Existing Playbook entries (atomic behaviors)
{playbooks}

## Existing Routines
{routines}

## Today's episodes
{episodes}

## Output

[
  {{
    "name": "kebab-case-name",
    "type": "deep-work|strategic|avoidance|displacement",
    "trigger": "Recognizable situation that starts this routine",
    "goal": "What this achieves (deep-work/strategic) or what it avoids (avoidance/displacement)",
    "steps": [
      "Step 1: concrete action. Verify: observable signal.",
      "Step 2: concrete action.",
      "IF condition THEN step 3a ELSE step 3b",
      "Step 4: concrete action. Verify: observable signal."
    ],
    "exit_condition": "How to know the routine is DONE (or how to break out of an avoidance loop)",
    "uses": ["playbook-entry-name-1"],
    "confidence": 0.0,
    "maturity": "nascent|developing|mature"
  }}
]

Rules:
- ≥3 steps per routine
- ≥2 observations to create
- deep-work routines MUST have verification steps — if an agent can't verify success, it's not a program
- avoidance/displacement routines MUST have an exit_condition showing how to break the loop
- Do NOT create recovery routines (recovery is atomic, not a workflow)
- `uses` references playbook entry names

Output ONLY the JSON array."""
