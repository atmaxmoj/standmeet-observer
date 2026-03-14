"""Tests for engine DB: schema, insert, query, state, episodes, playbooks, usage."""

import pytest


@pytest.mark.asyncio
class TestFrames:
    async def test_insert_and_query(self, db):
        fid = await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="Terminal",
            window_name="zsh",
            text="$ git status",
            display_id=1,
            image_hash="abc123",
            image_path="frames/2026-03-14/100000_000_d1.webp",
        )
        assert fid == 1

        frames, total = await db.get_frames(limit=10, offset=0)
        assert total == 1
        assert frames[0]["app_name"] == "Terminal"
        assert frames[0]["image_path"] == "frames/2026-03-14/100000_000_d1.webp"

    async def test_pagination(self, db):
        for i in range(5):
            await db.insert_frame(
                timestamp=f"2026-03-14T10:0{i}:00+00:00",
                app_name="VSCode",
                window_name="editor",
                text=f"line {i}",
                display_id=1,
                image_hash=f"hash{i}",
            )
        frames, total = await db.get_frames(limit=2, offset=0)
        assert total == 5
        assert len(frames) == 2
        # DESC order: newest first
        assert frames[0]["id"] == 5

        frames2, _ = await db.get_frames(limit=2, offset=2)
        assert len(frames2) == 2
        assert frames2[0]["id"] == 3

    async def test_text_truncated_to_500(self, db):
        long_text = "x" * 1000
        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="App",
            window_name="win",
            text=long_text,
            display_id=1,
            image_hash="h",
        )
        frames, _ = await db.get_frames()
        assert len(frames[0]["text"]) == 500

    async def test_get_last_frame_hash(self, db):
        assert await db.get_last_frame_hash(1) is None

        await db.insert_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            app_name="App",
            window_name="win",
            text="t",
            display_id=1,
            image_hash="first",
        )
        await db.insert_frame(
            timestamp="2026-03-14T10:01:00+00:00",
            app_name="App",
            window_name="win",
            text="t",
            display_id=1,
            image_hash="second",
        )
        assert await db.get_last_frame_hash(1) == "second"
        assert await db.get_last_frame_hash(2) is None


@pytest.mark.asyncio
class TestAudioFrames:
    async def test_insert_and_query(self, db):
        aid = await db.insert_audio_frame(
            timestamp="2026-03-14T10:00:00+00:00",
            duration_seconds=5.2,
            text="hello world",
            language="en",
            source="mic",
        )
        assert aid == 1

        audio, total = await db.get_audio_frames()
        assert total == 1
        assert audio[0]["text"] == "hello world"
        assert audio[0]["duration_seconds"] == 5.2


@pytest.mark.asyncio
class TestOsEvents:
    async def test_insert_and_query(self, db):
        eid = await db.insert_os_event(
            timestamp="2026-03-14T10:00:00+00:00",
            event_type="shell_command",
            source="zsh",
            data="git push",
        )
        assert eid == 1

        events, total = await db.get_os_events()
        assert total == 1
        assert events[0]["data"] == "git push"

    async def test_filter_by_event_type(self, db):
        await db.insert_os_event(
            timestamp="2026-03-14T10:00:00+00:00",
            event_type="shell_command",
            source="zsh",
            data="git push",
        )
        await db.insert_os_event(
            timestamp="2026-03-14T10:01:00+00:00",
            event_type="browser_url",
            source="chrome",
            data="https://github.com",
        )

        events, total = await db.get_os_events(event_type="browser_url")
        assert total == 1
        assert events[0]["source"] == "chrome"

        all_events, all_total = await db.get_os_events()
        assert all_total == 2

    async def test_get_last_event_data(self, db):
        assert await db.get_last_os_event_data("shell_command", "zsh") is None

        await db.insert_os_event(
            timestamp="2026-03-14T10:00:00+00:00",
            event_type="shell_command",
            source="zsh",
            data="first",
        )
        await db.insert_os_event(
            timestamp="2026-03-14T10:01:00+00:00",
            event_type="shell_command",
            source="zsh",
            data="second",
        )
        assert await db.get_last_os_event_data("shell_command", "zsh") == "second"


