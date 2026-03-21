"""Playbook distillation prompt."""

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

## Process

1. Call `get_all_playbook_entries` to see existing rules
2. Call `search_episodes` with relevant keywords to find evidence
3. For interesting patterns, call `get_episode_frames` to verify against raw data
4. When you've confirmed a pattern, call `write_playbook_entry` to save it

## Quality rules

- Rules must be TRANSFERABLE — apply to anyone in similar situations
- Abstract away specific tools into situation types
- "boundary" field is critical: defines when behavior SWITCHES type
- Classify every rule as deep-work, strategic, recovery, avoidance, or displacement
- Minimum confidence 0.2 for single-episode, 0.6 for multi-episode
- Be aggressive — extract from single strong episodes. Aim for 8-15 rules.
- Every type should have at least 1 entry if evidence exists.

When done, output a brief summary of what you found."""
