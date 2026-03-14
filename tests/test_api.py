"""Tests for engine API: ingest endpoints, query endpoints, frame image serving."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from engine.db import DB
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
