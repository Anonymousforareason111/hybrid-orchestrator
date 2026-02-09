"""Tests for session storage."""

import pytest
from datetime import datetime, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage import SessionStore, Session, Activity, SessionStatus


class TestSessionStore:
    """Test SessionStore CRUD operations."""

    def setup_method(self):
        """Fresh in-memory store for each test."""
        self.store = SessionStore(":memory:")

    def test_create_session(self):
        """Creating a session returns a valid Session object."""
        session = self.store.create_session(
            metadata={"test": "value"},
            external_id="ext_123",
        )

        assert session.token.startswith("ses_")
        assert session.external_id == "ext_123"
        assert session.metadata == {"test": "value"}
        assert session.status == SessionStatus.ACTIVE

    def test_get_session(self):
        """Can retrieve a session by token."""
        created = self.store.create_session()
        retrieved = self.store.get_session(created.token)

        assert retrieved is not None
        assert retrieved.token == created.token

    def test_get_session_not_found(self):
        """Returns None for nonexistent session."""
        result = self.store.get_session("ses_doesnotexist")
        assert result is None

    def test_get_session_by_external_id(self):
        """Can retrieve session by external ID."""
        self.store.create_session(external_id="vapi_call_abc")
        retrieved = self.store.get_session_by_external_id("vapi_call_abc")

        assert retrieved is not None
        assert retrieved.external_id == "vapi_call_abc"

    def test_update_session_status(self):
        """Can update session status."""
        session = self.store.create_session()
        updated = self.store.update_session(
            session.token,
            status=SessionStatus.COMPLETED,
        )

        assert updated is not None
        assert updated.status == SessionStatus.COMPLETED

    def test_update_session_metadata_merges(self):
        """Updating metadata merges with existing."""
        session = self.store.create_session(metadata={"a": 1})
        self.store.update_session(session.token, metadata={"b": 2})
        retrieved = self.store.get_session(session.token)

        assert retrieved.metadata == {"a": 1, "b": 2}

    def test_update_session_with_session_object(self):
        """Can pass Session object directly to update."""
        session = self.store.create_session()
        session.metadata["updated"] = True
        session.status = SessionStatus.ABANDONED

        self.store.update_session(session)
        retrieved = self.store.get_session(session.token)

        assert retrieved.metadata["updated"] is True
        assert retrieved.status == SessionStatus.ABANDONED


class TestActivities:
    """Test activity tracking."""

    def setup_method(self):
        self.store = SessionStore(":memory:")
        self.session = self.store.create_session()

    def test_add_activity(self):
        """Can add activity to session."""
        activity = self.store.add_activity(
            session_token=self.session.token,
            activity_type="field_change",
            data={"field_id": "email", "value": "test@example.com"},
        )

        assert activity.id is not None
        assert activity.activity_type == "field_change"
        assert activity.data["field_id"] == "email"

    def test_get_activities(self):
        """Can retrieve activities for session."""
        self.store.add_activity(self.session.token, "type_a", {"n": 1})
        self.store.add_activity(self.session.token, "type_b", {"n": 2})
        self.store.add_activity(self.session.token, "type_a", {"n": 3})

        activities = self.store.get_activities(self.session.token)
        assert len(activities) == 3

    def test_get_activities_with_type_filter(self):
        """Can filter activities by type."""
        self.store.add_activity(self.session.token, "type_a", {})
        self.store.add_activity(self.session.token, "type_b", {})
        self.store.add_activity(self.session.token, "type_a", {})

        activities = self.store.get_activities(
            self.session.token, activity_type="type_a"
        )
        assert len(activities) == 2

    def test_get_activities_with_limit(self):
        """Can limit number of activities returned."""
        for i in range(10):
            self.store.add_activity(self.session.token, "test", {"n": i})

        activities = self.store.get_activities(self.session.token, limit=3)
        assert len(activities) == 3

    def test_session_includes_activities(self):
        """Session can include activities when retrieved."""
        self.store.add_activity(self.session.token, "test", {})
        self.store.add_activity(self.session.token, "test", {})

        session = self.store.get_session(self.session.token, include_activities=True)
        assert len(session.activities) == 2


class TestSessionExpiry:
    """Test session expiration and cleanup."""

    def setup_method(self):
        self.store = SessionStore(":memory:")

    def test_get_active_sessions_excludes_expired(self):
        """Active sessions query excludes expired ones."""
        # Create a session that's already expired
        session = self.store.create_session()

        # Manually expire it by updating expires_at
        with self.store._get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                ((datetime.utcnow() - timedelta(hours=1)).isoformat(), session.token),
            )

        active = self.store.get_active_sessions()
        assert len(active) == 0

    def test_cleanup_expired_returns_deleted(self):
        """Cleanup returns list of expired sessions."""
        session = self.store.create_session()

        # Expire it
        with self.store._get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                ((datetime.utcnow() - timedelta(hours=1)).isoformat(), session.token),
            )

        expired = self.store.cleanup_expired()
        assert len(expired) == 1
        assert expired[0].token == session.token

    def test_cleanup_deletes_activities_too(self):
        """Cleaning up session also deletes its activities."""
        session = self.store.create_session()
        self.store.add_activity(session.token, "test", {})

        # Expire and cleanup
        with self.store._get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                ((datetime.utcnow() - timedelta(hours=1)).isoformat(), session.token),
            )

        self.store.cleanup_expired()

        # Activities should be gone too
        activities = self.store.get_activities(session.token)
        assert len(activities) == 0


class TestSessionModel:
    """Test Session dataclass behavior."""

    def test_seconds_since_activity_with_activities(self):
        """seconds_since_activity returns time since last activity."""
        session = Session()
        session.activities = [
            Activity(
                session_id=session.token,
                activity_type="test",
                created_at=datetime.utcnow() - timedelta(seconds=30),
            )
        ]

        assert session.seconds_since_activity is not None
        assert 29 <= session.seconds_since_activity <= 31

    def test_seconds_since_activity_no_activities(self):
        """seconds_since_activity returns None when no activities."""
        session = Session()
        assert session.seconds_since_activity is None

    def test_is_expired(self):
        """is_expired returns True for expired sessions."""
        session = Session()
        session.expires_at = datetime.utcnow() - timedelta(hours=1)
        assert session.is_expired is True

        session.expires_at = datetime.utcnow() + timedelta(hours=1)
        assert session.is_expired is False
