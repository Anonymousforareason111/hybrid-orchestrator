"""
Base channel interface for multi-channel communication.

Channels are responsible for delivering messages to recipients.
Each channel type (voice, SMS, email, etc.) implements this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class ChannelType(Enum):
    """Standard channel types."""
    VOICE = "voice"
    SMS = "sms"
    EMAIL = "email"
    SLACK = "slack"
    DASHBOARD = "dashboard"
    WEBHOOK = "webhook"
    CONSOLE = "console"  # For testing


@dataclass
class ChannelConfig:
    """Configuration for a channel."""
    type: ChannelType
    enabled: bool = True
    config: dict = field(default_factory=dict)

    # Priority for channel selection (lower = higher priority)
    priority: int = 100


@dataclass
class Recipient:
    """A message recipient."""
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    slack_id: Optional[str] = None
    is_available: bool = True
    preferred_channel: Optional[ChannelType] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Message:
    """A message to be sent via a channel."""
    content: str
    recipient: Recipient
    channel_type: Optional[ChannelType] = None
    urgency: str = "normal"  # low, normal, high, critical
    metadata: dict = field(default_factory=dict)


@dataclass
class SendResult:
    """Result of sending a message."""
    success: bool
    channel_type: ChannelType
    message_id: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class Channel(ABC):
    """
    Abstract base class for communication channels.

    Implement this interface to add new channel types.
    """

    def __init__(self, config: ChannelConfig):
        self.config = config
        self.enabled = config.enabled

    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """Return the channel type."""
        pass

    @abstractmethod
    async def send(self, message: Message) -> SendResult:
        """
        Send a message via this channel.

        Args:
            message: The message to send.

        Returns:
            SendResult indicating success/failure.
        """
        pass

    def can_reach(self, recipient: Recipient) -> bool:
        """
        Check if this channel can reach the recipient.

        Override in subclasses for channel-specific checks.
        """
        return self.enabled

    def matches_urgency(self, urgency: str) -> bool:
        """
        Check if this channel is appropriate for the urgency level.

        Default implementation - override for channel-specific logic.
        """
        return True
