"""Vulture whitelist — framework-registered code that appears unused statically."""

# Huey periodic tasks (registered via @huey.periodic_task decorator)
daily_distill_task
daily_routines_task
daily_gc_task

# Pydantic Settings fields (read from environment variables)
poll_interval_seconds
host
port
model_config
openai_api_key
openai_base_url

# SQLAlchemy / manifest dataclass fields (accessed by framework)
version
author
platform
entrypoint
events
context_description
config
_owns_session

# Storage methods called indirectly via API routes or manifest registry
insert_frame
insert_audio_frame
insert_os_event
get_last_os_event_data
get_last_frame_hash
get_frame_image_path
get_episodes_by_timerange

# Engine utilities
_utcnow
get_async_session_factory
_set_signal_handlers

# Manifest registry methods used by sources
format_context
all_sources
names

# Pipeline functions called from scheduler or API
process_window

# Repository functions called from ToolDef-based tools (audit.py)
record_snapshot

# Validation function — has unit tests, should be wired into MCP write tools
validate_playbooks

# LLM adapters — used when corresponding env vars are configured
OpenAIClient

# Domain entities — newly created, callers being migrated
Playbook
VALID_TYPES
validate_playbook_entry

