"""Deterministic confidence time decay for playbook entries.

Layer 3 (garbage collection): entries that haven't received new evidence
decay toward a floor. Purely mathematical — no LLM involved.

Formula: effective = confidence * max(0.3, 1.0 - days_since_evidence / 90)
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from engine.infrastructure.pipeline.repository import (
    get_all_playbooks_for_decay, update_confidence,
    get_all_routines_for_decay, update_routine_confidence,
)

logger = logging.getLogger(__name__)

DECAY_DAYS = 90
DECAY_FLOOR = 0.3


def decay_confidence(session: Session) -> int:
    """Apply time-based confidence decay. Returns number of entries updated."""
    rows = get_all_playbooks_for_decay(session)
    updated = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for r in rows:
        last_evidence = r["last_evidence_at"]
        if not last_evidence:
            days_since = DECAY_DAYS
        else:
            try:
                last_dt = datetime.fromisoformat(last_evidence.replace("Z", "+00:00")).replace(tzinfo=None)
                days_since = (now - last_dt).total_seconds() / 86400
            except (ValueError, AttributeError):
                days_since = DECAY_DAYS

        if days_since <= 0:
            continue

        decay_factor = max(DECAY_FLOOR, 1.0 - days_since / DECAY_DAYS)
        original = r["confidence"]
        new_confidence = round(original * decay_factor, 4)

        if abs(new_confidence - original) < 0.0001:
            continue

        update_confidence(session, r["id"], new_confidence)
        updated += 1
        logger.debug("Decayed %s: %.4f → %.4f (%.0f days)", r["name"], original, new_confidence, days_since)

    if updated:
        logger.info("Decayed confidence for %d playbook entries", updated)

    return updated


def decay_routines(session: Session) -> int:
    """Apply time-based confidence decay to routines. Uses updated_at instead of last_evidence_at."""
    rows = get_all_routines_for_decay(session)
    updated = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for r in rows:
        updated_at = r["updated_at"]
        if not updated_at:
            days_since = DECAY_DAYS
        else:
            try:
                last_dt = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00")).replace(tzinfo=None)
                days_since = (now - last_dt).total_seconds() / 86400
            except (ValueError, AttributeError):
                days_since = DECAY_DAYS

        if days_since <= 0:
            continue

        decay_factor = max(DECAY_FLOOR, 1.0 - days_since / DECAY_DAYS)
        original = r["confidence"]
        new_confidence = round(original * decay_factor, 4)

        if abs(new_confidence - original) < 0.0001:
            continue

        update_routine_confidence(session, r["id"], new_confidence)
        updated += 1
        logger.debug("Decayed routine %s: %.4f → %.4f (%.0f days)", r["name"], original, new_confidence, days_since)

    if updated:
        logger.info("Decayed confidence for %d routines", updated)

    return updated
