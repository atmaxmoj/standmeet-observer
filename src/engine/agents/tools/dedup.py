"""Playbook deduplication tools for the GC agent."""

import sqlite3

from engine.llm.types import ToolDef
from engine.agents import repository as repo


def make_dedup_tools(conn: sqlite3.Connection) -> list[ToolDef]:
    """Create dedup tool definitions for the GC agent."""
    return [
        ToolDef(
            name="find_similar_pairs",
            description="Find pairs of playbook entries with high name similarity (Jaccard > 0.8).",
            input_schema={
                "type": "object",
                "properties": {"threshold": {"type": "number", "default": 0.8}},
                "required": [],
            },
            handler=lambda threshold=0.8: repo.find_similar_pairs(conn, threshold),
        ),
        ToolDef(
            name="merge_entries",
            description="Merge two playbook entries. Keeps keep_id, combines evidence, deletes the other.",
            input_schema={
                "type": "object",
                "properties": {
                    "keep_id": {"type": "integer"},
                    "remove_id": {"type": "integer"},
                },
                "required": ["keep_id", "remove_id"],
            },
            handler=lambda keep_id, remove_id: repo.merge_entries(conn, keep_id, remove_id),
        ),
    ]
