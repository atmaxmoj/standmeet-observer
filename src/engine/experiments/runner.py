"""Experiment runner — full chain L1→L2→L3 inside Docker container.

Each experiment variant is a directory in /app/tests/experiments/prompts/<name>/
containing up to 3 files:
  - episode.txt   (L1: frames → episodes)
  - playbook.txt  (L2: episodes → playbook entries)
  - routine.txt   (L3: episodes + playbook → routines)

Missing files fall back to production prompts.
Uses {context}, {episodes}, {playbooks}, {routines} as placeholders.

Usage: npm run experiment
"""

import json
import logging
import sys
from pathlib import Path

from engine.config import Settings, MODEL_FAST
from engine.infra.llm import create_client
from engine.pipeline.stages.extract import build_context_from_dicts, parse_llm_json

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = Path("/data/experiment_results")
DEFAULT_FIXTURE = Path("/app/tests/experiments/fixtures/frames.json")
PROMPTS_DIR = Path("/app/tests/experiments/prompts")


def _production_prompts() -> dict[str, str]:
    """Load production prompts, converting .format() style to .replace() style."""
    from engine.domain.prompts.episode import EPISODE_PROMPT
    from engine.domain.prompts.playbook import PLAYBOOK_PROMPT
    from engine.domain.prompts.routine import ROUTINE_PROMPT

    def convert(p):
        return p.replace("{{", "{").replace("}}", "}")

    return {
        "episode": convert(EPISODE_PROMPT),
        "playbook": convert(PLAYBOOK_PROMPT),
        "routine": convert(ROUTINE_PROMPT),
    }


def load_variant(name: str, production: dict[str, str]) -> dict[str, str]:
    """Load a prompt variant. Falls back to production for missing layers."""
    variant_dir = PROMPTS_DIR / name
    result = dict(production)  # start with production defaults
    if variant_dir.is_dir():
        for layer in ("episode", "playbook", "routine"):
            f = variant_dir / f"{layer}.txt"
            if f.exists():
                result[layer] = f.read_text()
                logger.info("  [%s] loaded %s.txt", name, layer)
    return result


def discover_variants() -> list[str]:
    """Find all variant directories + always include 'baseline'."""
    variants = ["baseline"]
    if PROMPTS_DIR.exists():
        for d in sorted(PROMPTS_DIR.iterdir()):
            if d.is_dir() and d.name != "baseline":
                variants.append(d.name)
    return variants


def format_episodes_text(episodes: list[dict]) -> str:
    return "\n\n".join(
        f"Episode #{i+1}:\n{json.dumps(ep, ensure_ascii=False)}"
        for i, ep in enumerate(episodes)
    )


def format_playbooks_text(entries: list[dict]) -> str:
    if not entries:
        return "(none yet)"
    return "\n".join(
        f"- **{e.get('name', '?')}**: {e.get('context', '')} → {e.get('action', '')}"
        for e in entries
    )


def save(name: str, data: dict):
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("  saved → %s", path)


def run_chain(llm, context: str, prompts: dict[str, str], name: str):
    """Run full L1→L2→L3 chain with given prompts."""
    logger.info("=== Chain: %s ===", name)

    # L1: Episode extraction
    logger.info("  L1: extracting episodes...")
    prompt_text = prompts["episode"].replace("{context}", context)
    resp1 = llm.complete(prompt_text, MODEL_FAST)
    episodes = parse_llm_json(resp1.text)
    save(f"{name}_L1_episodes", {
        "episodes": episodes, "count": len(episodes),
        "output_tokens": resp1.output_tokens,
    })
    logger.info("  L1: %d episodes, %d tokens", len(episodes), resp1.output_tokens)

    if not episodes:
        logger.warning("  No episodes, skipping L2/L3")
        return

    episodes_text = format_episodes_text(episodes)

    # L2: Playbook distillation
    logger.info("  L2: distilling playbook...")
    prompt_text = (prompts["playbook"]
                   .replace("{episodes}", episodes_text)
                   .replace("{playbooks}", "(none yet — first extraction)"))
    resp2 = llm.complete(prompt_text, MODEL_FAST)
    playbook = parse_llm_json(resp2.text)
    save(f"{name}_L2_playbook", {
        "entries": playbook, "count": len(playbook),
        "output_tokens": resp2.output_tokens,
    })
    logger.info("  L2: %d entries, %d tokens", len(playbook), resp2.output_tokens)

    # L3: Routine composition
    logger.info("  L3: composing routines...")
    prompt_text = (prompts["routine"]
                   .replace("{episodes}", episodes_text)
                   .replace("{playbooks}", format_playbooks_text(playbook))
                   .replace("{routines}", "(none yet)"))
    resp3 = llm.complete(prompt_text, MODEL_FAST)
    routines = parse_llm_json(resp3.text)
    save(f"{name}_L3_routines", {
        "routines": routines, "count": len(routines),
        "output_tokens": resp3.output_tokens,
    })
    logger.info("  L3: %d routines, %d tokens", len(routines), resp3.output_tokens)

    total = resp1.output_tokens + resp2.output_tokens + resp3.output_tokens
    save(f"{name}_summary", {
        "episodes": len(episodes),
        "playbook_entries": len(playbook),
        "routines": len(routines),
        "total_output_tokens": total,
    })
    logger.info("  TOTAL: %d episodes → %d entries → %d routines (%d tokens)",
                len(episodes), len(playbook), len(routines), total)


def main():
    # Args: [fixture_path] [variant_filter]
    fixture_path = DEFAULT_FIXTURE
    variant_filter = None
    for arg in sys.argv[1:]:
        if Path(arg).suffix == ".json" or Path(arg).exists():
            fixture_path = Path(arg)
        else:
            variant_filter = arg
    if not fixture_path.exists():
        logger.error("Fixture not found: %s", fixture_path)
        sys.exit(1)

    settings = Settings()
    llm = create_client(
        api_key=settings.anthropic_api_key,
        auth_token=settings.claude_code_oauth_token,
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
    )

    fixture = json.loads(fixture_path.read_text())
    context = build_context_from_dicts(
        fixture["frames"], fixture.get("audio", []), fixture.get("os_events", []),
    )
    logger.info("Fixture: %d frames, context: %d chars", len(fixture["frames"]), len(context))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    save("context", {"chars": len(context), "fixture": str(fixture_path)})

    production = _production_prompts()
    variants = discover_variants()
    if variant_filter:
        variants = [v for v in variants if v == variant_filter]
        if not variants:
            logger.error("Variant '%s' not found. Available: %s", variant_filter, discover_variants())
            sys.exit(1)
    logger.info("Variants: %s", variants)

    for name in variants:
        prompts = load_variant(name, production)
        try:
            run_chain(llm, context, prompts, name)
        except Exception:
            logger.exception("Chain [%s] FAILED", name)

    logger.info("Done. Results in %s", RESULTS_DIR)


if __name__ == "__main__":
    main()
