from pydantic_settings import BaseSettings


# ┌─────────────────────────────────────────────────────────────┐
# │  Model tiers (2026-03 pricing)                              │
# │                                                             │
# │  FAST (Haiku) — episode extraction      ~$0.01/episode      │
# │  DEEP (Opus)  — daily distill + GC      ~$1-2/run           │
# │                                                             │
# │  DO NOT swap these. Opus on episode-level = ~$50/day.       │
# └─────────────────────────────────────────────────────────────┘
MODEL_FAST = "claude-haiku-4-5-20251001"
MODEL_DEEP = "claude-opus-4-6"

# Budget cap
DAILY_COST_CAP_USD = 10.0

# Per-token pricing (USD) — 2026-03
TOKEN_COSTS = {
    MODEL_FAST: {"input": 0.80 / 1_000_000, "output": 4.00 / 1_000_000},
    MODEL_DEEP: {"input": 15.00 / 1_000_000, "output": 75.00 / 1_000_000},
}


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_code_oauth_token: str = ""

    # OpenAI-compatible API (e.g. ollama, vllm, openrouter, together, etc.)
    openai_api_key: str = ""
    openai_base_url: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///data/engine.db"
    database_url_sync: str = "sqlite:///data/engine.db"

    # Huey task queue (always SQLite, separate from engine data)
    huey_db_dir: str = "/data"

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
