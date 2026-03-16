"""Decorator for logging mutations to pipeline_logs."""

import functools
import json
import logging

logger = logging.getLogger(__name__)


def log_mutation(stage: str):
    """Decorator: log the input/output of any async mutation to pipeline_logs.

    The wrapped function must take `db` as its first argument and return
    a dict with at least `success` and `result` keys.
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(db, *args, **kwargs):
            result = await fn(db, *args, **kwargs)
            try:
                prompt = json.dumps(kwargs or (args[0] if args else {}), default=str)
                response = json.dumps(result.get("result", {}), default=str)
                await db.insert_pipeline_log(
                    stage=stage,
                    prompt=prompt,
                    response=response,
                    model="",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0,
                )
            except Exception:
                logger.exception("log_mutation: failed to log %s", stage)
            return result
        return wrapper
    return decorator
