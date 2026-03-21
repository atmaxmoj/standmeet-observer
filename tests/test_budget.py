"""Tests for daily budget checking."""

import pytest
from sqlalchemy import text
from engine.infrastructure.persistence.models import TokenUsage, State
from engine.infrastructure.pipeline.budget import check_daily_budget
from engine.infrastructure.pipeline.repository import get_daily_spend, get_budget_cap


@pytest.fixture
def session(sync_session):
    return sync_session


class TestCheckDailyBudget:
    def test_no_usage_passes(self, session):
        assert check_daily_budget(session, cap_usd=2.0) is True

    def test_under_cap_passes(self, session):
        session.add(TokenUsage(model="haiku", layer="episode", input_tokens=100, output_tokens=50, cost_usd=0.50))
        session.commit()
        assert check_daily_budget(session, cap_usd=2.0) is True

    def test_over_cap_rejected(self, session):
        session.add(TokenUsage(model="opus", layer="distill", input_tokens=1000, output_tokens=500, cost_usd=2.50))
        session.commit()
        assert check_daily_budget(session, cap_usd=2.0) is False

    def test_exactly_at_cap_rejected(self, session):
        session.add(TokenUsage(model="opus", layer="distill", input_tokens=1000, output_tokens=500, cost_usd=2.00))
        session.commit()
        assert check_daily_budget(session, cap_usd=2.0) is False

    def test_multiple_entries_sum(self, session):
        for cost in [0.5, 0.6, 0.7]:
            session.add(TokenUsage(model="haiku", layer="episode", input_tokens=100, output_tokens=50, cost_usd=cost))
        session.commit()
        # Total = 1.8, under 2.0
        assert check_daily_budget(session, cap_usd=2.0) is True
        # Total = 1.8, over 1.5
        assert check_daily_budget(session, cap_usd=1.5) is False

    def test_old_usage_not_counted(self, session):
        # Insert old record (2 days ago) using raw SQL for datetime manipulation
        session.execute(
            text("INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd, created_at) "
                 "VALUES (:model, :layer, :input_tokens, :output_tokens, :cost_usd, NOW() - INTERVAL '2 days')"),
            {"model": "opus", "layer": "distill", "input_tokens": 1000, "output_tokens": 500, "cost_usd": 5.00},
        )
        session.commit()
        assert check_daily_budget(session, cap_usd=2.0) is True


class TestGetDailySpend:
    def test_no_usage(self, session):
        assert get_daily_spend(session) == 0.0

    def test_sums_today(self, session):
        session.add(TokenUsage(model="haiku", layer="episode", input_tokens=100, output_tokens=50, cost_usd=0.75))
        session.add(TokenUsage(model="opus", layer="distill", input_tokens=200, output_tokens=100, cost_usd=1.25))
        session.commit()
        assert get_daily_spend(session) == pytest.approx(2.0)

    def test_excludes_old(self, session):
        session.add(TokenUsage(model="haiku", layer="episode", input_tokens=100, output_tokens=50, cost_usd=0.50))
        session.execute(
            text("INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd, created_at) "
                 "VALUES (:model, :layer, :input_tokens, :output_tokens, :cost_usd, NOW() - INTERVAL '2 days')"),
            {"model": "opus", "layer": "distill", "input_tokens": 200, "output_tokens": 100, "cost_usd": 3.00},
        )
        session.commit()
        assert get_daily_spend(session) == pytest.approx(0.50)


class TestGetBudgetCap:
    def test_default_when_no_state(self, session):
        assert get_budget_cap(session, 2.0) == 2.0

    def test_reads_from_state_table(self, session):
        session.add(State(key="daily_cost_cap_usd", value="5.0"))
        session.commit()
        assert get_budget_cap(session, 2.0) == 5.0

    def test_check_budget_uses_db_cap(self, session):
        """check_daily_budget should use DB cap over the passed default."""
        session.add(State(key="daily_cost_cap_usd", value="10.0"))
        session.add(TokenUsage(model="opus", layer="distill", input_tokens=1000, output_tokens=500, cost_usd=5.0))
        session.commit()
        # Default cap=2.0 would reject, but DB cap=10.0 allows
        assert check_daily_budget(session, cap_usd=2.0) is True

    def test_check_budget_falls_back_to_default(self, session):
        """No DB state -> use passed default."""
        session.add(TokenUsage(model="opus", layer="distill", input_tokens=1000, output_tokens=500, cost_usd=5.0))
        session.commit()
        assert check_daily_budget(session, cap_usd=2.0) is False


class TestSyncDBWithPsycopgConn:
    """SyncDB must accept any DBAPI connection, not just sqlite3.Connection."""

    def test_accepts_sqlalchemy_session(self, sync_session):
        """SyncDB should work with a SQLAlchemy Session."""
        from engine.infrastructure.persistence.sync_db import SyncDB

        db = SyncDB(sync_session)
        assert db.session is not None
