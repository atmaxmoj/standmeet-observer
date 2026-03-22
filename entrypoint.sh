#!/bin/sh
# Fix ownership of /data (volume may have files from previous root runs)
chown -R engine:engine /data/ 2>/dev/null || true
# Clear stale Huey task locks from previous runs
rm -f /data/huey.db /data/huey.db-shm /data/huey.db-wal
exec su -s /bin/sh engine -c "uv run uvicorn engine.main:app --host 0.0.0.0 --port 5000"
