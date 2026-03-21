"""Stage: collect frames from DB by IDs + store episodes.

Delegates to etl/repository.py for actual DB access.
"""

from engine.infrastructure.etl.repository import load_frames, store_episodes

__all__ = ["load_frames", "store_episodes"]
