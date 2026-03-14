"""SQLite writer for audio frames. Shares DB with capture daemon (WAL mode)."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    text TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'mic',
    chunk_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audio_frames_id ON audio_frames(id);
"""

MIGRATION_ADD_SOURCE = """
ALTER TABLE audio_frames ADD COLUMN source TEXT NOT NULL DEFAULT 'mic';
"""


class AudioDB:
    def __init__(self, path: str):
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def connect(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        logger.debug("connecting to audio DB at %s", self.path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        # Migrate: add source column if missing
        try:
            self._conn.execute(MIGRATION_ADD_SOURCE)
            self._conn.commit()
            logger.info("migrated: added source column")
        except sqlite3.OperationalError:
            pass  # column already exists
        self._conn.commit()
        logger.info("audio DB ready at %s (WAL mode)", self.path)

    def close(self):
        if self._conn:
            logger.debug("closing audio DB")
            self._conn.close()

    def insert_audio_frame(
        self,
        timestamp: str,
        duration_seconds: float,
        text: str,
        language: str,
        chunk_path: str,
        source: str = "mic",
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO audio_frames (timestamp, duration_seconds, text, language, source, chunk_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, duration_seconds, text, language, source, chunk_path),
        )
        self._conn.commit()
        row_id = cursor.lastrowid
        logger.debug(
            "inserted audio_frame id=%d duration=%.1fs lang=%s text_len=%d",
            row_id, duration_seconds, language, len(text),
        )
        return row_id
