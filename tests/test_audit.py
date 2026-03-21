"""Tests for evidence audit tools + playbook snapshots."""

import json
import pytest
from engine.infrastructure.persistence.models import PlaybookEntry, Episode, PlaybookHistory
from engine.infrastructure.agent.repository import (
    check_evidence_exists,
    check_maturity_consistency,
    record_snapshot,
    deprecate_entry,
)


@pytest.fixture
def session(sync_session):
    return sync_session


def _insert_playbook(session, name, confidence=0.5, maturity="nascent", evidence="[]"):
    session.add(PlaybookEntry(name=name, confidence=confidence, maturity=maturity, evidence=evidence))
    session.commit()


def _insert_episode(session, episode_id=None):
    session.add(Episode(summary="test episode", started_at="t1", ended_at="t2"))
    session.commit()


class TestCheckEvidenceExists:
    def test_entry_not_found(self, session):
        result = check_evidence_exists(session, "nonexistent")
        assert "error" in result

    def test_empty_evidence(self, session):
        _insert_playbook(session, "test-entry", evidence="[]")
        result = check_evidence_exists(session, "test-entry")
        assert result["all_exist"] is True
        assert result["missing"] == []

    def test_all_evidence_exists(self, session):
        # Insert 3 episodes
        for _ in range(3):
            _insert_episode(session)
        _insert_playbook(session, "test-entry", evidence="[1, 2, 3]")
        result = check_evidence_exists(session, "test-entry")
        assert result["all_exist"] is True
        assert result["missing"] == []

    def test_orphan_evidence(self, session):
        _insert_episode(session)  # id=1
        _insert_playbook(session, "test-entry", evidence="[1, 99, 100]")
        result = check_evidence_exists(session, "test-entry")
        assert result["all_exist"] is False
        assert set(result["missing"]) == {99, 100}


class TestCheckMaturityConsistency:
    def test_empty_db(self, session):
        assert check_maturity_consistency(session) == []

    def test_consistent_entries(self, session):
        _insert_playbook(session, "nascent-entry", maturity="nascent", evidence="[1]")
        _insert_playbook(session, "developing-ok", maturity="developing", evidence="[1,2,3]")
        assert check_maturity_consistency(session) == []

    def test_mature_with_few_evidence(self, session):
        _insert_playbook(session, "bad-mature", maturity="mature", evidence="[1, 2]")
        results = check_maturity_consistency(session)
        assert len(results) == 1
        assert results[0]["name"] == "bad-mature"
        assert "mature" in results[0]["issue"]

    def test_developing_with_few_evidence(self, session):
        _insert_playbook(session, "bad-developing", maturity="developing", evidence="[1]")
        results = check_maturity_consistency(session)
        assert len(results) == 1

    def test_mastered_with_enough_evidence(self, session):
        evidence = json.dumps(list(range(1, 11)))
        _insert_playbook(session, "good-mastered", maturity="mastered", evidence=evidence)
        assert check_maturity_consistency(session) == []


class TestRecordSnapshot:
    def test_records_snapshot(self, session):
        _insert_playbook(session, "test-entry", confidence=0.7, maturity="developing")
        result = record_snapshot(session, "test-entry", reason="before merge")
        assert result["name"] == "test-entry"
        assert result["snapshot_confidence"] == 0.7

        history = session.query(PlaybookHistory).filter_by(playbook_name="test-entry").all()
        assert len(history) == 1
        assert history[0].change_reason == "before merge"

    def test_not_found(self, session):
        result = record_snapshot(session, "nonexistent")
        assert "error" in result


class TestDeprecateEntry:
    def test_deprecates(self, session):
        _insert_playbook(session, "old-pattern", confidence=0.8, maturity="mature")
        result = deprecate_entry(session, 1, reason="superseded")
        assert result["deprecated"] is True

        row = session.query(PlaybookEntry).filter_by(id=1).first()
        assert row.confidence == 0.0
        assert row.maturity == "nascent"

        # Should have recorded a snapshot
        history = session.query(PlaybookHistory).all()
        assert len(history) == 1
        assert "superseded" in history[0].change_reason

    def test_not_found(self, session):
        result = deprecate_entry(session, 999)
        assert "error" in result
