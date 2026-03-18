"""Playbook distillation prompt template."""

PLAYBOOK_PROMPT = """\
You are extracting reusable behavioral rules from someone's work journal.

Extract DECISION RULES that are TRANSFERABLE — they apply to anyone in similar situations, not just this person with these specific tools.

## Rule types (based on self-regulation theory)

**deep-work**: High-focus productive patterns — systematic approaches to solving problems, building features, debugging
**strategic**: Deliberate preparation or delay — investigating before acting, waiting for CI, reading docs before coding
**recovery**: Attention restoration — micro-breaks, task-switching during forced idle time (builds, deploys), deliberate rest
**avoidance**: Self-regulation failure — knows what to do but doesn't do it, anxiety-driven checking, displacement activity
**displacement**: Fake productivity — browsing settings, checking unrelated accounts, organizing instead of executing

## Abstraction level

Extract PATTERNS from specific instances. Abstract tool-specific details into transferable situation types.

WRONG: "When docker cp fails: mkdir -p first"
RIGHT: "When a file operation fails due to missing path: create the path structure first, then retry"

## Existing rules
{playbooks}

## Recent episodes
{episodes}

## Output

[
  {{
    "name": "kebab-case-name",
    "type": "deep-work|strategic|recovery|avoidance|displacement",
    "when": "Recognizable situation type (transferable)",
    "then": "Behavioral pattern (transferable)",
    "because": "The value or reasoning driving this",
    "boundary": "When this does NOT apply, or when it crosses into a different type (null if unknown)",
    "confidence": 0.0,
    "maturity": "nascent|developing|mature|mastered",
    "evidence": [1, 2, 3]
  }}
]

Rules:
- Be aggressive — extract from single episodes too (confidence 0.2). Aim for 8-15 rules.
- Every type should have at least 1 entry if evidence exists.
- "boundary" is critical: it defines when a behavior SWITCHES type (e.g., strategic investigation becomes avoidance when it extends indefinitely without execution).

Output ONLY the JSON array."""

# Backwards compat alias
DISTILL_PROMPT = PLAYBOOK_PROMPT
