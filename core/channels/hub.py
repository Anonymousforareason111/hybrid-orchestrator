"""
Channel hub for routing messages to appropriate channels.

Pattern 2: Multi-channel communication with intelligent routing.
"""

import logging
from typing import Optional

from .base import (
    Channel,
    ChannelConfig,
    ChannelType,
    Message,
    Recipient,
    SendResult,
)
from ..triggers.models import TriggerResult, ActionType

logger = logging.getLogger(__name__)


# Map action types to channel types
ACTION_TO_CHANNEL: dict[ActionType, ChannelType] = {
    ActionType.VOICE_PROMPT: ChannelType.VOICE,
    ActionType.SMS: ChannelType.SMS,
    ActionType.EMAIL: ChannelType.EMAIL,
    ActionType.DASHBOARD_ALERT: ChannelType.DASHBOARD,
    ActionType.WEBHOOK: ChannelType.WEBHOOK,
}


# Urgency to channel priority mapping
URGENCY_CHANNELS: dict[str, list[ChannelType]] = {
    "critical": [ChannelType.VOICE, ChannelType.SMS, ChannelType.SLACK],
    "high": [ChannelType.SMS, ChannelType.SLACK, ChannelType.EMAIL],
    "normal": [ChannelType.EMAIL, ChannelType.SLACK, ChannelType.DASHBOARD],
    "low": [ChannelType.DASHBOARD, ChannelType.WEBHOOK],
}


class ChannelHub:
    """
    Central hub for routing messages to communication channels.

    Responsibilities:
        - Register and manage channels
        - Route messages based on urgency and recipient preference
        - Execute trigger actions
        - Handle fallback when primary channel fails

    Usage:
        hub = ChannelHub()

        # Register channels
        hub.register(ConsoleChannel())
        hub.register(WebhookChannel(config))

        # Send a message
        result = await hub.send(message)

        # Execute a trigger result
        result = await hub.execute_trigger(trigger_result, recipient)
    """

    def __init__(self):
        self.channels: dict[ChannelType, Channel] = {}

    def register(self, channel: Channel) -> None:
        """Register a channel with the hub."""
        self.channels[channel.channel_type] = channel
        logger.info(f"Registered channel: {channel.channel_type.value}")

    def unregister(self, channel_type: ChannelType) -> bool:
        """Unregister a channel. Returns True if found."""
        if channel_type in self.channels:
            del self.channels[channel_type]
            logger.info(f"Unregistered channel: {channel_type.value}")
            return True
        return False

    def get_channel(self, channel_type: ChannelType) -> Optional[Channel]:
        """Get a specific channel."""
        return self.channels.get(channel_type)

    async def send(self, message: Message) -> SendResult:
        """
        Send a message via the most appropriate channel.

        Channel selection priority:
        1. Explicit channel_type on message
        2. Recipient's preferred channel
        3. Best channel for urgency level
        4. Any available channel
        """

        # Priority 1: Explicit channel type
        if message.channel_type:
            channel = self.channels.get(message.channel_type)
            if channel and channel.can_reach(message.recipient):
                return await channel.send(message)
            logger.warning(
                f"Requested channel {message.channel_type} unavailable, falling back"
            )

        # Priority 2: Recipient preference
        if message.recipient.preferred_channel:
            channel = self.channels.get(message.recipient.preferred_channel)
            if channel and channel.can_reach(message.recipient):
                return await channel.send(message)

        # Priority 3: Best for urgency
        urgency_channels = URGENCY_CHANNELS.get(message.urgency, [])
        for channel_type in urgency_channels:
            channel = self.channels.get(channel_type)
            if channel and channel.can_reach(message.recipient):
                return await channel.send(message)

        # Priority 4: Any available channel
        for channel in self.channels.values():
            if channel.can_reach(message.recipient):
                return await channel.send(message)

        # No channel available
        logger.error(f"No channel available for recipient {message.recipient.id}")
        return SendResult(
            success=False,
            channel_type=ChannelType.CONSOLE,  # placeholder
            error="No channel available to reach recipient",
        )

    async def send_to_channel(
        self, channel_type: ChannelType, message: Message
    ) -> SendResult:
        """Send a message to a specific channel."""
        channel = self.channels.get(channel_type)
        if not channel:
            return SendResult(
                success=False,
                channel_type=channel_type,
                error=f"Channel {channel_type.value} not registered",
            )
        return await channel.send(message)

    async def broadcast(
        self, message: Message, channel_types: Optional[list[ChannelType]] = None
    ) -> list[SendResult]:
        """
        Send a message to multiple channels.

        Args:
            message: Message to send.
            channel_types: Specific channels to use. If None, uses all.

        Returns:
            List of SendResults from each channel.
        """
        results = []
        targets = channel_types or list(self.channels.keys())

        for channel_type in targets:
            channel = self.channels.get(channel_type)
            if channel and channel.can_reach(message.recipient):
                result = await channel.send(message)
                results.append(result)

        return results

    async def execute_trigger(
        self, trigger_result: TriggerResult, recipient: Recipient
    ) -> Optional[SendResult]:
        """
        Execute a trigger action by sending via appropriate channel.

        Args:
            trigger_result: The fired trigger result.
            recipient: Who to send the message to.

        Returns:
            SendResult if message was sent, None if trigger didn't fire.
        """
        if not trigger_result.fired:
            return None

        if not trigger_result.action_type:
            logger.warning(f"Trigger {trigger_result.trigger_name} has no action type")
            return None

        # Get channel for action type
        channel_type = ACTION_TO_CHANNEL.get(trigger_result.action_type)

        # Build message from trigger params
        params = trigger_result.action_params or {}
        content = params.get("message", f"Trigger {trigger_result.trigger_name} fired")
        urgency = params.get("urgency", "normal")

        message = Message(
            content=content,
            recipient=recipient,
            channel_type=channel_type,
            urgency=urgency,
            metadata={
                "trigger_name": trigger_result.trigger_name,
                "session_token": trigger_result.session_token,
                "trigger_reason": trigger_result.reason,
            },
        )

        # Handle custom action type
        if trigger_result.action_type == ActionType.CUSTOM:
            custom_handler = params.get("handler")
            if callable(custom_handler):
                try:
                    return await custom_handler(message, self)
                except Exception as e:
                    logger.error(f"Custom action handler error: {e}")
                    return SendResult(
                        success=False,
                        channel_type=ChannelType.WEBHOOK,
                        error=str(e),
                    )

        return await self.send(message)

    def list_channels(self) -> list[dict]:
        """List all registered channels with their status."""
        return [
            {
                "type": channel.channel_type.value,
                "enabled": channel.enabled,
                "priority": channel.config.priority if channel.config else 100,
            }
            for channel in self.channels.values()
        ]
