"""Tests for engine API: ingest endpoints, query endpoints, frame image serving, pipeline control."""

import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport

from engine.api.routes import router
from fastapi import FastAPI


@pytest.fixture
def app(db):
    """Create a minimal FastAPI app with the router and test DB."""
    test_app = FastAPI()
    test_app.include_router(router)

    test_app.state.db = db
    test_app.state.anthropic = MagicMock()
    test_app.state.settings = MagicMock()
    test_app.state.settings.frames_base_dir = "/tmp/frames"

    return test_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestIngestFrame:
    async def test_ingest_frame(self, client, db):
        resp = await client.post("/ingest/frame", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
            "app_name": "Terminal",
            "window_name": "zsh",
            "text": "$ git status",
            "display_id": 1,
            "image_hash": "abc123",
            "image_path": "frames/2026-03-14/100000_d1.webp",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1

        # Verify in DB
        frames, total = await db.get_frames()
        assert total == 1
        assert frames[0]["app_name"] == "Terminal"

    async def test_ingest_frame_minimal(self, client):
        resp = await client.post("/ingest/frame", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    async def test_ingest_frame_missing_timestamp(self, client):
        resp = await client.post("/ingest/frame", json={
            "app_name": "Terminal",
        })
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestIngestAudio:
    async def test_ingest_audio(self, client, db):
        resp = await client.post("/ingest/audio", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
            "duration_seconds": 5.2,
            "text": "hello world",
            "language": "en",
            "source": "mic",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

        audio, total = await db.get_audio_frames()
        assert total == 1
        assert audio[0]["text"] == "hello world"


@pytest.mark.asyncio
class TestIngestOsEvent:
    async def test_ingest_os_event(self, client, db):
        resp = await client.post("/ingest/os-event", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
            "event_type": "shell_command",
            "source": "zsh",
            "data": "git push origin main",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

        events, total = await db.get_os_events()
        assert total == 1
        assert events[0]["data"] == "git push origin main"

    async def test_ingest_os_event_missing_type(self, client):
        resp = await client.post("/ingest/os-event", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
            "source": "zsh",
        })
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestQueryFrames:
    async def test_list_frames(self, client, db):
        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="VSCode", window_name="editor",
            text="code", display_id=1, image_hash="h1",
        )
        resp = await client.get("/capture/frames?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["frames"]) == 1
        assert data["frames"][0]["app_name"] == "VSCode"

    async def test_empty_frames(self, client):
        resp = await client.get("/capture/frames")
        assert resp.status_code == 200
        assert resp.json() == {"frames": [], "total": 0}


@pytest.mark.asyncio
class TestQueryAudio:
    async def test_list_audio(self, client, db):
        await db.insert_audio_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            duration_seconds=3.0, text="hi", language="en",
        )
        resp = await client.get("/capture/audio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1


@pytest.mark.asyncio
class TestQueryOsEvents:
    async def test_list_os_events(self, client, db):
        await db.insert_os_event(
            timestamp="2026-03-14T10:00:00+00:00",
            event_type="shell_command", source="zsh", data="ls -la",
        )
        await db.insert_os_event(
            timestamp="2026-03-14T10:01:00+00:00",
            event_type="browser_url", source="chrome", data="https://x.com",
        )
        resp = await client.get("/capture/os-events")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_filter_by_type(self, client, db):
        await db.insert_os_event(
            timestamp="2026-03-14T10:00:00+00:00",
            event_type="shell_command", source="zsh", data="ls",
        )
        await db.insert_os_event(
            timestamp="2026-03-14T10:01:00+00:00",
            event_type="browser_url", source="chrome", data="https://x.com",
        )
        resp = await client.get("/capture/os-events?event_type=browser_url")
        data = resp.json()
        assert data["total"] == 1
        assert data["events"][0]["source"] == "chrome"


@pytest.mark.asyncio
class TestFrameImage:
    async def test_no_image(self, client, db):
        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="App", window_name="win", text="t",
            display_id=1, image_hash="h",
        )
        resp = await client.get("/capture/frames/1/image")
        assert resp.status_code == 200
        assert resp.json() == {"error": "no image"}

    async def test_image_file_not_found(self, client, db):
        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="App", window_name="win", text="t",
            display_id=1, image_hash="h",
            image_path="frames/2026-03-14/missing.webp",
        )
        resp = await client.get("/capture/frames/1/image")
        assert resp.status_code == 200
        assert resp.json() == {"error": "file not found"}

    async def test_image_served(self, client, db, tmp_path):
        # Create a fake webp file
        frames_dir = tmp_path / "frames" / "2026-03-14"
        frames_dir.mkdir(parents=True)
        img_file = frames_dir / "100000_d1.webp"
        img_file.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")  # minimal webp-like header

        # Update settings to point to tmp_path
        client._transport.app.state.settings.frames_base_dir = str(tmp_path / "frames")

        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="App", window_name="win", text="t",
            display_id=1, image_hash="h",
            image_path="frames/2026-03-14/100000_d1.webp",
        )
        resp = await client.get("/capture/frames/1/image")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"

    async def test_nonexistent_frame(self, client):
        resp = await client.get("/capture/frames/999/image")
        assert resp.status_code == 200
        assert resp.json() == {"error": "no image"}


