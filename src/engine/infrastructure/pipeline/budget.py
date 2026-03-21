"""Deterministic daily cost budget checking.

Layer 2 (architectural constraints): hard cap on daily LLM spend.
"""

import logging

from sqlalchemy.orm import Session

from engine.infrastructure.pipeline.repository import get_daily_spend, get_budget_cap

logger = logging.getLogger(__name__)


def check_daily_budget(session: Session, cap_usd: float) -> bool:
    """Return True if today's spend is under the cap, False otherwise."""
    actual_cap = get_budget_cap(session, cap_usd)
    spend = get_daily_spend(session)
    if spend >= actual_cap:
        logger.warning("Daily budget exceeded: $%.4f >= $%.2f cap", spend, actual_cap)
        return False
    return True
