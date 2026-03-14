"""Tests for pipeline collectors: poll_frames and poll_audio."""

import asyncio
import pytest

from engine.pipeline.collector import Frame, poll_frames, poll_audio


@pytest.mark.asyncio
class TestPollFrames:
    async def test_polls_new_frames(self, db):
        queue: asyncio.Queue[list[Frame]] = asyncio.Queue()

        # Insert frames before polling
        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="Terminal", window_name="zsh",
            text="git status", display_id=1, image_hash="h1",
            image_path="frames/2026-03-14/100000_d1.webp",
        )
        await db.insert_frame(
            timestamp="2026-03-14T10:01:00+00:00",
            app_name="VSCode", window_name="editor",
            text="code", display_id=1, image_hash="h2",
        )

        # Run one poll cycle
        task = asyncio.create_task(poll_frames(db, interval=100, on_frames=queue))
        frames = await asyncio.wait_for(queue.get(), timeout=5)
        task.cancel()

        assert len(frames) == 2
        assert frames[0].source == "capture"
        assert frames[0].app_name == "Terminal"
        assert frames[0].image_path == "frames/2026-03-14/100000_d1.webp"
        assert frames[1].app_name == "VSCode"

        # Cursor should be updated
        cursor = await db.get_state("frames_cursor")
        assert cursor == 2

    async def test_cursor_advances(self, db):
        queue: asyncio.Queue[list[Frame]] = asyncio.Queue()

        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="App1", window_name="w", text="t",
            display_id=1, image_hash="h1",
        )

        # Use short interval so second poll fires quickly
        task = asyncio.create_task(poll_frames(db, interval=1, on_frames=queue))
        await asyncio.wait_for(queue.get(), timeout=5)

        # Insert more
        await db.insert_frame(
            timestamp="2026-03-14T10:01:00+00:00",
            app_name="App2", window_name="w", text="t",
            display_id=1, image_hash="h2",
        )

        # Second poll should only get new frame
        frames = await asyncio.wait_for(queue.get(), timeout=5)
        task.cancel()

        assert len(frames) == 1
        assert frames[0].app_name == "App2"


@pytest.mark.asyncio
class TestPollAudio:
    async def test_polls_new_audio(self, db):
        queue: asyncio.Queue[list[Frame]] = asyncio.Queue()

        await db.insert_audio_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            duration_seconds=3.0, text="hello", language="en",
        )

        task = asyncio.create_task(poll_audio(db, interval=100, on_frames=queue))
        frames = await asyncio.wait_for(queue.get(), timeout=5)
        task.cancel()

        assert len(frames) == 1
        assert frames[0].source == "audio"
        assert frames[0].text == "hello"
        assert frames[0].app_name == "microphone"

    async def test_empty_db_no_emit(self, db):
        queue: asyncio.Queue[list[Frame]] = asyncio.Queue()

        task = asyncio.create_task(poll_audio(db, interval=1, on_frames=queue))
        # Wait a bit, should not emit anything
        await asyncio.sleep(0.1)
        task.cancel()

        assert queue.empty()
