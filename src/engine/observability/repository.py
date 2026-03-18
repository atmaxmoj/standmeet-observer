"""Observability data access — pipeline log persistence."""

import json
import sqlite3

from engine.storage.session import get_session
from engine.storage.models import PipelineLog


def insert_tool_call_log(
    conn: sqlite3.Connection,
    stage: str,
    tool_name: str,
    tool_input: dict,
    tool_output,
):
    """Write a tool call to pipeline_logs."""
    s = get_session(conn)
    s.add(PipelineLog(
        stage=stage,
        prompt=json.dumps({"tool": tool_name, "input": tool_input}, default=str),
        response=json.dumps(tool_output, default=str)[:10000],
    ))
    s.flush()
    s.close()
