"""Tests for channel hub and channels."""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.channels import (
    ChannelHub,
    Channel,
    ChannelConfig,
    ChannelType,
    Message,
    Recipient,
    SendResult,
    ConsoleChannel,
    WebhookChannel,
)
from core.triggers import TriggerResult, ActionType


class TestChannelHub:
    """Test channel hub routing."""

    def setup_method(self):
        self.hub = ChannelHub()
        self.recipient = Recipient(
            id="user_1",
            name="Test User",
            email="test@example.com",
        )

    def test_register_channel(self):
        """Can register channels."""
        channel = ConsoleChannel()
        self.hub.register(channel)

        assert ChannelType.CONSOLE in self.hub.channels
        assert self.hub.get_channel(ChannelType.CONSOLE) is channel

    def test_unregister_channel(self):
        """Can unregister channels."""
        self.hub.register(ConsoleChannel())
        assert self.hub.unregister(ChannelType.CONSOLE) is True
        assert self.hub.get_channel(ChannelType.CONSOLE) is None

    def test_unregister_nonexistent(self):
        """Unregistering nonexistent channel returns False."""
        assert self.hub.unregister(ChannelType.VOICE) is False

    @pytest.mark.asyncio
    async def test_send_to_explicit_channel(self):
        """Message with explicit channel_type uses that channel."""
        self.hub.register(ConsoleChannel())

        message = Message(
            content="Test",
            recipient=self.recipient,
            channel_type=ChannelType.CONSOLE,
        )

        result = await self.hub.send(message)
        assert result.success is True
        assert result.channel_type == ChannelType.CONSOLE

    @pytest.mark.asyncio
    async def test_send_falls_back_to_available(self):
        """Falls back to available channel when preferred unavailable."""
        self.hub.register(ConsoleChannel())

        message = Message(
            content="Test",
            recipient=self.recipient,
            channel_type=ChannelType.VOICE,  # Not registered
        )

        result = await self.hub.send(message)
        assert result.success is True
        assert result.channel_type == ChannelType.CONSOLE  # Fallback

    @pytest.mark.asyncio
    async def test_send_no_channel_available(self):
        """Returns failure when no channel available."""
        # No channels registered
        message = Message(content="Test", recipient=self.recipient)

        result = await self.hub.send(message)
        assert result.success is False
        assert "No channel available" in result.error

    @pytest.mark.asyncio
    async def test_send_respects_recipient_preference(self):
        """Uses recipient's preferred channel when available."""
        self.hub.register(ConsoleChannel())

        recipient = Recipient(
            id="user_1",
            preferred_channel=ChannelType.CONSOLE,
        )
        message = Message(content="Test", recipient=recipient)

        result = await self.hub.send(message)
        assert result.channel_type == ChannelType.CONSOLE

    @pytest.mark.asyncio
    async def test_broadcast(self):
        """Broadcast sends to multiple channels."""
        self.hub.register(ConsoleChannel())
        # Would add more channels here in real scenario

        message = Message(content="Broadcast", recipient=self.recipient)
        results = await self.hub.broadcast(message)

        assert len(results) >= 1
        assert all(r.success for r in results)

    def test_list_channels(self):
        """list_channels returns channel info."""
        self.hub.register(ConsoleChannel())

        channels = self.hub.list_channels()
        assert len(channels) == 1
        assert channels[0]["type"] == "console"
        assert channels[0]["enabled"] is True


class TestConsoleChannel:
    """Test console channel."""

    def setup_method(self):
        self.channel = ConsoleChannel()
        self.recipient = Recipient(id="test_user", name="Test")

    def test_channel_type(self):
        """Channel reports correct type."""
        assert self.channel.channel_type == ChannelType.CONSOLE

    @pytest.mark.asyncio
    async def test_send_success(self, capsys):
        """Sending message prints to console and succeeds."""
        message = Message(
            content="Hello, world!",
            recipient=self.recipient,
        )

        result = await self.channel.send(message)

        assert result.success is True
        assert result.message_id is not None

        captured = capsys.readouterr()
        assert "Hello, world!" in captured.out
        assert "Test" in captured.out

    @pytest.mark.asyncio
    async def test_stores_sent_messages(self):
        """Console channel stores sent messages for testing."""
        message = Message(content="Test", recipient=self.recipient)

        await self.channel.send(message)
        await self.channel.send(message)

        assert len(self.channel.sent_messages) == 2

    def test_clear_history(self):
        """Can clear sent message history."""
        self.channel.sent_messages.append(
            Message(content="Test", recipient=self.recipient)
        )
        self.channel.clear_history()

        assert len(self.channel.sent_messages) == 0


