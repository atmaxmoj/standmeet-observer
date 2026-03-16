"""Tests for raw data GC tools (frames, audio, os_events, pipeline_logs)."""

import sqlite3
import pytest
from engine.pipeline.audit import (
    get_data_stats,
    get_oldest_processed,
    purge_processed_frames,
    purge_processed_audio,
    purge_processed_os_events,
    purge_pipeline_logs,
)


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            app_name TEXT NOT NULL DEFAULT '',
            window_name TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            display_id INTEGER NOT NULL DEFAULT 0,
            image_hash TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS audio_frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            duration_seconds REAL NOT NULL DEFAULT 0.0,
            text TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'mic',
            chunk_path TEXT NOT NULL DEFAULT '',
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS os_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL DEFAULT '',
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS pipeline_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage TEXT NOT NULL,
            prompt TEXT NOT NULL DEFAULT '',
            response TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    c.commit()
    yield c
    c.close()


class TestGetDataStats:
    def test_empty_db(self, conn):
        stats = get_data_stats(conn)
        assert stats["frames"]["total"] == 0
        assert stats["frames"]["processed"] == 0
        assert stats["audio_frames"]["total"] == 0
        assert stats["os_events"]["total"] == 0
        assert stats["pipeline_logs"]["total"] == 0

    def test_counts_correct(self, conn):
        # 3 frames: 2 processed, 1 not
        for i in range(3):
            conn.execute(
                "INSERT INTO frames (timestamp, processed) VALUES (?, ?)",
                (f"2026-03-{10+i}T00:00:00Z", 1 if i < 2 else 0),
            )
        # 1 audio
        conn.execute(
            "INSERT INTO audio_frames (timestamp, processed) VALUES (?, ?)",
            ("2026-03-10T00:00:00Z", 1),
        )
        # 2 os_events
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, processed) VALUES (?, ?, ?)",
            ("2026-03-10T00:00:00Z", "shell", 1),
        )
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, processed) VALUES (?, ?, ?)",
            ("2026-03-11T00:00:00Z", "url", 0),
        )
        # 5 pipeline logs
        for i in range(5):
            conn.execute(
                "INSERT INTO pipeline_logs (stage, prompt, response) VALUES (?, ?, ?)",
                ("episode", "p", "r"),
            )
        conn.commit()

        stats = get_data_stats(conn)
        assert stats["frames"]["total"] == 3
        assert stats["frames"]["processed"] == 2
        assert stats["frames"]["unprocessed"] == 1
        assert stats["audio_frames"]["total"] == 1
        assert stats["audio_frames"]["processed"] == 1
        assert stats["os_events"]["total"] == 2
        assert stats["os_events"]["processed"] == 1
        assert stats["pipeline_logs"]["total"] == 5


class TestGetOldestProcessed:
    def test_empty(self, conn):
        result = get_oldest_processed(conn)
        assert result["frames"] is None

    def test_returns_oldest(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, processed, created_at) VALUES (?, ?, ?)",
            ("t1", 1, "2026-03-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO frames (timestamp, processed, created_at) VALUES (?, ?, ?)",
            ("t2", 1, "2026-03-10T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO frames (timestamp, processed) VALUES (?, ?)",
            ("t3", 0),  # unprocessed — should be ignored
        )
        conn.commit()
        result = get_oldest_processed(conn)
        assert result["frames"] == "2026-03-01T00:00:00Z"

    def test_unprocessed_only_returns_none(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, processed) VALUES (?, ?)",
            ("t1", 0),
        )
        conn.commit()
        result = get_oldest_processed(conn)
        assert result["frames"] is None


