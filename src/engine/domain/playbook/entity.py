"""Playbook entity — a reusable behavioral decision rule."""

from dataclasses import dataclass


VALID_MATURITIES = frozenset({"nascent", "developing", "mature", "mastered"})
VALID_TYPES = frozenset({"deep-work", "strategic", "recovery", "avoidance", "displacement"})


@dataclass
class Playbook:
    """A transferable behavioral rule extracted from episodes."""
    id: int = 0
    name: str = ""
    context: str = ""
    action: str = ""
    confidence: float = 0.0
    maturity: str = "nascent"
    evidence: str = "[]"
    last_evidence_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
