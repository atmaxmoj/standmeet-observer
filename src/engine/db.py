import logging

import aiosqlite
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCHEMA = """
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

CREATE INDEX IF NOT EXISTS idx_frames_id ON frames(id);

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

CREATE INDEX IF NOT EXISTS idx_audio_frames_id ON audio_frames(id);

CREATE TABLE IF NOT EXISTS os_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_os_events_id ON os_events(id);
CREATE INDEX IF NOT EXISTS idx_os_events_type ON os_events(event_type);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    app_names TEXT NOT NULL DEFAULT '',
    frame_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    frame_id_min INTEGER NOT NULL DEFAULT 0,
    frame_id_max INTEGER NOT NULL DEFAULT 0,
    frame_source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS playbook_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    context TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    maturity TEXT NOT NULL DEFAULT 'nascent',
    evidence TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,
    layer TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_token_usage_created_at ON token_usage(created_at);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_pipeline_logs_stage ON pipeline_logs(stage);
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_created_at ON pipeline_logs(created_at);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self):
        logger.debug("connecting to database at %s", self.path)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        # Migrations for existing databases
        for sql in [
            "ALTER TABLE frames ADD COLUMN processed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE audio_frames ADD COLUMN processed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE os_events ADD COLUMN processed INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                await self._conn.execute(sql)
            except Exception:
                pass  # Column already exists
        # Indexes on processed column (safe to run after migration)
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_frames_processed ON frames(processed)",
            "CREATE INDEX IF NOT EXISTS idx_audio_frames_processed ON audio_frames(processed)",
            "CREATE INDEX IF NOT EXISTS idx_os_events_processed ON os_events(processed)",
        ]:
            await self._conn.execute(sql)
        await self._conn.commit()
        logger.info("database connected and schema initialized at %s", self.path)

    async def close(self):
        if self._conn:
            logger.debug("closing database connection")
            await self._conn.close()

    # -- ingest (capture/audio daemons push data here) --

    async def insert_frame(
        self,
        timestamp: str,
        app_name: str,
        window_name: str,
        text: str,
        display_id: int,
        image_hash: str,
        image_path: str = "",
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO frames (timestamp, app_name, window_name, text, display_id, image_hash, image_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, app_name, window_name, text, display_id, image_hash, image_path),
        ) as cur:
            await self._conn.commit()
            logger.debug(
                "inserted frame id=%d display=%d app=%s",
                cur.lastrowid, display_id, app_name,
            )
            return cur.lastrowid

    async def insert_audio_frame(
        self,
        timestamp: str,
        duration_seconds: float,
        text: str,
        language: str,
        source: str = "mic",
        chunk_path: str = "",
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO audio_frames (timestamp, duration_seconds, text, language, source, chunk_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, duration_seconds, text, language, source, chunk_path),
        ) as cur:
            await self._conn.commit()
            logger.debug(
                "inserted audio_frame id=%d duration=%.1fs lang=%s",
                cur.lastrowid, duration_seconds, language,
            )
            return cur.lastrowid

    async def insert_os_event(
        self,
        timestamp: str,
        event_type: str,
        source: str,
        data: str,
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO os_events (timestamp, event_type, source, data) "
            "VALUES (?, ?, ?, ?)",
            (timestamp, event_type, source, data),
        ) as cur:
            await self._conn.commit()
            logger.debug(
                "inserted os_event id=%d type=%s source=%s",
                cur.lastrowid, event_type, source,
            )
            return cur.lastrowid

    # -- query (for API + pipeline) --

    async def get_frames(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        async with self._conn.execute("SELECT COUNT(*) FROM frames") as cur:
            total = (await cur.fetchone())[0]
        async with self._conn.execute(
            "SELECT id, timestamp, app_name, window_name, "
            "substr(text, 1, 500) as text, display_id, image_hash, image_path "
            "FROM frames ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return rows, total

    async def get_audio_frames(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        async with self._conn.execute("SELECT COUNT(*) FROM audio_frames") as cur:
            total = (await cur.fetchone())[0]
        async with self._conn.execute(
            "SELECT id, timestamp, duration_seconds, text, language, source "
            "FROM audio_frames ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return rows, total

    async def get_os_events(
        self, limit: int = 50, offset: int = 0, event_type: str = ""
    ) -> tuple[list[dict], int]:
        where = "WHERE event_type = ?" if event_type else ""
        params: list = [event_type] if event_type else []
        async with self._conn.execute(
            f"SELECT COUNT(*) FROM os_events {where}", params
        ) as cur:
            total = (await cur.fetchone())[0]
        async with self._conn.execute(
            f"SELECT id, timestamp, event_type, source, data "
            f"FROM os_events {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return rows, total

    async def get_last_os_event_data(self, event_type: str, source: str) -> str | None:
        async with self._conn.execute(
            "SELECT data FROM os_events WHERE event_type = ? AND source = ? "
            "ORDER BY id DESC LIMIT 1",
            (event_type, source),
        ) as cur:
            row = await cur.fetchone()
            return row["data"] if row else None

    async def get_last_frame_hash(self, display_id: int) -> str | None:
        async with self._conn.execute(
            "SELECT image_hash FROM frames WHERE display_id = ? ORDER BY id DESC LIMIT 1",
            (display_id,),
        ) as cur:
            row = await cur.fetchone()
            return row["image_hash"] if row else None

    # -- state (each collector tracks its own cursor) --

    async def get_state(self, key: str, default: int = 0) -> int:
        async with self._conn.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            val = int(row["value"]) if row else default
            logger.debug("get_state(%s) = %d", key, val)
            return val

    async def set_state(self, key: str, value: int):
        await self._conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        await self._conn.commit()
        logger.debug("set_state(%s) = %d", key, value)

    # -- episodes --

    async def insert_episode(
        self,
        summary: str,
        app_names: str,
        frame_count: int,
        started_at: str,
        ended_at: str,
        frame_id_min: int = 0,
        frame_id_max: int = 0,
        frame_source: str = "",
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO episodes (summary, app_names, frame_count, started_at, ended_at, "
            "frame_id_min, frame_id_max, frame_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (summary, app_names, frame_count, started_at, ended_at,
             frame_id_min, frame_id_max, frame_source),
        ) as cur:
            await self._conn.commit()
            logger.debug(
                "inserted episode id=%d frame_count=%d range=[%s, %s] frames=[%d, %d]",
                cur.lastrowid, frame_count, started_at, ended_at, frame_id_min, frame_id_max,
            )
            return cur.lastrowid

    async def get_recent_episodes(self, days: int = 7) -> list[dict]:
        datetime.now(timezone.utc).isoformat()
        async with self._conn.execute(
            "SELECT * FROM episodes WHERE created_at >= datetime('now', ?) ORDER BY created_at",
            (f"-{days} days",),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_episodes(self, limit: int = 100, offset: int = 0) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM episodes ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def count_episodes(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM episodes") as cur:
            return (await cur.fetchone())[0]

    # -- playbook entries --

    async def upsert_playbook(
        self,
        name: str,
        context: str,
        action: str,
        confidence: float,
        evidence: str,
        maturity: str = "nascent",
    ):
        await self._conn.execute(
            "INSERT INTO playbook_entries (name, context, action, confidence, maturity, evidence, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET "
            "context=excluded.context, action=excluded.action, "
            "confidence=excluded.confidence, maturity=excluded.maturity, "
            "evidence=excluded.evidence, "
            "updated_at=datetime('now')",
            (name, context, action, confidence, maturity, evidence),
        )
        await self._conn.commit()
        logger.debug(
            "upserted playbook name=%s confidence=%.2f maturity=%s",
            name, confidence, maturity,
        )

    async def get_all_playbooks(self) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM playbook_entries ORDER BY confidence DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # -- token usage --

    async def record_usage(
        self,
        model: str,
        layer: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ):
        await self._conn.execute(
            "INSERT INTO token_usage (model, layer, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (model, layer, input_tokens, output_tokens, cost_usd),
        )
        await self._conn.commit()
        logger.debug(
            "recorded usage: model=%s layer=%s in=%d out=%d cost=$%.4f",
            model, layer, input_tokens, output_tokens, cost_usd,
        )

    async def get_usage_summary(self, days: int = 7) -> dict:
        """Get token usage breakdown by layer and model for the past N days."""
        rows_by_layer = []
        async with self._conn.execute(
            "SELECT layer, model, "
            "SUM(input_tokens) as total_input, "
            "SUM(output_tokens) as total_output, "
            "SUM(cost_usd) as total_cost, "
            "COUNT(*) as call_count "
            "FROM token_usage "
            "WHERE created_at >= datetime('now', ?) "
            "GROUP BY layer, model "
            "ORDER BY total_cost DESC",
            (f"-{days} days",),
        ) as cur:
            rows_by_layer = [dict(r) for r in await cur.fetchall()]

        rows_by_day = []
        async with self._conn.execute(
            "SELECT date(created_at) as day, "
            "SUM(input_tokens) as total_input, "
            "SUM(output_tokens) as total_output, "
            "SUM(cost_usd) as total_cost, "
            "COUNT(*) as call_count "
            "FROM token_usage "
            "WHERE created_at >= datetime('now', ?) "
            "GROUP BY date(created_at) "
            "ORDER BY day",
            (f"-{days} days",),
        ) as cur:
            rows_by_day = [dict(r) for r in await cur.fetchall()]

        total_cost = sum(r["total_cost"] for r in rows_by_layer)
        total_input = sum(r["total_input"] for r in rows_by_layer)
        total_output = sum(r["total_output"] for r in rows_by_layer)
        total_calls = sum(r["call_count"] for r in rows_by_layer)

        return {
            "days": days,
            "total_cost_usd": round(total_cost, 4),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_calls": total_calls,
            "by_layer": rows_by_layer,
            "by_day": rows_by_day,
        }

    # -- pipeline logs --

    async def insert_pipeline_log(
        self,
        stage: str,
        prompt: str,
        response: str,
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> int:
        async with self._conn.execute(
            "INSERT INTO pipeline_logs (stage, prompt, response, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (stage, prompt, response, model, input_tokens, output_tokens, cost_usd),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid

    async def get_pipeline_logs(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        async with self._conn.execute("SELECT COUNT(*) FROM pipeline_logs") as cur:
            total = (await cur.fetchone())[0]
        async with self._conn.execute(
            "SELECT id, stage, prompt, response, model, input_tokens, output_tokens, cost_usd, created_at "
            "FROM pipeline_logs ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return rows, total

    # -- batch delete --

    async def delete_rows(self, table: str, ids: list[int]) -> int:
        """Delete rows by IDs from an allowed table. Returns count deleted."""
        allowed = {"frames", "audio_frames", "os_events", "episodes", "playbook_entries"}
        if table not in allowed:
            raise ValueError(f"delete not allowed on table: {table}")
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        async with self._conn.execute(
            f"DELETE FROM {table} WHERE id IN ({placeholders})", ids
        ) as cur:
            await self._conn.commit()
            return cur.rowcount

    # -- stats --

    async def get_status(self) -> dict:
        episode_count = 0
        playbook_count = 0
        async with self._conn.execute("SELECT COUNT(*) as c FROM episodes") as cur:
            row = await cur.fetchone()
            episode_count = row["c"]
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM playbook_entries"
        ) as cur:
            row = await cur.fetchone()
            playbook_count = row["c"]
        # Check if capture is alive: last frame within 2 minutes
        last_frame_at = None
        async with self._conn.execute(
            "SELECT timestamp FROM frames ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            if row:
                last_frame_at = row["timestamp"]

        capture_alive = False
        if last_frame_at:
            from datetime import datetime, timezone, timedelta
            try:
                ts = datetime.fromisoformat(last_frame_at)
                capture_alive = (datetime.now(timezone.utc) - ts) < timedelta(minutes=2)
            except Exception:
                pass

        return {
            "episode_count": episode_count,
            "playbook_count": playbook_count,
            "capture_alive": capture_alive,
            "last_frame_at": last_frame_at,
        }
