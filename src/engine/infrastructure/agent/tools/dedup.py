"""Playbook deduplication tools for the GC agent."""

from sqlalchemy.orm import Session

from engine.infrastructure.llm.types import ToolDef
from engine.infrastructure.agent import repository as repo


def make_dedup_tools(session: Session) -> list[ToolDef]:
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
            handler=lambda threshold=0.8: repo.find_similar_pairs(session, threshold),
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
            handler=lambda keep_id, remove_id: repo.merge_entries(session, keep_id, remove_id),
        ),
    ]
