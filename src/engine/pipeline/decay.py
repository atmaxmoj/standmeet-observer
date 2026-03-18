"""Deterministic confidence time decay for playbook entries.

Layer 3 (garbage collection): entries that haven't received new evidence
decay toward a floor. Purely mathematical — no LLM involved.

Formula: effective = confidence * max(0.3, 1.0 - days_since_evidence / 90)
"""

import logging
import sqlite3
from datetime import datetime, timezone

from engine.pipeline.repository import get_all_playbooks_for_decay, update_confidence

logger = logging.getLogger(__name__)

DECAY_DAYS = 90
DECAY_FLOOR = 0.3


def decay_confidence(conn: sqlite3.Connection) -> int:
    """Apply time-based confidence decay. Returns number of entries updated."""
    rows = get_all_playbooks_for_decay(conn)
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

        update_confidence(conn, r["id"], new_confidence)
        updated += 1
        logger.debug("Decayed %s: %.4f → %.4f (%.0f days)", r["name"], original, new_confidence, days_since)

    if updated:
        conn.commit()
        logger.info("Decayed confidence for %d entries", updated)

    return updated
