"""
Trigger models for defining intervention rules.

Triggers detect patterns in session activity and fire actions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Callable


class ConditionType(Enum):
    """Types of conditions that can trigger actions."""
    NO_ACTIVITY = "no_activity"          # No activity for N seconds
    FIELD_CHANGED = "field_changed"      # Specific field was changed
    FIELD_ERROR = "field_error"          # Field changed multiple times (user struggling)
    STATUS_CHANGED = "status_changed"    # Session status changed
    CUSTOM = "custom"                    # Custom condition function


class ActionType(Enum):
    """Types of actions that can be triggered."""
    VOICE_PROMPT = "voice_prompt"        # Speak a message via voice channel
    SMS = "sms"                          # Send SMS message
    EMAIL = "email"                      # Send email
    DASHBOARD_ALERT = "dashboard_alert"  # Alert human agents
    WEBHOOK = "webhook"                  # Call external webhook
    CUSTOM = "custom"                    # Custom action function


@dataclass
class TriggerCondition:
    """
    A condition that determines when a trigger fires.

    Examples:
        # Fire if no activity for 2 minutes
        TriggerCondition(
            type=ConditionType.NO_ACTIVITY,
            params={"duration_seconds": 120}
        )

        # Fire if same field changed 3 times in 60 seconds
        TriggerCondition(
            type=ConditionType.FIELD_ERROR,
            params={"field_pattern": "*dob*", "times": 3, "within_seconds": 60}
        )
    """
    type: ConditionType
    params: dict = field(default_factory=dict)

    # For custom conditions
    custom_fn: Optional[Callable] = None


@dataclass
class TriggerAction:
    """
    An action to take when a trigger fires.

    Examples:
        # Send voice prompt
        TriggerAction(
            type=ActionType.VOICE_PROMPT,
            params={"message": "Need any help with that field?"}
        )

        # Alert dashboard
        TriggerAction(
            type=ActionType.DASHBOARD_ALERT,
            params={"priority": "high", "message": "Customer stuck for 5+ minutes"}
        )
    """
    type: ActionType
    params: dict = field(default_factory=dict)

    # For custom actions
    custom_fn: Optional[Callable] = None


@dataclass
class Trigger:
    """
    A trigger defines when and how to intervene in a session.

    Triggers are evaluated against sessions. When conditions match,
    actions are executed.
    """
    name: str
    condition: TriggerCondition
    action: TriggerAction

    # Limits to prevent spam
    max_fires_per_session: int = 1          # How many times this trigger can fire per session
    cooldown_seconds: int = 60              # Minimum time between fires

    # Optional filter
    session_filter: Optional[Callable] = None  # Function to filter which sessions this applies to

    # Tracking (set by engine)
    fires_count: dict = field(default_factory=dict)  # session_token -> count
    last_fired: dict = field(default_factory=dict)   # session_token -> datetime


@dataclass
class TriggerResult:
    """Result of evaluating a trigger against a session."""
    trigger_name: str
    session_token: str
    fired: bool
    action_type: Optional[ActionType] = None
    action_params: Optional[dict] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
