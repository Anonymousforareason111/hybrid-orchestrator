"""
Channel module for multi-channel communication.

Pattern 2: Route messages to appropriate channels based on context.
"""

from .hub import ChannelHub
from .base import (
    Channel,
    ChannelConfig,
    ChannelType,
    Message,
    Recipient,
    SendResult,
)
from .console import ConsoleChannel
from .webhook import WebhookChannel
from .email import EmailChannel, EmailChannelError
from .email_listener import EmailAgentListener, EmailEvent, EmailAgentListenerContext

__all__ = [
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
    "EmailAgentListenerContext",
]