class TestPurgeProcessedFrames:
    def test_purge_old(self, conn, tmp_path):
        # Insert old processed frame with image file
        img_dir = tmp_path / "frames" / "2026-03-01"
        img_dir.mkdir(parents=True)
        img_file = img_dir / "test.webp"
        img_file.write_bytes(b"fake image")

        conn.execute(
            "INSERT INTO frames (timestamp, processed, image_path, created_at) VALUES (?, ?, ?, ?)",
            ("t1", 1, str(img_file), "2026-03-01T00:00:00Z"),
        )
        # Recent processed frame — should NOT be purged
        conn.execute(
            "INSERT INTO frames (timestamp, processed, created_at) VALUES (?, ?, datetime('now'))",
            ("t2", 1),
        )
        # Unprocessed frame — should NOT be purged
        conn.execute(
            "INSERT INTO frames (timestamp, processed, created_at) VALUES (?, ?, ?)",
            ("t3", 0, "2026-01-01T00:00:00Z"),
        )
        conn.commit()

        result = purge_processed_frames(conn, older_than_days=7)
        assert result["deleted"] == 1
        assert result["files_deleted"] == 1
        assert not img_file.exists()

        remaining = conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
        assert remaining == 2

    def test_no_old_data(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, processed) VALUES (?, ?)",
            ("t1", 1),
        )
        conn.commit()
        result = purge_processed_frames(conn, older_than_days=7)
        assert result["deleted"] == 0

    def test_missing_image_file_ok(self, conn):
        conn.execute(
            "INSERT INTO frames (timestamp, processed, image_path, created_at) VALUES (?, ?, ?, ?)",
            ("t1", 1, "/nonexistent/path.webp", "2020-01-01T00:00:00Z"),
        )
        conn.commit()
        result = purge_processed_frames(conn, older_than_days=7)
        assert result["deleted"] == 1
        assert result["files_deleted"] == 0


class TestPurgeProcessedAudio:
    def test_purge_old(self, conn, tmp_path):
        chunk_file = tmp_path / "chunk.wav"
        chunk_file.write_bytes(b"fake audio")

        conn.execute(
            "INSERT INTO audio_frames (timestamp, processed, chunk_path, created_at) VALUES (?, ?, ?, ?)",
            ("t1", 1, str(chunk_file), "2020-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO audio_frames (timestamp, processed) VALUES (?, ?)",
            ("t2", 0),
        )
        conn.commit()

        result = purge_processed_audio(conn, older_than_days=7)
        assert result["deleted"] == 1
        assert result["files_deleted"] == 1
        assert not chunk_file.exists()

    def test_no_old_data(self, conn):
        result = purge_processed_audio(conn, older_than_days=7)
        assert result["deleted"] == 0


class TestPurgeProcessedOsEvents:
    def test_purge_old(self, conn):
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, processed, created_at) VALUES (?, ?, ?, ?)",
            ("t1", "shell", 1, "2020-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, processed) VALUES (?, ?, ?)",
            ("t2", "url", 1),
        )
        conn.commit()

        result = purge_processed_os_events(conn, older_than_days=7)
        assert result["deleted"] == 1

    def test_keeps_unprocessed(self, conn):
        conn.execute(
            "INSERT INTO os_events (timestamp, event_type, processed, created_at) VALUES (?, ?, ?, ?)",
            ("t1", "shell", 0, "2020-01-01T00:00:00Z"),
        )
        conn.commit()
        result = purge_processed_os_events(conn, older_than_days=7)
        assert result["deleted"] == 0


class TestPurgePipelineLogs:
    def test_purge_old(self, conn):
        conn.execute(
            "INSERT INTO pipeline_logs (stage, created_at) VALUES (?, ?)",
            ("episode", "2020-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO pipeline_logs (stage) VALUES (?)",
            ("distill",),
        )
        conn.commit()

        result = purge_pipeline_logs(conn, older_than_days=7)
        assert result["deleted"] == 1

        remaining = conn.execute("SELECT COUNT(*) FROM pipeline_logs").fetchone()[0]
        assert remaining == 1

    def test_no_old_data(self, conn):
        result = purge_pipeline_logs(conn, older_than_days=7)
        assert result["deleted"] == 0
