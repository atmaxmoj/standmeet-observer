"""Episode entity — a task-level summary of user activity."""

from dataclasses import dataclass


@dataclass
class Episode:
    """A coherent unit of work extracted from observation frames."""
    id: int = 0
    summary: str = ""
    app_names: str = ""
    frame_count: int = 0
    started_at: str = ""
    ended_at: str = ""
    frame_id_min: int = 0
    frame_id_max: int = 0
    frame_source: str = ""
    created_at: str = ""
