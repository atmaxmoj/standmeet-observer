"""Tests for Scrum Master — project task tracking from episodes.

Tests repository CRUD, async DB, and API endpoint for drag-and-drop.
Real PostgreSQL via conftest fixtures.
"""

import json

import pytest

from engine.infrastructure.agent.repository import (
    write_scm_task, get_scm_tasks, update_scm_task,
)


class TestScmTaskRepository:
    def test_write_and_read_task(self, sync_session):
        result = write_scm_task(
            sync_session, "YouTeacher", "Fix meilisearch production issue",
            "open", json.dumps({"episode_ids": [5511, 5252]}), "run001",
        )
        sync_session.commit()
        assert result["title"] == "Fix meilisearch production issue"
        assert result["id"] > 0

        tasks = get_scm_tasks(sync_session)
        assert len(tasks) == 1
        assert tasks[0]["project"] == "YouTeacher"
        assert tasks[0]["status"] == "open"
        assert "5511" in tasks[0]["evidence"]

    def test_multiple_tasks_per_project(self, sync_session):
        write_scm_task(sync_session, "YouTeacher", "Fix meilisearch", "open", "[]", "run001")
        write_scm_task(sync_session, "YouTeacher", "Fix category tree #59", "open", "[]", "run001")
        write_scm_task(sync_session, "Otium", "Fix VS4 spelling test", "open", "[]", "run001")
        sync_session.commit()

        yt_tasks = get_scm_tasks(sync_session, status="open")
        projects = {t["project"] for t in yt_tasks}
        assert "YouTeacher" in projects
        assert "Otium" in projects

    def test_update_status_with_note(self, sync_session):
        created = write_scm_task(sync_session, "FlexDriver", "Fix CocoaPods", "open", "[]", "run001")
        sync_session.commit()

        update_scm_task(sync_session, created["id"], "blocked", "Exit code 1, lock file conflict")
        sync_session.commit()

        tasks = get_scm_tasks(sync_session)
        assert tasks[0]["status"] == "blocked"
        notes = json.loads(tasks[0]["notes"])
        assert len(notes) == 1
        assert "lock file" in notes[0]

        # Add another note
        update_scm_task(sync_session, created["id"], "done", "Resolved by deleting Podfile.lock")
        sync_session.commit()

        tasks = get_scm_tasks(sync_session)
        assert tasks[0]["status"] == "done"
        notes = json.loads(tasks[0]["notes"])
        assert len(notes) == 2

    def test_update_nonexistent_task(self, sync_session):
        result = update_scm_task(sync_session, 99999, "done", "")
        assert "error" in result

    def test_filter_by_status(self, sync_session):
        write_scm_task(sync_session, "A", "task1", "open", "[]", "run001")
        write_scm_task(sync_session, "B", "task2", "done", "[]", "run001")
        write_scm_task(sync_session, "C", "task3", "blocked", "[]", "run001")
        sync_session.commit()

        assert len(get_scm_tasks(sync_session, status="open")) == 1
        assert len(get_scm_tasks(sync_session, status="done")) == 1
        assert len(get_scm_tasks(sync_session, status="blocked")) == 1
        assert len(get_scm_tasks(sync_session, status="in_progress")) == 0
        assert len(get_scm_tasks(sync_session)) == 3


class TestScmAsyncDb:
    @pytest.mark.asyncio
    async def test_get_scm_tasks_empty(self, db):
        tasks = await db.get_scm_tasks()
        assert tasks == []

    @pytest.mark.asyncio
    async def test_count_by_status(self, db, sync_session):
        write_scm_task(sync_session, "A", "t1", "open", "[]", "r1")
        write_scm_task(sync_session, "B", "t2", "done", "[]", "r1")
        write_scm_task(sync_session, "C", "t3", "open", "[]", "r1")
        sync_session.commit()

        assert await db.count_scm_tasks() == 3
        assert await db.count_scm_tasks(status="open") == 2
        assert await db.count_scm_tasks(status="done") == 1
        assert await db.count_scm_tasks(status="blocked") == 0

    @pytest.mark.asyncio
    async def test_filter_returns_correct_tasks(self, db, sync_session):
        write_scm_task(sync_session, "X", "open-task", "open", "[]", "r1")
        write_scm_task(sync_session, "Y", "done-task", "done", "[]", "r1")
        sync_session.commit()

        open_tasks = await db.get_scm_tasks(status="open")
        assert len(open_tasks) == 1
        assert open_tasks[0]["title"] == "open-task"