@pytest.mark.asyncio
class TestState:
    async def test_get_default(self, db):
        assert await db.get_state("nonexistent") == 0
        assert await db.get_state("nonexistent", 42) == 42

    async def test_set_and_get(self, db):
        await db.set_state("cursor", 100)
        assert await db.get_state("cursor") == 100

    async def test_upsert(self, db):
        await db.set_state("cursor", 100)
        await db.set_state("cursor", 200)
        assert await db.get_state("cursor") == 200


@pytest.mark.asyncio
class TestEpisodes:
    async def test_insert_and_query(self, db):
        eid = await db.insert_episode(
            summary="Worked on git commit",
            app_names="Terminal,VSCode",
            frame_count=10,
            started_at="2026-03-14T10:00:00+00:00",
            ended_at="2026-03-14T10:30:00+00:00",
            frame_id_min=1,
            frame_id_max=10,
        )
        assert eid == 1

        episodes = await db.get_all_episodes()
        assert len(episodes) == 1
        assert episodes[0]["summary"] == "Worked on git commit"
        assert episodes[0]["frame_id_min"] == 1

    async def test_count(self, db):
        assert await db.count_episodes() == 0
        await db.insert_episode(
            summary="ep1", app_names="", frame_count=5,
            started_at="2026-03-14T10:00:00", ended_at="2026-03-14T10:30:00",
        )
        assert await db.count_episodes() == 1

    async def test_pagination(self, db):
        for i in range(3):
            await db.insert_episode(
                summary=f"ep{i}", app_names="", frame_count=1,
                started_at="2026-03-14T10:00:00", ended_at="2026-03-14T10:30:00",
            )
        episodes = await db.get_all_episodes(limit=2, offset=0)
        assert len(episodes) == 2


@pytest.mark.asyncio
class TestPlaybooks:
    async def test_insert_and_query(self, db):
        await db.upsert_playbook(
            name="daily standup",
            context="morning routine",
            action="open slack",
            confidence=0.8,
            evidence='["ep1"]',
        )
        playbooks = await db.get_all_playbooks()
        assert len(playbooks) == 1
        assert playbooks[0]["name"] == "daily standup"
        assert playbooks[0]["confidence"] == 0.8

    async def test_upsert_updates_existing(self, db):
        await db.upsert_playbook(
            name="deploy", context="c1", action="a1",
            confidence=0.5, evidence="[]",
        )
        await db.upsert_playbook(
            name="deploy", context="c2", action="a2",
            confidence=0.9, evidence='["ep1"]',
        )
        playbooks = await db.get_all_playbooks()
        assert len(playbooks) == 1
        assert playbooks[0]["confidence"] == 0.9
        assert playbooks[0]["context"] == "c2"


@pytest.mark.asyncio
class TestUsage:
    async def test_record_and_summary(self, db):
        await db.record_usage(
            model="claude-haiku-4-5-20251001",
            layer="task",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.003,
        )
        await db.record_usage(
            model="claude-opus-4-6",
            layer="weekly",
            input_tokens=5000,
            output_tokens=2000,
            cost_usd=0.225,
        )
        summary = await db.get_usage_summary(days=7)
        assert summary["total_calls"] == 2
        assert summary["total_input_tokens"] == 6000
        assert summary["total_output_tokens"] == 2500
        assert summary["total_cost_usd"] == 0.228
        assert len(summary["by_layer"]) == 2
        assert len(summary["by_day"]) == 1  # both recorded today

    async def test_empty_usage(self, db):
        summary = await db.get_usage_summary(days=7)
        assert summary["total_calls"] == 0
        assert summary["total_cost_usd"] == 0


@pytest.mark.asyncio
class TestStatus:
    async def test_empty_status(self, db):
        status = await db.get_status()
        assert status["episode_count"] == 0
        assert status["playbook_count"] == 0

    async def test_status_counts(self, db):
        await db.insert_episode(
            summary="ep1", app_names="", frame_count=1,
            started_at="2026-03-14T10:00:00", ended_at="2026-03-14T10:30:00",
        )
        await db.upsert_playbook(
            name="pb1", context="c", action="a",
            confidence=0.5, evidence="[]",
        )
        status = await db.get_status()
        assert status["episode_count"] == 1
        assert status["playbook_count"] == 1
