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

CREATE TABLE IF NOT EXISTS playbook_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playbook_name TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    maturity TEXT NOT NULL DEFAULT 'nascent',
    evidence TEXT NOT NULL DEFAULT '[]',
    change_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_playbook_history_name ON playbook_history(playbook_name);

CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    trigger TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '[]',
    uses TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.0,
    maturity TEXT NOT NULL DEFAULT 'nascent',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    proposals TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CHAT_WINDOW_SIZE = 20


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
            "ALTER TABLE playbook_entries ADD COLUMN last_evidence_at TEXT",
            "ALTER TABLE chat_messages ADD COLUMN proposals TEXT NOT NULL DEFAULT '[]'",
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

    async def get_frames(self, limit: int = 50, offset: int = 0, search: str = "") -> tuple[list[dict], int]:
        clauses, params = [], []
        if search:
            clauses.append("(app_name LIKE ? OR window_name LIKE ? OR text LIKE ?)")
            params.extend([f"%{search}%"] * 3)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._conn.execute(f"SELECT COUNT(*) FROM frames {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with self._conn.execute(
            f"SELECT id, timestamp, app_name, window_name, "
            f"substr(text, 1, 500) as text, display_id, image_hash, image_path "
            f"FROM frames {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return rows, total

    async def get_audio_frames(self, limit: int = 50, offset: int = 0, search: str = "") -> tuple[list[dict], int]:
        clauses, params = [], []
        if search:
            clauses.append("text LIKE ?")
            params.append(f"%{search}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._conn.execute(f"SELECT COUNT(*) FROM audio_frames {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with self._conn.execute(
            f"SELECT id, timestamp, duration_seconds, text, language, source "
            f"FROM audio_frames {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return rows, total

    async def get_os_events(
        self, limit: int = 50, offset: int = 0, event_type: str = "", search: str = ""
    ) -> tuple[list[dict], int]:
        clauses, params = [], []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if search:
            clauses.append("(data LIKE ? OR source LIKE ?)")
            params.extend([f"%{search}%"] * 2)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
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

    async def get_state_float(self, key: str, default: float = 0.0) -> float:
        async with self._conn.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return float(row["value"]) if row else default

    async def set_state_float(self, key: str, value: float):
        await self._conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        await self._conn.commit()

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

    async def get_all_episodes(self, limit: int = 100, offset: int = 0, search: str = "") -> list[dict]:
        clauses, params = [], []
        if search:
            clauses.append("(summary LIKE ? OR app_names LIKE ?)")
            params.extend([f"%{search}%"] * 2)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._conn.execute(
            f"SELECT * FROM episodes {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def count_episodes(self, search: str = "") -> int:
        clauses, params = [], []
        if search:
            clauses.append("(summary LIKE ? OR app_names LIKE ?)")
            params.extend([f"%{search}%"] * 2)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._conn.execute(f"SELECT COUNT(*) FROM episodes {where}", params) as cur:
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

    async def get_all_playbooks(self, search: str = "") -> list[dict]:
        clauses, params = [], []
        if search:
            clauses.append("(name LIKE ? OR context LIKE ? OR action LIKE ?)")
            params.extend([f"%{search}%"] * 3)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._conn.execute(
            f"SELECT * FROM playbook_entries {where} ORDER BY confidence DESC", params
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # -- playbook history --

    async def record_playbook_snapshot(
        self,
        playbook_name: str,
        confidence: float,
        maturity: str,
        evidence: str,
        change_reason: str = "",
    ):
        """Record a snapshot of a playbook entry's state in history."""
        await self._conn.execute(
            "INSERT INTO playbook_history (playbook_name, confidence, maturity, evidence, change_reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (playbook_name, confidence, maturity, evidence, change_reason),
        )
        await self._conn.commit()

    async def get_playbook_history(self, name: str) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM playbook_history WHERE playbook_name = ? ORDER BY created_at",
            (name,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # -- episode search (for recall tools) --

    async def search_episodes_by_keyword(self, query: str, limit: int = 10) -> list[dict]:
        async with self._conn.execute(
            "SELECT id, summary, app_names, started_at, ended_at "
            "FROM episodes WHERE summary LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_episodes_by_app(self, app_name: str, limit: int = 20) -> list[dict]:
        async with self._conn.execute(
            "SELECT id, summary, app_names, started_at, ended_at "
            "FROM episodes WHERE app_names LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{app_name}%", limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_episodes_by_timerange(self, hours: int = 24) -> list[dict]:
        async with self._conn.execute(
            "SELECT id, summary, app_names, started_at, ended_at "
            "FROM episodes WHERE created_at >= datetime('now', ?) ORDER BY created_at DESC",
            (f"-{hours} hours",),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

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

    async def get_daily_spend(self) -> float:
        """Sum today's LLM costs."""
        async with self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) as total "
            "FROM token_usage WHERE created_at >= datetime('now', '-1 days')",
        ) as cur:
            row = await cur.fetchone()
            return float(row["total"])

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

    async def get_pipeline_logs(self, limit: int = 50, offset: int = 0, search: str = "") -> tuple[list[dict], int]:
        clauses, params = [], []
        if search:
            clauses.append("(stage LIKE ? OR model LIKE ? OR prompt LIKE ? OR response LIKE ?)")
            params.extend([f"%{search}%"] * 4)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._conn.execute(f"SELECT COUNT(*) FROM pipeline_logs {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with self._conn.execute(
            f"SELECT id, stage, prompt, response, model, input_tokens, output_tokens, cost_usd, created_at "
            f"FROM pipeline_logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
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

    # ── Routines ──

    async def upsert_routine(
        self, name: str, trigger: str, goal: str,
        steps: str, uses: str, confidence: float, maturity: str = "nascent",
    ):
        await self._conn.execute(
            "INSERT INTO routines (name, trigger, goal, steps, uses, confidence, maturity, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET "
            "trigger=excluded.trigger, goal=excluded.goal, steps=excluded.steps, "
            "uses=excluded.uses, confidence=excluded.confidence, maturity=excluded.maturity, "
            "updated_at=datetime('now')",
            (name, trigger, goal, steps, uses, confidence, maturity),
        )
        await self._conn.commit()

    async def get_all_routines(self, search: str = "") -> list[dict]:
        clauses, params = [], []
        if search:
            clauses.append("(name LIKE ? OR trigger LIKE ? OR goal LIKE ?)")
            params.extend([f"%{search}%"] * 3)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._conn.execute(
            f"SELECT * FROM routines {where} ORDER BY confidence DESC", params
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ── Chat messages ──

    async def append_chat_message(self, role: str, content: str, proposals: str = "[]"):
        """Insert a message and trim to CHAT_WINDOW_SIZE."""
        await self._conn.execute(
            "INSERT INTO chat_messages (role, content, proposals) VALUES (?, ?, ?)",
            (role, content, proposals),
        )
        await self._conn.execute(
            "DELETE FROM chat_messages WHERE id NOT IN "
            "(SELECT id FROM chat_messages ORDER BY id DESC LIMIT ?)",
            (CHAT_WINDOW_SIZE,),
        )
        await self._conn.commit()

    async def get_chat_messages(self) -> list[dict]:
        """Return up to CHAT_WINDOW_SIZE most recent messages, oldest first."""
        cursor = await self._conn.execute(
            "SELECT id, role, content, proposals FROM chat_messages ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [{"id": r["id"], "role": r["role"], "content": r["content"], "proposals": r["proposals"]} for r in rows]

    async def update_chat_proposals(self, msg_id: int, proposals_json: str):
        """Update the proposals JSON for a specific chat message."""
        await self._conn.execute(
            "UPDATE chat_messages SET proposals = ? WHERE id = ?",
            (proposals_json, msg_id),
        )
        await self._conn.commit()

    async def clear_chat_messages(self):
        """Delete all chat messages."""
        await self._conn.execute("DELETE FROM chat_messages")
        await self._conn.commit()
