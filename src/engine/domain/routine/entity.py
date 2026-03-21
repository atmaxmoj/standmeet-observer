"""Routine entity — a multi-step executable program composed from playbooks."""

from dataclasses import dataclass


@dataclass
class Routine:
    """A multi-step workflow composed from playbook entries."""
    id: int = 0
    name: str = ""
    trigger: str = ""
    goal: str = ""
    steps: str = "[]"
    uses: str = "[]"
    confidence: float = 0.0
    maturity: str = "nascent"
    created_at: str = ""
    updated_at: str = ""
