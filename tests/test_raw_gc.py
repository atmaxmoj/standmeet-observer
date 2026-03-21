"""Tests for raw data GC tools (frames, audio, os_events, pipeline_logs)."""

import pytest
from sqlalchemy import text
from engine.infrastructure.persistence.models import Frame, AudioFrame, OsEvent, PipelineLog
from engine.infrastructure.agent.repository import (
    get_data_stats,
    get_oldest_processed,
    purge_processed_frames,
    purge_processed_audio,
    purge_processed_os_events,
    purge_pipeline_logs,
)


@pytest.fixture
def session(sync_session):
    return sync_session


class TestGetDataStats:
    def test_empty_db(self, session):
        stats = get_data_stats(session)
        assert stats["frames"]["total"] == 0
        assert stats["frames"]["processed"] == 0
        assert stats["audio_frames"]["total"] == 0
        assert stats["os_events"]["total"] == 0
        assert stats["pipeline_logs"]["total"] == 0

    def test_counts_correct(self, session):
        # 3 frames: 2 processed, 1 not
        for i in range(3):
            session.add(Frame(timestamp=f"2026-03-{10+i}T00:00:00Z", processed=1 if i < 2 else 0))
        # 1 audio
        session.add(AudioFrame(timestamp="2026-03-10T00:00:00Z", processed=1))
        # 2 os_events
        session.add(OsEvent(timestamp="2026-03-10T00:00:00Z", event_type="shell", processed=1))
        session.add(OsEvent(timestamp="2026-03-11T00:00:00Z", event_type="url", processed=0))
        # 5 pipeline logs
        for i in range(5):
            session.add(PipelineLog(stage="episode", prompt="p", response="r"))
        session.commit()

        stats = get_data_stats(session)
        assert stats["frames"]["total"] == 3
        assert stats["frames"]["processed"] == 2
        assert stats["frames"]["unprocessed"] == 1
        assert stats["audio_frames"]["total"] == 1
        assert stats["audio_frames"]["processed"] == 1
        assert stats["os_events"]["total"] == 2
        assert stats["os_events"]["processed"] == 1
        assert stats["pipeline_logs"]["total"] == 5


class TestGetOldestProcessed:
    def test_empty(self, session):
        result = get_oldest_processed(session)
        assert result["frames"] is None

    def test_returns_oldest(self, session):
        session.add(Frame(timestamp="t1", processed=1, created_at="2026-03-01T00:00:00Z"))
        session.add(Frame(timestamp="t2", processed=1, created_at="2026-03-10T00:00:00Z"))
        session.add(Frame(timestamp="t3", processed=0))  # unprocessed -- should be ignored
        session.commit()
        result = get_oldest_processed(session)
        assert result["frames"] == "2026-03-01T00:00:00Z"

    def test_unprocessed_only_returns_none(self, session):
        session.add(Frame(timestamp="t1", processed=0))
        session.commit()
        result = get_oldest_processed(session)
        assert result["frames"] is None


class TestPurgeProcessedFrames:
    def test_purge_old(self, session, tmp_path):
        # Insert old processed frame with image file
        img_dir = tmp_path / "frames" / "2026-03-01"
        img_dir.mkdir(parents=True)
        img_file = img_dir / "test.webp"
        img_file.write_bytes(b"fake image")

        session.add(Frame(timestamp="t1", processed=1, image_path=str(img_file), created_at="2026-03-01T00:00:00Z"))
        # Recent processed frame -- should NOT be purged
        session.execute(
            text("INSERT INTO frames (timestamp, processed, created_at) VALUES (:ts, :p, NOW())"),
            {"ts": "t2", "p": 1},
        )
        # Unprocessed frame -- should NOT be purged
        session.add(Frame(timestamp="t3", processed=0, created_at="2026-01-01T00:00:00Z"))
        session.commit()

        result = purge_processed_frames(session, older_than_days=7)
        assert result["deleted"] == 1
        assert result["files_deleted"] == 1
        assert not img_file.exists()

        remaining = session.query(Frame).count()
        assert remaining == 2

    def test_no_old_data(self, session):
        session.add(Frame(timestamp="t1", processed=1))
        session.commit()
        result = purge_processed_frames(session, older_than_days=7)
        assert result["deleted"] == 0

    def test_missing_image_file_ok(self, session):
        session.add(Frame(timestamp="t1", processed=1, image_path="/nonexistent/path.webp", created_at="2020-01-01T00:00:00Z"))
        session.commit()
        result = purge_processed_frames(session, older_than_days=7)
        assert result["deleted"] == 1
        assert result["files_deleted"] == 0


class TestPurgeProcessedAudio:
    def test_purge_old(self, session, tmp_path):
        chunk_file = tmp_path / "chunk.wav"
        chunk_file.write_bytes(b"fake audio")

        session.add(AudioFrame(timestamp="t1", processed=1, chunk_path=str(chunk_file), created_at="2020-01-01T00:00:00Z"))
        session.add(AudioFrame(timestamp="t2", processed=0))
        session.commit()

        result = purge_processed_audio(session, older_than_days=7)
        assert result["deleted"] == 1
        assert result["files_deleted"] == 1
        assert not chunk_file.exists()

    def test_no_old_data(self, session):
        result = purge_processed_audio(session, older_than_days=7)
        assert result["deleted"] == 0


class TestPurgeProcessedOsEvents:
    def test_purge_old(self, session):
        session.add(OsEvent(timestamp="t1", event_type="shell", processed=1, created_at="2020-01-01T00:00:00Z"))
        session.add(OsEvent(timestamp="t2", event_type="url", processed=1))
        session.commit()

        result = purge_processed_os_events(session, older_than_days=7)
        assert result["deleted"] == 1

    def test_keeps_unprocessed(self, session):
        session.add(OsEvent(timestamp="t1", event_type="shell", processed=0, created_at="2020-01-01T00:00:00Z"))
        session.commit()
        result = purge_processed_os_events(session, older_than_days=7)
        assert result["deleted"] == 0


class TestPurgePipelineLogs:
    def test_purge_old(self, session):
        session.add(PipelineLog(stage="episode", created_at="2020-01-01T00:00:00Z"))
        session.add(PipelineLog(stage="distill"))
        session.commit()

        result = purge_pipeline_logs(session, older_than_days=7)
        assert result["deleted"] == 1

        remaining = session.query(PipelineLog).count()
        assert remaining == 1

    def test_no_old_data(self, session):
        result = purge_pipeline_logs(session, older_than_days=7)
        assert result["deleted"] == 0
