"""
Console channel for testing and debugging.

Prints messages to stdout instead of sending them.
"""

import logging
from datetime import datetime
import uuid

from .base import Channel, ChannelConfig, ChannelType, Message, SendResult

logger = logging.getLogger(__name__)


class ConsoleChannel(Channel):
    """
    A channel that prints messages to the console.

    Useful for testing and debugging without setting up real channels.
    """

    def __init__(self, config: ChannelConfig = None):
        if config is None:
            config = ChannelConfig(type=ChannelType.CONSOLE)
        super().__init__(config)
        self.sent_messages: list[Message] = []

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.CONSOLE

    async def send(self, message: Message) -> SendResult:
        """Print the message to console."""
        timestamp = datetime.utcnow().isoformat()
        message_id = str(uuid.uuid4())[:8]

        print(f"\n{'='*60}")
        print(f"[CONSOLE CHANNEL] Message {message_id}")
        print(f"{'='*60}")
        print(f"Time:      {timestamp}")
        print(f"Recipient: {message.recipient.name or message.recipient.id}")
        print(f"Urgency:   {message.urgency}")
        print(f"Content:   {message.content}")
        if message.metadata:
            print(f"Metadata:  {message.metadata}")
        print(f"{'='*60}\n")

        # Store for testing
        self.sent_messages.append(message)

        logger.info(f"Console message sent: {message_id}")

        return SendResult(
            success=True,
            channel_type=self.channel_type,
            message_id=message_id,
        )

    def clear_history(self):
        """Clear sent message history."""
        self.sent_messages.clear()