@pytest.mark.asyncio
class TestEngineStatus:
    async def test_status(self, client, db):
        resp = await client.get("/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["episode_count"] == 0
        assert data["playbook_count"] == 0

    async def test_capture_alive_false_when_no_frames(self, client, db):
        resp = await client.get("/engine/status")
        assert resp.json()["capture_alive"] is False
        assert resp.json()["last_frame_at"] is None

    async def test_capture_alive_true_with_recent_frame(self, client, db):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await db.insert_frame(
            timestamp=now, app_name="App", window_name="w",
            text="t", display_id=1, image_hash="h",
        )
        resp = await client.get("/engine/status")
        assert resp.json()["capture_alive"] is True

    async def test_capture_alive_false_with_old_frame(self, client, db):
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        await db.insert_frame(
            timestamp=old, app_name="App", window_name="w",
            text="t", display_id=1, image_hash="h",
        )
        resp = await client.get("/engine/status")
        assert resp.json()["capture_alive"] is False


@pytest.mark.asyncio
class TestEngineUsage:
    async def test_usage_empty(self, client):
        resp = await client.get("/engine/usage?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 0

    async def test_usage_with_data(self, client, db):
        await db.record_usage(
            model="haiku", layer="task",
            input_tokens=1000, output_tokens=500, cost_usd=0.01,
        )
        resp = await client.get("/engine/usage?days=7")
        data = resp.json()
        assert data["total_calls"] == 1
        assert data["total_input_tokens"] == 1000


@pytest.mark.asyncio
class TestEpisodes:
    async def test_list_episodes(self, client, db):
        await db.insert_episode(
            summary="Worked on git", app_names="Terminal",
            frame_count=10,
            started_at="2026-03-14T10:00:00", ended_at="2026-03-14T10:30:00",
        )
        resp = await client.get("/memory/episodes/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["episodes"][0]["summary"] == "Worked on git"


@pytest.mark.asyncio
class TestPlaybooks:
    async def test_list_playbooks(self, client, db):
        await db.upsert_playbook(
            name="deploy", context="c", action="a",
            confidence=0.9, evidence="[]",
        )
        resp = await client.get("/memory/playbooks/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["playbooks"]) == 1


@pytest.mark.asyncio
class TestPipelineControl:
    async def test_pipeline_status_default(self, client):
        resp = await client.get("/engine/pipeline")
        assert resp.status_code == 200
        assert resp.json()["paused"] is False

    async def test_pause_and_resume(self, client):
        resp = await client.post("/engine/pipeline/pause")
        assert resp.json()["paused"] is True

        resp = await client.get("/engine/pipeline")
        assert resp.json()["paused"] is True

        resp = await client.post("/engine/pipeline/resume")
        assert resp.json()["paused"] is False

        resp = await client.get("/engine/pipeline")
        assert resp.json()["paused"] is False

    async def test_ingest_rejected_when_paused(self, client, db):
        await client.post("/engine/pipeline/pause")

        # All three ingest endpoints should reject data
        resp = await client.post("/ingest/frame", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
        })
        assert resp.json()["id"] is None
        assert resp.json()["paused"] is True

        resp = await client.post("/ingest/audio", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
            "duration_seconds": 5.0,
            "text": "hello",
        })
        assert resp.json()["id"] is None

        resp = await client.post("/ingest/os-event", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
            "event_type": "shell_command",
            "source": "zsh",
            "data": "ls",
        })
        assert resp.json()["id"] is None

        # DB should be empty
        frames, total = await db.get_frames()
        assert total == 0

    async def test_ingest_works_after_resume(self, client, db):
        await client.post("/engine/pipeline/pause")
        await client.post("/engine/pipeline/resume")

        resp = await client.post("/ingest/frame", json={
            "timestamp": "2026-03-14T10:00:00+00:00",
        })
        assert resp.json()["id"] == 1


@pytest.mark.asyncio
class TestPipelineLogs:
    async def test_empty_logs(self, client):
        resp = await client.get("/engine/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["logs"] == []
        assert data["total"] == 0

    async def test_logs_returned(self, client, db):
        await db.insert_pipeline_log(
            stage="episode",
            prompt="test prompt",
            response="test response",
            model="haiku",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )
        resp = await client.get("/engine/logs")
        data = resp.json()
        assert data["total"] == 1
        log = data["logs"][0]
        assert log["stage"] == "episode"
        assert log["prompt"] == "test prompt"
        assert log["response"] == "test response"
        assert log["model"] == "haiku"
        assert log["input_tokens"] == 100
        assert log["cost_usd"] == 0.001

    async def test_logs_pagination(self, client, db):
        for i in range(5):
            await db.insert_pipeline_log(
                stage="episode", prompt=f"p{i}", response=f"r{i}",
                model="haiku",
            )
        resp = await client.get("/engine/logs?limit=2&offset=0")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["logs"]) == 2
        # Most recent first
        assert data["logs"][0]["prompt"] == "p4"

    async def test_distill_stage_logged(self, client, db):
        await db.insert_pipeline_log(
            stage="distill",
            prompt="distill prompt",
            response="distill response",
            model="opus",
            input_tokens=5000,
            output_tokens=2000,
            cost_usd=0.05,
        )
        resp = await client.get("/engine/logs")
        assert resp.json()["logs"][0]["stage"] == "distill"


@pytest.mark.asyncio
class TestBatchDelete:
    async def test_delete_frames(self, client, db):
        id1 = await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="App", window_name="w", text="t",
            display_id=1, image_hash="h1",
        )
        id2 = await db.insert_frame(
            timestamp="2026-03-14T10:01:00+00:00",
            app_name="App", window_name="w", text="t",
            display_id=1, image_hash="h2",
        )
        resp = await client.post("/batch/delete", json={"table": "frames", "ids": [id1, id2]})
        assert resp.json()["deleted"] == 2
        _, total = await db.get_frames()
        assert total == 0

    async def test_delete_episodes(self, client, db):
        eid = await db.insert_episode(
            summary="test", app_names="App", frame_count=5,
            started_at="2026-03-14T10:00:00", ended_at="2026-03-14T10:30:00",
        )
        resp = await client.post("/batch/delete", json={"table": "episodes", "ids": [eid]})
        assert resp.json()["deleted"] == 1

    async def test_delete_invalid_table(self, client):
        resp = await client.post("/batch/delete", json={"table": "users", "ids": [1]})
        assert resp.json()["deleted"] == 0
        assert "error" in resp.json()

    async def test_delete_empty_ids(self, client):
        resp = await client.post("/batch/delete", json={"table": "frames", "ids": []})
        assert resp.json()["deleted"] == 0


