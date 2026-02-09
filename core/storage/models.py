"""
Data models for session state.

These models are database-agnostic. The SessionStore handles persistence.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional
import uuid


class SessionStatus(Enum):
    """Session lifecycle states."""
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class Activity:
    """
    A single activity record in a session.

    Activities are append-only. Never update; always insert new records.
    This enables replay and debugging.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    activity_type: str = ""  # e.g., "screen_update", "field_change", "user_action"
    data: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "activity_type": self.activity_type,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Activity":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            session_id=data.get("session_id", ""),
            activity_type=data.get("activity_type", ""),
            data=data.get("data", {}),
            created_at=datetime.fromisoformat(data["created_at"])
                if "created_at" in data else datetime.utcnow(),
        )


@dataclass
class Session:
    """
    A session represents a single interaction flow.

    Key design decisions:
    - Token is the primary key (not auto-increment). Enables direct lookup.
    - External references stored explicitly (e.g., external_id for third-party systems).
    - Expiration built in. Sessions auto-expire after TTL.
    - Metadata is flexible (dict). Domain-specific data goes here.
    """
    token: str = field(default_factory=lambda: f"ses_{uuid.uuid4().hex[:16]}")
    external_id: Optional[str] = None  # Reference to external system

    # Basic info
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: dict = field(default_factory=dict)

    # Pending actions (e.g., UI commands to be executed)
    pending_action: Optional[dict] = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=24))

    # Activity log (populated by SessionStore)
    activities: list[Activity] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @property
    def is_active(self) -> bool:
        return self.status == SessionStatus.ACTIVE and not self.is_expired

    @property
    def last_activity(self) -> Optional[Activity]:
        if self.activities:
            return max(self.activities, key=lambda a: a.created_at)
        return None

    @property
    def seconds_since_activity(self) -> Optional[float]:
        if self.last_activity:
            delta = datetime.utcnow() - self.last_activity.created_at
            return delta.total_seconds()
        return None

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "external_id": self.external_id,
            "status": self.status.value,
            "metadata": self.metadata,
            "pending_action": self.pending_action,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            token=data.get("token", f"ses_{uuid.uuid4().hex[:16]}"),
            external_id=data.get("external_id"),
            status=SessionStatus(data.get("status", "active")),
            metadata=data.get("metadata", {}),
            pending_action=data.get("pending_action"),
            created_at=datetime.fromisoformat(data["created_at"])
                if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"])
                if "updated_at" in data else datetime.utcnow(),
            expires_at=datetime.fromisoformat(data["expires_at"])
                if "expires_at" in data else datetime.utcnow() + timedelta(hours=24),
        )
