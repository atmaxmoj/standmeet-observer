"""Vulture whitelist — framework-registered code that appears unused statically."""

# Huey periodic tasks (registered via @huey.periodic_task decorator)
daily_distill_task  # noqa
daily_routines_task  # noqa

# Pydantic Settings fields (read from environment variables)
poll_interval_seconds  # noqa
host  # noqa
port  # noqa
model_config  # noqa

# SQLAlchemy / manifest dataclass fields (accessed by framework)
version  # noqa
author  # noqa
platform  # noqa
entrypoint  # noqa
events  # noqa
context_description  # noqa
config  # noqa
_owns_session  # noqa

# Storage methods called indirectly via API routes or manifest registry
insert_frame  # noqa
insert_audio_frame  # noqa
insert_os_event  # noqa
get_last_os_event_data  # noqa
get_last_frame_hash  # noqa
get_frame_image_path  # noqa
get_episodes_by_timerange  # noqa

# Engine utilities
_utcnow  # noqa
get_async_session_factory  # noqa
_set_signal_handlers  # noqa

# Manifest registry methods used by sources
format_context  # noqa
all_sources  # noqa
names  # noqa

# Pipeline functions called from scheduler or API
process_window  # noqa

# Repository functions called from ToolDef-based tools (audit.py)
record_snapshot  # noqa
