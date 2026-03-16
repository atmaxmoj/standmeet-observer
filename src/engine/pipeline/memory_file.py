"""Write playbook entries and routines to markdown files.

Memory files are the readable, auditable source of truth.
DB is the index; files are what a human (or agent) reads.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("/data/memory")


def _playbooks_dir() -> Path:
    d = MEMORY_DIR / "playbooks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _routines_dir() -> Path:
    d = MEMORY_DIR / "routines"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_action(raw: str) -> dict:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"action": raw}


def write_playbook(entry: dict) -> Path:
    """Write a playbook entry to a markdown file. Returns the file path."""
    name = entry["name"]
    path = _playbooks_dir() / f"{name}.md"
    action_data = _parse_action(entry.get("action", ""))

    lines = [
        f"# {name}",
        "",
        f"**Confidence:** {entry.get('confidence', 0):.0%}  ",
        f"**Maturity:** {entry.get('maturity', 'nascent')}  ",
        f"**Updated:** {entry.get('updated_at', 'unknown')}",
        "",
        "## Context",
        "",
        entry.get("context", ""),
        "",
        "## Action",
        "",
        action_data.get("action", str(action_data)),
        "",
    ]

    if action_data.get("intuition"):
        lines += ["## Intuition", "", action_data["intuition"], ""]
    if action_data.get("why"):
        lines += ["## Why", "", action_data["why"], ""]
    if action_data.get("counterexample"):
        lines += ["## Counterexample", "", action_data["counterexample"], ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.debug("wrote playbook file: %s", path)
    return path


def write_routine(entry: dict) -> Path:
    """Write a routine to a markdown file. Returns the file path."""
    name = entry["name"]
    path = _routines_dir() / f"{name}.md"

    steps = entry.get("steps", "[]")
    if isinstance(steps, str):
        steps = json.loads(steps)
    uses = entry.get("uses", "[]")
    if isinstance(uses, str):
        uses = json.loads(uses)

    lines = [
        f"# {name}",
        "",
        f"**Confidence:** {entry.get('confidence', 0):.0%}  ",
        f"**Maturity:** {entry.get('maturity', 'nascent')}  ",
        f"**Updated:** {entry.get('updated_at', 'unknown')}",
        "",
        "## Trigger",
        "",
        entry.get("trigger", ""),
        "",
        "## Goal",
        "",
        entry.get("goal", ""),
        "",
        "## Steps",
        "",
    ]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
    lines.append("")

    if uses:
        lines += ["## Uses", ""]
        for u in uses:
            lines.append(f"- `{u}`")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.debug("wrote routine file: %s", path)
    return path


def delete_playbook(name: str) -> bool:
    """Delete a playbook markdown file. Returns True if existed."""
    path = _playbooks_dir() / f"{name}.md"
    if path.exists():
        path.unlink()
        return True
    return False
