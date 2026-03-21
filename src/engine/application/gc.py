"""Use case: garbage collection — decay + agent-driven audit."""

import logging

from sqlalchemy.orm import Session

from engine.config import Settings, MODEL_DEEP, DAILY_COST_CAP_USD
from engine.infrastructure.pipeline.budget import check_daily_budget
from engine.infrastructure.pipeline.decay import decay_confidence, decay_routines

logger = logging.getLogger(__name__)


def run_gc(settings: Settings, session: Session) -> dict:
    """Run garbage collection: deterministic decay + agent audit.

    Returns summary dict.
    """
    if not check_daily_budget(session, DAILY_COST_CAP_USD):
        logger.warning("gc: daily budget exceeded, skipping")
        return {"skipped": True, "reason": "budget_exceeded"}

    # Phase 1: Deterministic decay
    decayed_pb = decay_confidence(session)
    decayed_rt = decay_routines(session)
    logger.info("gc: decayed %d playbook entries, %d routines", decayed_pb, decayed_rt)

    # Phase 2: Agent-driven audit
    from engine.infrastructure.agent.tools.dedup import make_dedup_tools
    from engine.infrastructure.agent.tools.audit import make_audit_tools, make_manifest_purge_tools
    from engine.infrastructure.agent.service import AgentService

    gc_tools = make_dedup_tools(session) + make_audit_tools(session) + make_manifest_purge_tools(session)
    gc_prompt = _build_gc_prompt()

    try:
        agent = AgentService(settings)
        resp = agent.run(gc_prompt, MODEL_DEEP, gc_tools, max_turns=10)

        from engine.infrastructure.persistence.sync_db import SyncDB
        cost = resp.cost_usd or 0
        db = SyncDB(session)
        db.record_usage(MODEL_DEEP, "gc", resp.input_tokens, resp.output_tokens, cost)
        db.insert_pipeline_log("gc", gc_prompt, resp.text, MODEL_DEEP, resp.input_tokens, resp.output_tokens, cost)
        session.commit()
        logger.info("gc: agent audit complete, cost=$%.4f", cost)
        return {"decayed_pb": decayed_pb, "decayed_rt": decayed_rt, "audit_cost": cost}
    except NotImplementedError:
        logger.info("gc: LLM client does not support tools, skipping agent audit")
        session.commit()
        return {"decayed_pb": decayed_pb, "decayed_rt": decayed_rt, "audit_cost": 0}


GC_PROMPT = """\
You are auditing the behavioral memory system. Your goals:

1. **Dedup**: Find and merge similar playbook entries (use find_similar_pairs + merge_entries).
2. **Evidence check**: Verify entries still have valid episode evidence (use check_evidence_exists).
3. **Maturity audit**: Check if maturity levels are consistent with evidence count (use check_maturity_consistency).
4. **Snapshot**: Record snapshots of entries you're about to change (use record_snapshot).
5. **Deprecate**: Soft-deprecate entries with no remaining evidence or very low confidence (use deprecate_entry).
6. **Purge old data**: Remove processed frames, audio, and OS events older than retention period.

Be conservative — only merge entries that are clearly duplicates.
Only deprecate entries with zero evidence and confidence < 0.1.

Output a brief summary of what you did when finished."""


def _build_gc_prompt() -> str:
    """Build GC prompt with manifest source info."""
    from engine.infrastructure.etl.sources.manifest_registry import get_global_registry
    registry = get_global_registry()
    extra = ""
    if registry:
        for m in registry.all_manifests():
            if m.gc:
                prompt = m.gc.get("prompt", "")
                if prompt:
                    retention = m.gc.get("retention_days_default", 14)
                    try:
                        extra += f"\n\n### {m.display_name}\n{prompt.format(retention_days=retention)}"
                    except (KeyError, IndexError):
                        extra += f"\n\n### {m.display_name}\n{prompt}"
    if extra:
        return GC_PROMPT + "\n\n## Source-specific GC guidelines" + extra
    return GC_PROMPT
