"""Observability data access — pipeline log persistence."""

import json

from sqlalchemy.orm import Session

from engine.infrastructure.persistence.models import PipelineLog


def insert_tool_call_log(
    session: Session,
    stage: str,
    tool_name: str,
    tool_input: dict,
    tool_output,
):
    """Write a tool call to pipeline_logs."""
    session.add(PipelineLog(
        stage=stage,
        prompt=json.dumps({"tool": tool_name, "input": tool_input}, default=str),
        response=json.dumps(tool_output, default=str)[:10000],
    ))
    session.commit()
