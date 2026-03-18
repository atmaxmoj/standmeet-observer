"""Recall tools for the episode/distill agents.

Layer 1 (context engineering): gives agents tools to search episode history
and raw capture data.
"""

import sqlite3

from engine.llm.types import ToolDef
from engine.agents import repository as repo


def make_recall_tools(conn: sqlite3.Connection) -> list[ToolDef]:
    """Create recall tool definitions bound to a DB connection."""
    return [
        ToolDef(
            name="search_episodes",
            description="Search historical episode summaries by keyword.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword"},
                    "limit": {"type": "integer", "description": "Max results", "default": 10},
                },
                "required": ["query"],
            },
            handler=lambda query, limit=10: repo.search_episodes(conn, query, limit),
        ),
        ToolDef(
            name="get_recent_episodes",
            description="Get episodes from the last N hours.",
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "Hours to look back", "default": 24},
                },
                "required": [],
            },
            handler=lambda hours=24: repo.get_recent_episodes(conn, hours),
        ),
        ToolDef(
            name="get_episodes_by_app",
            description="Get episodes involving a specific application.",
            input_schema={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Application name"},
                },
                "required": ["app_name"],
            },
            handler=lambda app_name: repo.get_episodes_by_app(conn, app_name),
        ),
        ToolDef(
            name="get_recent_frames",
            description="Get recent screen capture frames (OCR text, app name, window name).",
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "default": 24},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
            handler=lambda hours=24, limit=50: repo.get_recent_frames(conn, hours, limit),
        ),
        ToolDef(
            name="get_frames_by_app",
            description="Get screen capture frames from a specific application.",
            input_schema={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 30},
                },
                "required": ["app_name"],
            },
            handler=lambda app_name, limit=30: repo.get_frames_by_app(conn, app_name, limit),
        ),
        ToolDef(
            name="get_recent_audio",
            description="Get recent audio transcriptions.",
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "default": 24},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
            handler=lambda hours=24, limit=50: repo.get_recent_audio(conn, hours, limit),
        ),
        ToolDef(
            name="get_recent_os_events",
            description="Get recent OS events (shell commands, browser URLs).",
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "default": 24},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
            handler=lambda hours=24, limit=50: repo.get_recent_os_events(conn, hours, limit),
        ),
        ToolDef(
            name="get_os_events_by_type",
            description="Get OS events filtered by type ('shell', 'url').",
            input_schema={
                "type": "object",
                "properties": {
                    "event_type": {"type": "string"},
                    "limit": {"type": "integer", "default": 30},
                },
                "required": ["event_type"],
            },
            handler=lambda event_type, limit=30: repo.get_os_events_by_type(conn, event_type, limit),
        ),
    ]
