"""
Session store for persistent state management.

This implementation uses SQLite by default for simplicity.
For production, swap to PostgreSQL or another database.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from .models import Session, Activity, SessionStatus


class SessionStore:
    """
    Persistent storage for sessions and activities.

    Design principles:
    - Sessions are the unit of work
    - Activities are append-only (never update, always insert)
    - External IDs enable lookup by third-party references
    - Automatic cleanup of expired sessions
    """

    def __init__(self, db_path: str = "sessions.db"):
        """
        Initialize the session store.

        Args:
            db_path: Path to SQLite database file. Use ":memory:" for testing.
        """
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._persistent_conn = None

        # For in-memory databases, keep a persistent connection
        if self._is_memory:
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row

        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    external_id TEXT UNIQUE,
                    status TEXT DEFAULT 'active',
                    metadata TEXT DEFAULT '{}',
                    pending_action TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    expires_at TEXT
                );

                CREATE TABLE IF NOT EXISTS activities (
                    id TEXT PRIMARY KEY,
                    session_token TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    created_at TEXT,
                    FOREIGN KEY (session_token) REFERENCES sessions(token) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_external ON sessions(external_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
                CREATE INDEX IF NOT EXISTS idx_activities_session ON activities(session_token);
                CREATE INDEX IF NOT EXISTS idx_activities_created ON activities(created_at);
            """)

    @contextmanager
    def _get_connection(self):
        """Get a database connection with proper cleanup."""
        if self._is_memory and self._persistent_conn:
            # For in-memory, reuse the persistent connection
            # Enable foreign keys for CASCADE to work
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")
            yield self._persistent_conn
            self._persistent_conn.commit()
        else:
            # For file-based, create new connection each time
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            # Enable foreign keys for CASCADE to work
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def create_session(
        self,
        metadata: Optional[dict] = None,
        external_id: Optional[str] = None,
        ttl_hours: int = 24,
    ) -> Session:
        """
        Create a new session.

        Args:
            metadata: Domain-specific data to store with the session.
            external_id: Optional reference to external system (must be unique).
            ttl_hours: Hours until session expires.

        Returns:
            The created session.
        """
        session = Session(
            external_id=external_id,
            metadata=metadata or {},
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, external_id, status, metadata, pending_action, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.token,
                    session.external_id,
                    session.status.value,
                    json.dumps(session.metadata),
                    json.dumps(session.pending_action) if session.pending_action else None,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.expires_at.isoformat(),
                ),
            )

        return session

    def get_session(self, token: str, include_activities: bool = False) -> Optional[Session]:
        """
        Get a session by token.

        Args:
            token: Session token.
            include_activities: If True, load all activities for the session.

        Returns:
            Session if found, None otherwise.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token = ?", (token,)
            ).fetchone()

            if not row:
                return None

            session = self._row_to_session(row)

            if include_activities:
                session.activities = self.get_activities(token)

            return session

    def get_session_by_external_id(
        self, external_id: str, include_activities: bool = False
    ) -> Optional[Session]:
        """Get a session by its external ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE external_id = ?", (external_id,)
            ).fetchone()

            if not row:
                return None

            session = self._row_to_session(row)

            if include_activities:
                session.activities = self.get_activities(session.token)

            return session

    def get_active_sessions(self, include_activities: bool = False) -> list[Session]:
        """Get all active (non-expired) sessions."""
        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                WHERE status = 'active' AND expires_at > ?
                ORDER BY created_at DESC
                """,
                (now,),
            ).fetchall()

            sessions = [self._row_to_session(row) for row in rows]

            if include_activities:
                for session in sessions:
                    session.activities = self.get_activities(session.token)

            return sessions

    def update_session(
        self,
        session_or_token,
        status: Optional[SessionStatus] = None,
        metadata: Optional[dict] = None,
        pending_action: Optional[dict] = None,
    ) -> Optional[Session]:
        """
        Update a session.

        Args:
            session_or_token: Session object or token string.
            status: New status (if provided, ignored if Session object passed).
            metadata: Updated metadata (merged with existing, ignored if Session object passed).
            pending_action: Pending action to set (ignored if Session object passed).

        Returns:
            Updated session, or None if not found.
        """
        # Support passing a Session object directly
        if isinstance(session_or_token, Session):
            session = session_or_token
            token = session.token
        else:
            token = session_or_token
            session = self.get_session(token)
            if not session:
                return None

            # Merge metadata if provided
            if metadata:
                session.metadata.update(metadata)

            # Update fields
            if status:
                session.status = status
            if pending_action is not None:
                session.pending_action = pending_action

        session.updated_at = datetime.utcnow()

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, metadata = ?, pending_action = ?, updated_at = ?
                WHERE token = ?
                """,
                (
                    session.status.value,
                    json.dumps(session.metadata),
                    json.dumps(session.pending_action) if session.pending_action else None,
                    session.updated_at.isoformat(),
                    token,
                ),
            )

        return session

    def add_activity(
        self,
        session_token: str,
        activity_type: str,
        data: Optional[dict] = None,
    ) -> Activity:
        """
        Add an activity to a session.

        Activities are append-only. This is intentional for auditability.

        Args:
            session_token: Session to add activity to.
            activity_type: Type of activity (e.g., "screen_update", "user_action").
            data: Activity-specific data.

        Returns:
            The created activity.
        """
        activity = Activity(
            session_id=session_token,
            activity_type=activity_type,
            data=data or {},
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO activities (id, session_token, activity_type, data, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    activity.id,
                    session_token,
                    activity.activity_type,
                    json.dumps(activity.data),
                    activity.created_at.isoformat(),
                ),
            )

            # Update session's updated_at timestamp
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE token = ?",
                (datetime.utcnow().isoformat(), session_token),
            )

        return activity

    def get_activities(
        self,
        session_token: str,
        limit: Optional[int] = None,
        activity_type: Optional[str] = None,
    ) -> list[Activity]:
        """
        Get activities for a session.

        Args:
            session_token: Session token.
            limit: Maximum number of activities to return (most recent first).
            activity_type: Filter by activity type.

        Returns:
            List of activities, ordered by created_at descending.
        """
        query = "SELECT * FROM activities WHERE session_token = ?"
        params = [session_token]

        if activity_type:
            query += " AND activity_type = ?"
            params.append(activity_type)

        query += " ORDER BY created_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_activity(row) for row in rows]

    def cleanup_expired(self) -> list[Session]:
        """
        Remove expired sessions and their activities.

        Returns:
            List of expired sessions that were deleted.
        """
        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            # Get expired sessions before deleting
            rows = conn.execute(
                "SELECT * FROM sessions WHERE expires_at <= ?", (now,)
            ).fetchall()
            expired = [self._row_to_session(row) for row in rows]

            # Delete (activities cascade)
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))

            return expired

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        """Convert a database row to a Session object."""
        return Session(
            token=row["token"],
            external_id=row["external_id"],
            status=SessionStatus(row["status"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            pending_action=json.loads(row["pending_action"]) if row["pending_action"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    def _row_to_activity(self, row: sqlite3.Row) -> Activity:
        """Convert a database row to an Activity object."""
        return Activity(
            id=row["id"],
            session_id=row["session_token"],
            activity_type=row["activity_type"],
            data=json.loads(row["data"]) if row["data"] else {},
            created_at=datetime.fromisoformat(row["created_at"]),
        )