class TestWebhookChannel:
    """Test webhook channel."""

    def test_requires_url(self):
        """Webhook channel requires URL in config."""
        config = ChannelConfig(type=ChannelType.WEBHOOK, config={})

        with pytest.raises(ValueError, match="URL is required"):
            WebhookChannel(config)

    def test_accepts_https_url(self):
        """Webhook channel accepts HTTPS URL config."""
        config = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={"url": "https://example.com/webhook"},
        )

        channel = WebhookChannel(config)
        assert channel.url == "https://example.com/webhook"

    def test_rejects_http_by_default(self):
        """Webhook channel rejects HTTP URLs by default."""
        from core.channels.webhook import WebhookSecurityError

        config = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={"url": "http://example.com/webhook"},
        )

        with pytest.raises(WebhookSecurityError, match="HTTP URLs are not allowed"):
            WebhookChannel(config)

    def test_allows_http_when_enabled(self):
        """Webhook channel allows HTTP when explicitly enabled."""
        config = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={"url": "http://example.com/webhook", "allow_http": True},
        )

        channel = WebhookChannel(config)
        assert channel.url == "http://example.com/webhook"

    def test_blocks_localhost(self):
        """Webhook channel blocks localhost URLs."""
        from core.channels.webhook import WebhookSecurityError

        config = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={"url": "https://localhost/webhook"},
        )

        with pytest.raises(WebhookSecurityError, match="localhost is blocked"):
            WebhookChannel(config)

    def test_blocks_private_ips(self):
        """Webhook channel blocks private IP addresses."""
        from core.channels.webhook import WebhookSecurityError

        for ip in ["10.0.0.1", "192.168.1.1", "172.16.0.1", "127.0.0.1"]:
            config = ChannelConfig(
                type=ChannelType.WEBHOOK,
                config={"url": f"https://{ip}/webhook"},
            )

            with pytest.raises(WebhookSecurityError, match="blocked"):
                WebhookChannel(config)

    def test_domain_allowlist(self):
        """Webhook channel respects domain allowlist."""
        from core.channels.webhook import WebhookSecurityError

        # Allowed domain works
        config = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={
                "url": "https://api.trusted.com/webhook",
                "allowed_domains": ["api.trusted.com"],
            },
        )
        channel = WebhookChannel(config)
        assert channel.url == "https://api.trusted.com/webhook"

        # Disallowed domain fails
        config2 = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={
                "url": "https://evil.com/webhook",
                "allowed_domains": ["api.trusted.com"],
            },
        )
        with pytest.raises(WebhookSecurityError, match="not in allowed list"):
            WebhookChannel(config2)

    def test_wildcard_domain_allowlist(self):
        """Webhook channel supports wildcard domain patterns."""
        config = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={
                "url": "https://sub.example.com/webhook",
                "allowed_domains": ["*.example.com"],
            },
        )
        channel = WebhookChannel(config)
        assert channel.url == "https://sub.example.com/webhook"

    def test_custom_headers(self):
        """Can set custom headers."""
        config = ChannelConfig(
            type=ChannelType.WEBHOOK,
            config={
                "url": "https://example.com",
                "headers": {"Authorization": "Bearer token"},
            },
        )

        channel = WebhookChannel(config)
        assert channel.headers["Authorization"] == "Bearer token"


class TestTriggerExecution:
    """Test executing triggers through channel hub."""

    def setup_method(self):
        self.hub = ChannelHub()
        self.hub.register(ConsoleChannel())

    @pytest.mark.asyncio
    async def test_execute_trigger_sends_message(self):
        """Executing a fired trigger sends message through hub."""
        result = TriggerResult(
            trigger_name="test_trigger",
            session_token="ses_123",
            fired=True,
            action_type=ActionType.DASHBOARD_ALERT,
            action_params={"message": "Alert!", "urgency": "high"},
        )

        recipient = Recipient(id="user_1", name="Test User")

        send_result = await self.hub.execute_trigger(result, recipient)

        assert send_result is not None
        assert send_result.success is True

    @pytest.mark.asyncio
    async def test_execute_unfired_trigger_returns_none(self):
        """Executing unfired trigger returns None."""
        result = TriggerResult(
            trigger_name="test_trigger",
            session_token="ses_123",
            fired=False,
        )

        recipient = Recipient(id="user_1")
        send_result = await self.hub.execute_trigger(result, recipient)

        assert send_result is None
