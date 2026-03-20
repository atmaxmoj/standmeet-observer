"""Tests for pipeline validation + retry logic."""

import json
import pytest
from engine.pipeline.stages.validate import (
    validate_episodes,
    validate_playbooks,
    with_retry,
    ValidationError,
)


class TestValidateEpisodes:
    def test_valid_json(self):
        raw = json.dumps([{
            "summary": "Wrote a test",
            "apps": ["VSCode"],
            "started_at": "2026-03-15T10:00:00Z",
            "ended_at": "2026-03-15T10:30:00Z",
        }])
        result = validate_episodes(raw)
        assert len(result) == 1
        assert result[0]["summary"] == "Wrote a test"

    def test_strips_code_fence(self):
        raw = '```json\n[{"summary": "test", "apps": ["x"], "started_at": "t1", "ended_at": "t2"}]\n```'
        result = validate_episodes(raw)
        assert len(result) == 1

    def test_missing_required_field(self):
        raw = json.dumps([{"apps": ["x"], "started_at": "t1", "ended_at": "t2"}])
        with pytest.raises(ValidationError, match="summary"):
            validate_episodes(raw)

    def test_missing_apps(self):
        raw = json.dumps([{"summary": "x", "started_at": "t1", "ended_at": "t2"}])
        with pytest.raises(ValidationError, match="apps"):
            validate_episodes(raw)

    def test_missing_started_at(self):
        raw = json.dumps([{"summary": "x", "apps": [], "ended_at": "t2"}])
        with pytest.raises(ValidationError, match="started_at"):
            validate_episodes(raw)

    def test_missing_ended_at(self):
        raw = json.dumps([{"summary": "x", "apps": [], "started_at": "t1"}])
        with pytest.raises(ValidationError, match="ended_at"):
            validate_episodes(raw)

    def test_apps_must_be_list(self):
        raw = json.dumps([{"summary": "x", "apps": "VSCode", "started_at": "t1", "ended_at": "t2"}])
        with pytest.raises(ValidationError, match="apps.*list"):
            validate_episodes(raw)

    def test_truncates_to_max_5(self):
        episodes = [
            {"summary": f"task {i}", "apps": [], "started_at": "t1", "ended_at": "t2"}
            for i in range(10)
        ]
        result = validate_episodes(json.dumps(episodes))
        assert len(result) == 5

    def test_invalid_json(self):
        with pytest.raises(ValidationError, match="JSON"):
            validate_episodes("not json at all")

    def test_not_a_list(self):
        raw = json.dumps({"summary": "x", "apps": [], "started_at": "t1", "ended_at": "t2"})
        # Single object should be wrapped in list
        result = validate_episodes(raw)
        assert len(result) == 1

    def test_empty_list(self):
        with pytest.raises(ValidationError, match="empty"):
            validate_episodes("[]")


class TestValidatePlaybooks:
    def test_valid_entry(self):
        raw = json.dumps([{
            "name": "morning-coding",
            "confidence": 0.7,
            "maturity": "developing",
            "evidence": [1, 2, 3],
        }])
        result = validate_playbooks(raw)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.7

    def test_confidence_clamped_high(self):
        raw = json.dumps([{
            "name": "test-entry",
            "confidence": 1.5,
            "maturity": "nascent",
            "evidence": [1],
        }])
        result = validate_playbooks(raw)
        assert result[0]["confidence"] == 1.0

    def test_confidence_clamped_low(self):
        raw = json.dumps([{
            "name": "test-entry",
            "confidence": -0.3,
            "maturity": "nascent",
            "evidence": [1],
        }])
        result = validate_playbooks(raw)
        assert result[0]["confidence"] == 0.0

    def test_invalid_maturity(self):
        raw = json.dumps([{
            "name": "test-entry",
            "confidence": 0.5,
            "maturity": "legendary",
            "evidence": [1],
        }])
        with pytest.raises(ValidationError, match="maturity"):
            validate_playbooks(raw)

    def test_valid_maturities(self):
        for mat in ["nascent", "developing", "mature", "mastered"]:
            raw = json.dumps([{
                "name": "test-entry",
                "confidence": 0.5,
                "maturity": mat,
                "evidence": [1],
            }])
            result = validate_playbooks(raw)
            assert result[0]["maturity"] == mat

    def test_evidence_must_be_int_list(self):
        raw = json.dumps([{
            "name": "test-entry",
            "confidence": 0.5,
            "maturity": "nascent",
            "evidence": "not a list",
        }])
        with pytest.raises(ValidationError, match="evidence.*list"):
            validate_playbooks(raw)

    def test_name_must_be_kebab_case(self):
        raw = json.dumps([{
            "name": "Not Kebab Case",
            "confidence": 0.5,
            "maturity": "nascent",
            "evidence": [1],
        }])
        with pytest.raises(ValidationError, match="kebab-case"):
            validate_playbooks(raw)

    def test_valid_kebab_names(self):
        for name in ["simple", "two-words", "three-word-name", "a-b-c-d"]:
            raw = json.dumps([{
                "name": name,
                "confidence": 0.5,
                "maturity": "nascent",
                "evidence": [1],
            }])
            result = validate_playbooks(raw)
            assert result[0]["name"] == name

    def test_strips_code_fence(self):
        raw = '```json\n[{"name": "test", "confidence": 0.5, "maturity": "nascent", "evidence": [1]}]\n```'
        result = validate_playbooks(raw)
        assert len(result) == 1

    def test_missing_name(self):
        raw = json.dumps([{"confidence": 0.5, "maturity": "nascent", "evidence": [1]}])
        with pytest.raises(ValidationError, match="name"):
            validate_playbooks(raw)


class TestWithRetry:
    def test_success_first_try(self):
        call_count = 0

        def llm_fn(prompt):
            nonlocal call_count
            call_count += 1
            return '[{"summary": "x", "apps": [], "started_at": "t1", "ended_at": "t2"}]'

        result = with_retry(llm_fn, validate_episodes, max_retries=1)
        assert len(result) == 1
        assert call_count == 1

    def test_retry_on_first_failure(self):
        call_count = 0

        def llm_fn(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "not valid json"
            return '[{"summary": "x", "apps": [], "started_at": "t1", "ended_at": "t2"}]'

        result = with_retry(llm_fn, validate_episodes, max_retries=1)
        assert len(result) == 1
        assert call_count == 2

    def test_gives_up_after_max_retries(self):
        def llm_fn(prompt):
            return "always bad"

        with pytest.raises(ValidationError):
            with_retry(llm_fn, validate_episodes, max_retries=1)

    def test_error_message_in_retry_prompt(self):
        prompts_received = []

        def llm_fn(prompt):
            prompts_received.append(prompt)
            if len(prompts_received) == 1:
                return '{"bad": "not a list"}'
            return '[{"summary": "x", "apps": [], "started_at": "t1", "ended_at": "t2"}]'

        with_retry(llm_fn, validate_episodes, max_retries=1)
        assert len(prompts_received) == 2
        # Retry prompt should contain error info
        assert "error" in prompts_received[1].lower() or "Error" in prompts_received[1]
