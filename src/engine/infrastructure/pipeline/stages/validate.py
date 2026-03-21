"""Deterministic validation for LLM JSON outputs + retry logic.

Layer 2 (architectural constraints): agent output must conform to schema
or get rejected with error feedback for retry.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

VALID_MATURITIES = {"nascent", "developing", "mature", "mastered"}
MAX_EPISODES_PER_WINDOW = 5
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


class ValidationError(Exception):
    """Raised when LLM output fails validation."""
    pass


def strip_fence(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def validate_episodes(text: str) -> list[dict]:
    """Validate episode JSON from Haiku.

    Required fields: summary, apps (list), started_at, ended_at.
    Truncates to MAX_EPISODES_PER_WINDOW.
    """
    text = strip_fence(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON: {e}")

    if not isinstance(data, list):
        data = [data]

    if not data:
        raise ValidationError("Result is empty — expected at least one episode")

    for i, ep in enumerate(data):
        for field in ("summary", "apps", "started_at", "ended_at"):
            if field not in ep:
                raise ValidationError(
                    f"Episode {i}: missing required field '{field}'"
                )
        if not isinstance(ep["apps"], list):
            raise ValidationError(
                f"Episode {i}: 'apps' must be a list, got {type(ep['apps']).__name__}"
            )

    if len(data) > MAX_EPISODES_PER_WINDOW:
        logger.warning(
            "Truncating %d episodes to %d", len(data), MAX_EPISODES_PER_WINDOW,
        )
        data = data[:MAX_EPISODES_PER_WINDOW]

    return data


def validate_playbooks(text: str) -> list[dict]:
    """Validate playbook JSON from Opus.

    Required: name (kebab-case), confidence (0-1), maturity (enum), evidence (int list).
    Clamps confidence to [0.0, 1.0].
    """
    text = strip_fence(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON: {e}")

    if not isinstance(data, list):
        data = [data]

    for i, entry in enumerate(data):
        if "name" not in entry:
            raise ValidationError(f"Entry {i}: missing required field 'name'")

        if not KEBAB_RE.match(entry["name"]):
            raise ValidationError(
                f"Entry {i}: name '{entry['name']}' is not kebab-case "
                f"(expected pattern: lowercase-words-joined-by-hyphens)"
            )

        confidence = entry.get("confidence", 0.5)
        entry["confidence"] = max(0.0, min(1.0, float(confidence)))

        maturity = entry.get("maturity", "nascent")
        if maturity not in VALID_MATURITIES:
            raise ValidationError(
                f"Entry {i}: maturity '{maturity}' not in {VALID_MATURITIES}"
            )

        evidence = entry.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValidationError(
                f"Entry {i}: 'evidence' must be a list of int IDs, "
                f"got {type(evidence).__name__}"
            )

    return data


def with_retry(
    llm_fn,
    validator,
    max_retries: int = 1,
    initial_prompt: str = "",
) -> list[dict]:
    """Call LLM, validate output, retry with error feedback on failure.

    Args:
        llm_fn: callable(prompt) -> str. First call gets initial_prompt (or "").
        validator: callable(text) -> list[dict]. Raises ValidationError on failure.
        max_retries: number of retry attempts after first failure.
        initial_prompt: prompt for the first LLM call.
    """
    prompt = initial_prompt
    last_error = None

    for attempt in range(1 + max_retries):
        text = llm_fn(prompt)
        try:
            return validator(text)
        except ValidationError as e:
            last_error = e
            logger.warning(
                "Validation failed (attempt %d/%d): %s",
                attempt + 1, 1 + max_retries, e,
            )
            # Build retry prompt with error feedback
            prompt = (
                f"Your previous output had a validation error:\n"
                f"Error: {e}\n\n"
                f"Your output was:\n{text[:500]}\n\n"
                f"Please fix the error and output valid JSON."
            )

    raise last_error
