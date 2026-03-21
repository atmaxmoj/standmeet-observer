"""Tests for confidence time decay."""

from datetime import datetime, timedelta, timezone
import pytest
from engine.infrastructure.persistence.models import PlaybookEntry, Routine
from engine.infrastructure.pipeline.decay import decay_confidence


@pytest.fixture
def session(sync_session):
    return sync_session


def _insert(session, name, confidence, last_evidence_at=None):
    session.add(PlaybookEntry(name=name, confidence=confidence, last_evidence_at=last_evidence_at))
    session.commit()


class TestDecayConfidence:
    def test_empty_db(self, session):
        assert decay_confidence(session) == 0

    def test_recent_evidence_no_decay(self, session):
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        _insert(session, "fresh-entry", 0.8, last_evidence_at=recent)
        assert decay_confidence(session) == 0
        row = session.query(PlaybookEntry).first()
        session.refresh(row)
        assert row.confidence == 0.8

    def test_old_evidence_decays(self, session):
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=45)).isoformat()
        _insert(session, "old-entry", 0.8, last_evidence_at=old)
        assert decay_confidence(session) == 1
        row = session.query(PlaybookEntry).first()
        session.refresh(row)
        # 45 days: factor = max(0.3, 1.0 - 45/90) = 0.5
        assert abs(row.confidence - 0.4) < 0.01

    def test_very_old_hits_floor(self, session):
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=180)).isoformat()
        _insert(session, "ancient-entry", 0.8, last_evidence_at=old)
        assert decay_confidence(session) == 1
        row = session.query(PlaybookEntry).first()
        session.refresh(row)
        # > 90 days: factor = 0.3 (floor)
        assert abs(row.confidence - 0.24) < 0.01  # 0.8 * 0.3

    def test_no_evidence_date_max_decay(self, session):
        _insert(session, "no-evidence", 0.8, last_evidence_at=None)
        assert decay_confidence(session) == 1
        row = session.query(PlaybookEntry).first()
        session.refresh(row)
        # No evidence date: days_since = 90, factor = 0.3 (floor)
        assert abs(row.confidence - 0.24) < 0.01

    def test_multiple_entries(self, session):
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)).isoformat()
        _insert(session, "fresh", 0.8, last_evidence_at=recent)
        _insert(session, "stale", 0.6, last_evidence_at=old)
        updated = decay_confidence(session)
        assert updated == 1  # only stale one decayed

    def test_decay_math_30_days(self, session):
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)).isoformat()
        _insert(session, "entry", 1.0, last_evidence_at=old)
        decay_confidence(session)
        row = session.query(PlaybookEntry).first()
        session.refresh(row)
        # 30 days: factor = max(0.3, 1.0 - 30/90) = 0.6667
        expected = 1.0 * (1.0 - 30 / 90)
        assert abs(row.confidence - expected) < 0.01


def _insert_routine(session, name, confidence, updated_at=None):
    r = Routine(name=name, confidence=confidence)
    if updated_at:
        r.updated_at = updated_at
    session.add(r)
    session.commit()


class TestRoutineDecay:
    def test_empty_db(self, session):
        from engine.infrastructure.pipeline.decay import decay_routines
        assert decay_routines(session) == 0

    def test_recent_routine_no_decay(self, session):
        from engine.infrastructure.pipeline.decay import decay_routines
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        _insert_routine(session, "fresh-routine", 0.8, updated_at=recent)
        assert decay_routines(session) == 0
        row = session.query(Routine).first()
        session.refresh(row)
        assert row.confidence == 0.8

    def test_old_routine_decays(self, session):
        from engine.infrastructure.pipeline.decay import decay_routines
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=45)).isoformat()
        _insert_routine(session, "old-routine", 0.8, updated_at=old)
        assert decay_routines(session) == 1
        row = session.query(Routine).first()
        session.refresh(row)
        # 45 days: factor = max(0.3, 1.0 - 45/90) = 0.5
        assert abs(row.confidence - 0.4) < 0.01

    def test_very_old_routine_hits_floor(self, session):
        from engine.infrastructure.pipeline.decay import decay_routines
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=180)).isoformat()
        _insert_routine(session, "ancient-routine", 0.8, updated_at=old)
        assert decay_routines(session) == 1
        row = session.query(Routine).first()
        session.refresh(row)
        assert abs(row.confidence - 0.24) < 0.01
