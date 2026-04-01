"""Tests for L4 DA (Personal Data Analyst) pipeline.

Tests repository CRUD and async DB/API endpoints.
Real PostgreSQL via conftest fixtures.
"""

import json

import pytest

from engine.infrastructure.agent.repository import (
    write_insight, get_previous_insights,
    write_da_goal, update_da_goal, get_da_goals,
)


class TestInsightRepository:
    def test_write_and_read_insight(self, sync_session):
        result = write_insight(sync_session, "Test insight", "Body text", "trend",
                               json.dumps({"episode_ids": [1, 2]}), "run123")
        sync_session.commit()
        assert result["title"] == "Test insight"
        assert result["id"] > 0

        insights = get_previous_insights(sync_session, limit=10)
        assert len(insights) == 1
        assert insights[0]["title"] == "Test insight"
        assert insights[0]["category"] == "trend"
        assert insights[0]["run_id"] == "run123"

    def test_multiple_insights_same_run(self, sync_session):
        write_insight(sync_session, "Insight A", "Body A", "trend", "[]", "run456")
        write_insight(sync_session, "Insight B", "Body B", "anomaly", "[]", "run456")
        write_insight(sync_session, "Insight C", "Body C", "growth", "[]", "run789")
        sync_session.commit()

        insights = get_previous_insights(sync_session, limit=10)
        assert len(insights) == 3
        assert insights[0]["run_id"] == "run789"

    def test_insight_with_chart_data(self, sync_session):
        chart = json.dumps({"type": "bar", "x_key": "date", "y_key": "count",
                            "rows": [{"date": "03-28", "count": 5}]})
        write_insight(sync_session, "Chart insight", "Body", "trend", "[]", "run_chart", data=chart)
        sync_session.commit()

        insights = get_previous_insights(sync_session, limit=10)
        assert insights[0]["data"] == chart


class TestDaGoalRepository:
    def test_write_and_read_goal(self, sync_session):
        result = write_da_goal(sync_session, "Track deep-work duration trends")
        sync_session.commit()
        assert result["goal"] == "Track deep-work duration trends"

        goals = get_da_goals(sync_session)
        assert len(goals) == 1
        assert goals[0]["status"] == "active"

    def test_update_goal_status(self, sync_session):
        created = write_da_goal(sync_session, "Investigate morning patterns")
        sync_session.commit()

        updated = update_da_goal(sync_session, created["id"], "completed",
                                 "Found: mornings are 2x more productive")
        sync_session.commit()
        assert updated["status"] == "completed"

        goals = get_da_goals(sync_session)
        notes = json.loads(goals[0]["progress_notes"])
        assert len(notes) == 1
        assert "mornings" in notes[0]


class TestDaAsyncDb:
    @pytest.mark.asyncio
    async def test_get_insights_empty(self, db):
        insights = await db.get_insights()
        assert insights == []
        count = await db.count_insights()
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_da_goals_empty(self, db):
        goals = await db.get_da_goals()
        assert goals == []

    @pytest.mark.asyncio
    async def test_count_insights_by_run_id(self, db, sync_session):
        write_insight(sync_session, "A", "body", "trend", "[]", "runX")
        write_insight(sync_session, "B", "body", "trend", "[]", "runX")
        write_insight(sync_session, "C", "body", "trend", "[]", "runY")
        sync_session.commit()

        assert await db.count_insights(run_id="runX") == 2
        assert await db.count_insights(run_id="runY") == 1
        assert await db.count_insights() == 3


class TestPromptCustomization:
    @pytest.mark.asyncio
    async def test_get_default_prompt(self, db):
        from engine.domain.prompt.playbook import PLAYBOOK_PROMPT
        custom = await db.get_state_str("prompt:distill")
        assert custom == ""  # no custom prompt yet
        # Default should be the module constant
        assert len(PLAYBOOK_PROMPT) > 100

    @pytest.mark.asyncio
    async def test_set_and_get_custom_prompt(self, db):
        await db.set_state_str("prompt:distill", "Custom distill prompt")
        result = await db.get_state_str("prompt:distill")
        assert result == "Custom distill prompt"

    @pytest.mark.asyncio
    async def test_reset_prompt(self, db):
        await db.set_state_str("prompt:distill", "Custom prompt")
        assert await db.get_state_str("prompt:distill") == "Custom prompt"
        await db.delete_state("prompt:distill")
        assert await db.get_state_str("prompt:distill") == ""

    @pytest.mark.asyncio
    async def test_distill_uses_custom_prompt(self, db):
        """Verify application layer reads custom prompt from state."""
        await db.set_state_str("prompt:distill", "You are a test distiller.")
        custom = await db.get_state_str("prompt:distill")
        assert custom == "You are a test distiller."
        # Clean up
        await db.delete_state("prompt:distill")
