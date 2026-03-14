from pydantic_settings import BaseSettings


# ┌─────────────────────────────────────────────────────────────┐
# │  Model costs (2026-03 pricing)                              │
# │                                                             │
# │  HAIKU  — task-level episodes     ~$0.01/episode            │
# │  OPUS   — weekly playbook distill ~$1-2/week                │
# │                                                             │
# │  DO NOT swap these. Haiku on task-level keeps costs ~$0.    │
# │  Opus on task-level would cost ~$50/day.                    │
# └─────────────────────────────────────────────────────────────┘
MODEL_TASK = "claude-haiku-4-5-20251001"
MODEL_WEEKLY = "claude-opus-4-6"

# Per-token pricing (USD) — 2026-03
TOKEN_COSTS = {
    MODEL_TASK: {"input": 0.80 / 1_000_000, "output": 4.00 / 1_000_000},
    MODEL_WEEKLY: {"input": 15.00 / 1_000_000, "output": 75.00 / 1_000_000},
}


class Settings(BaseSettings):
    anthropic_api_key: str

    # Engine storage
    db_path: str = "/data/engine.db"

    # Frames directory (for image access during episode processing)
    frames_base_dir: str = "/data/frames"

    # Polling
    poll_interval_seconds: int = 5

    # Task boundary detection
    idle_threshold_seconds: int = 300  # 5 min idle gap = flush window

    # Server
    host: str = "0.0.0.0"
    port: int = 5000

    model_config = {"env_prefix": ""}
