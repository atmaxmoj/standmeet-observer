"""Playbook validation — domain rules for playbook entries."""

import re

from engine.domain.playbook.entity import VALID_MATURITIES

KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


class PlaybookValidationError(Exception):
    """Raised when a playbook entry fails validation."""
    pass


def validate_playbook_entry(entry: dict, index: int = 0) -> dict:
    """Validate and normalize a single playbook entry dict.

    Raises PlaybookValidationError on failure.
    Returns the (possibly modified) entry.
    """
    if "name" not in entry:
        raise PlaybookValidationError(f"Entry {index}: missing required field 'name'")

    if not KEBAB_RE.match(entry["name"]):
        raise PlaybookValidationError(
            f"Entry {index}: name '{entry['name']}' is not kebab-case "
            f"(expected pattern: lowercase-words-joined-by-hyphens)"
        )

    confidence = entry.get("confidence", 0.5)
    entry["confidence"] = max(0.0, min(1.0, float(confidence)))

    maturity = entry.get("maturity", "nascent")
    if maturity not in VALID_MATURITIES:
        raise PlaybookValidationError(
            f"Entry {index}: maturity '{maturity}' not in {VALID_MATURITIES}"
        )

    evidence = entry.get("evidence", [])
    if not isinstance(evidence, list):
        raise PlaybookValidationError(
            f"Entry {index}: 'evidence' must be a list of int IDs, "
            f"got {type(evidence).__name__}"
        )

    return entry