@pytest.mark.asyncio
class TestBudgetAPI:
    async def test_get_budget_default(self, client):
        resp = await client.get("/engine/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_cap_usd" in data
        assert "daily_spend_usd" in data
        assert "under_budget" in data
        assert data["daily_spend_usd"] == 0.0
        assert data["under_budget"] is True

    async def test_set_and_get_budget(self, client):
        resp = await client.put("/engine/budget", json={"daily_cap_usd": 5.0})
        assert resp.status_code == 200
        assert resp.json()["daily_cap_usd"] == 5.0

        resp = await client.get("/engine/budget")
        assert resp.json()["daily_cap_usd"] == 5.0

    async def test_budget_reflects_spend(self, client, db):
        await db.record_usage(model="haiku", layer="episode",
                              input_tokens=100, output_tokens=50, cost_usd=1.5)
        resp = await client.get("/engine/budget")
        assert resp.json()["daily_spend_usd"] == 1.5

    async def test_budget_under_budget_false_when_exceeded(self, client, db):
        await client.put("/engine/budget", json={"daily_cap_usd": 1.0})
        await db.record_usage(model="opus", layer="distill",
                              input_tokens=1000, output_tokens=500, cost_usd=2.0)
        resp = await client.get("/engine/budget")
        assert resp.json()["under_budget"] is False

