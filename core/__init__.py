"""
Hybrid Human-AI Orchestration Framework

Design patterns for coordinating human workers and AI agents.
"""

__version__ = "0.1.0"
__author__ = "Pavel Sukhachev"
__email__ = "pavel@electromania.llc"

from .orchestrator import Orchestrator
from .storage import SessionStore, Session, Activity, SessionStatus
from .triggers import (
    TriggerEngine,
    Trigger,
    TriggerCondition,
    TriggerAction,
    TriggerResult,
    ConditionType,
    ActionType,
)
from .channels import (
    ChannelHub,
    Channel,
    ChannelConfig,
    ChannelType,
    Message,
    Recipient,
    SendResult,
    ConsoleChannel,
    WebhookChannel,
    EmailChannel,
    EmailChannelError,
    EmailAgentListener,
    EmailEvent,
)

__all__ = [
    # Main orchestrator
    "Orchestrator",
    # Storage
    "SessionStore",
    "Session",
    "Activity",
    "SessionStatus",
    # Triggers
    "TriggerEngine",
    "Trigger",
    "TriggerCondition",
    "TriggerAction",
    "TriggerResult",
    "ConditionType",
    "ActionType",
    # Channels
    "ChannelHub",
    "Channel",
    "ChannelConfig",
    "ChannelType",
    "Message",
    "Recipient",
    "SendResult",
    "ConsoleChannel",
    "WebhookChannel",
    "EmailChannel",
    "EmailChannelError",
    "EmailAgentListener",
    "EmailEvent",
]
