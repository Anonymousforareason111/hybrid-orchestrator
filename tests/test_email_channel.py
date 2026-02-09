"""Tests for EmailChannel integration with email-agent microservice."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.channels import (
    ChannelConfig,
    ChannelType,
    Message,
    Recipient,
)
from core.channels.email import EmailChannel, EmailChannelError
from core.channels.email_listener import EmailAgentListener, EmailEvent


class TestEmailChannelConfig:
    """Test EmailChannel configuration and initialization."""

    def test_requires_api_key(self):
        """EmailChannel requires api_key in config."""
        config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={"base_url": "http://localhost:3001"},
        )

        with pytest.raises(ValueError, match="api_key is required"):
            EmailChannel(config)

    def test_accepts_valid_config(self):
        """EmailChannel accepts valid configuration."""
        config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )

        channel = EmailChannel(config)
        assert channel.base_url == "http://localhost:3001"
        assert channel.api_key == "test-key"
        assert channel.timeout == 30  # default

    def test_strips_trailing_slash_from_base_url(self):
        """Base URL trailing slash is stripped."""
        config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001/",
                "api_key": "test-key",
            },
        )

        channel = EmailChannel(config)
        assert channel.base_url == "http://localhost:3001"

    def test_custom_timeout(self):
        """Can set custom timeout."""
        config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
                "timeout": 60,
            },
        )

        channel = EmailChannel(config)
        assert channel.timeout == 60


class TestEmailChannelType:
    """Test EmailChannel type properties."""

    def setup_method(self):
        self.config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )
        self.channel = EmailChannel(self.config)

    def test_channel_type(self):
        """Channel reports correct type."""
        assert self.channel.channel_type == ChannelType.EMAIL

    def test_can_reach_with_email(self):
        """can_reach returns True when recipient has email."""
        recipient_with_email = Recipient(id="1", email="test@example.com")
        assert self.channel.can_reach(recipient_with_email) is True

    def test_cannot_reach_without_email(self):
        """can_reach returns False when recipient has no email."""
        recipient_without_email = Recipient(id="2")
        assert self.channel.can_reach(recipient_without_email) is False

    def test_matches_low_urgency(self):
        """Email matches low urgency messages."""
        assert self.channel.matches_urgency("low") is True

    def test_matches_normal_urgency(self):
        """Email matches normal urgency messages."""
        assert self.channel.matches_urgency("normal") is True

    def test_does_not_match_high_urgency(self):
        """Email doesn't match high urgency messages."""
        assert self.channel.matches_urgency("high") is False

    def test_does_not_match_critical_urgency(self):
        """Email doesn't match critical urgency messages."""
        assert self.channel.matches_urgency("critical") is False


class TestEmailChannelSend:
    """Test EmailChannel send functionality."""

    def setup_method(self):
        self.config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )
        self.channel = EmailChannel(self.config)

    @pytest.mark.asyncio
    async def test_send_without_email_fails(self):
        """Sending to recipient without email fails gracefully."""
        message = Message(
            content="Test message",
            recipient=Recipient(id="1"),  # No email
        )

        result = await self.channel.send(message)

        assert result.success is False
        assert "no email address" in result.error.lower()
        assert result.channel_type == ChannelType.EMAIL

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Successful send returns proper result."""
        mock_response = {"success": True, "messageId": "msg_123"}

        # Mock both send methods to handle aiohttp availability
        with patch.object(self.channel, "_send_aiohttp", return_value=mock_response):
            with patch.object(self.channel, "_send_urllib", return_value=mock_response):
                message = Message(
                    content="Test message",
                    recipient=Recipient(id="1", email="test@example.com"),
                )

                result = await self.channel.send(message)

                assert result.success is True
                assert result.message_id == "msg_123"
                assert result.channel_type == ChannelType.EMAIL

    @pytest.mark.asyncio
    async def test_send_failure_returns_error(self):
        """Send failure returns error in result."""
        # Mock both send methods to handle aiohttp availability
        with patch.object(
            self.channel, "_send_aiohttp", side_effect=Exception("Connection refused")
        ):
            with patch.object(
                self.channel, "_send_urllib", side_effect=Exception("Connection refused")
            ):
                message = Message(
                    content="Test message",
                    recipient=Recipient(id="1", email="test@example.com"),
                )

                result = await self.channel.send(message)

                assert result.success is False
                assert "Connection refused" in result.error
                assert result.message_id is not None  # UUID generated


class TestEmailChannelSubject:
    """Test email subject building."""

    def setup_method(self):
        self.config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )
        self.channel = EmailChannel(self.config)

    def test_build_subject_with_trigger(self):
        """Subject includes trigger name when present."""
        message = Message(
            content="User needs help",
            recipient=Recipient(id="1"),
            urgency="high",
            metadata={"trigger_name": "inactivity_alert"},
        )

        subject = self.channel._build_subject(message)

        assert "[Important]" in subject
        assert "inactivity_alert" in subject

    def test_build_subject_critical_urgency(self):
        """Critical urgency adds URGENT prefix."""
        message = Message(
            content="Emergency!",
            recipient=Recipient(id="1"),
            urgency="critical",
            metadata={"trigger_name": "critical_error"},
        )

        subject = self.channel._build_subject(message)
        assert "[URGENT]" in subject

    def test_build_subject_from_content(self):
        """Subject uses content preview when no trigger."""
        message = Message(
            content="This is a test message with some content that is longer than fifty characters",
            recipient=Recipient(id="1"),
        )

        subject = self.channel._build_subject(message)

        assert "This is a test message" in subject
        assert "..." in subject  # Truncated

    def test_build_subject_short_content(self):
        """Short content is not truncated."""
        message = Message(
            content="Hello",
            recipient=Recipient(id="1"),
        )

        subject = self.channel._build_subject(message)
        assert subject == "Hello"


class TestEmailChannelBody:
    """Test email body building."""

    def setup_method(self):
        self.config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )
        self.channel = EmailChannel(self.config)

    def test_build_body_basic(self):
        """Basic body contains content."""
        message = Message(
            content="Test content",
            recipient=Recipient(id="1"),
        )

        body = self.channel._build_body(message)
        assert "Test content" in body

    def test_build_body_with_session(self):
        """Body includes session token when available."""
        message = Message(
            content="Test content",
            recipient=Recipient(id="1"),
            metadata={"session_token": "ses_12345"},
        )

        body = self.channel._build_body(message)
        assert "ses_12345" in body

    def test_build_body_with_trigger_info(self):
        """Body includes trigger information when available."""
        message = Message(
            content="Alert!",
            recipient=Recipient(id="1"),
            metadata={
                "trigger_name": "inactivity_warning",
                "trigger_reason": "No activity for 120s",
            },
        )

        body = self.channel._build_body(message)
        assert "inactivity_warning" in body
        assert "No activity for 120s" in body


class TestEmailChannelHealthCheck:
    """Test health check functionality."""

    def setup_method(self):
        self.config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )
        self.channel = EmailChannel(self.config)

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Health check returns True on 200 response."""
        # Create a proper async context manager mock for aiohttp
        mock_response = MagicMock()
        mock_response.status = 200

        # Create async context manager for session.get()
        mock_get_cm = AsyncMock()
        mock_get_cm.__aenter__.return_value = mock_response

        # Create async context manager for ClientSession()
        mock_session = MagicMock()
        mock_session.get.return_value = mock_get_cm

        mock_client_cm = AsyncMock()
        mock_client_cm.__aenter__.return_value = mock_session

        with patch("core.channels.email.aiohttp.ClientSession", return_value=mock_client_cm):
            result = await self.channel.check_health()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Health check returns False on connection error."""
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            result = await self.channel.check_health()
            assert result is False


class TestEmailEvent:
    """Test EmailEvent dataclass."""

    def test_from_dict(self):
        """EmailEvent.from_dict creates event from dict."""
        data = {
            "eventType": "email_received",
            "messageId": "msg_123",
            "subject": "Test Subject",
            "from": "sender@example.com",
            "to": "recipient@example.com",
            "timestamp": "2026-01-13T10:00:00Z",
            "extra_field": "value",
        }

        event = EmailEvent.from_dict(data)

        assert event.event_type == "email_received"
        assert event.message_id == "msg_123"
        assert event.subject == "Test Subject"
        assert event.sender == "sender@example.com"
        assert event.recipient == "recipient@example.com"
        assert event.metadata["extra_field"] == "value"

    def test_from_dict_defaults(self):
        """EmailEvent.from_dict handles missing fields."""
        event = EmailEvent.from_dict({})

        assert event.event_type == "unknown"
        assert event.message_id == ""
        assert event.subject == ""


class TestEmailAgentListener:
    """Test EmailAgentListener configuration."""

    def test_requires_websockets(self):
        """Listener requires websockets package."""
        # This test verifies the import check works
        # If websockets is not installed, it should raise ImportError
        # Since we can't uninstall websockets in tests, we just verify
        # the listener can be instantiated when websockets is available
        try:
            listener = EmailAgentListener(
                ws_url="ws://localhost:3001/ws",
                api_key="test-key",
            )
            assert listener.ws_url == "ws://localhost:3001/ws"
            assert listener.api_key == "test-key"
        except ImportError:
            # websockets not installed, which is fine for this test
            pass

    def test_default_values(self):
        """Listener has sensible defaults."""
        try:
            listener = EmailAgentListener()
            assert listener.ws_url == "ws://localhost:3001/ws"
            assert listener.api_key is None
            assert listener.reconnect_delay == 5.0
            assert listener.max_reconnect_attempts == 10
        except ImportError:
            pass

    def test_is_running_initially_false(self):
        """Listener is not running initially."""
        try:
            listener = EmailAgentListener()
            assert listener.is_running is False
            assert listener.is_connected is False
        except ImportError:
            pass

    def test_on_callback_registration(self):
        """Can register callbacks with on() method."""
        try:

            def my_callback(event):
                pass

            listener = EmailAgentListener()
            listener.on("email_received", my_callback)
            assert listener._callbacks["email_received"] is my_callback
        except ImportError:
            pass


class TestChannelHubWithEmail:
    """Test EmailChannel integration with ChannelHub."""

    def setup_method(self):
        from core.channels import ChannelHub

        self.hub = ChannelHub()

    def test_register_email_channel(self):
        """Can register EmailChannel with hub."""
        config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )
        channel = EmailChannel(config)
        self.hub.register(channel)

        assert ChannelType.EMAIL in self.hub.channels
        assert self.hub.get_channel(ChannelType.EMAIL) is channel

    @pytest.mark.asyncio
    async def test_send_via_hub(self):
        """Can send messages through hub to EmailChannel."""
        config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "test-key",
            },
        )
        channel = EmailChannel(config)
        self.hub.register(channel)

        message = Message(
            content="Test",
            recipient=Recipient(id="1", email="test@example.com"),
            channel_type=ChannelType.EMAIL,
        )

        # Mock the send to avoid actual HTTP call
        mock_response = {"success": True, "messageId": "msg_123"}
        with patch.object(channel, "_send_urllib", return_value=mock_response):
            result = await self.hub.send(message)

        assert result.success is True
        assert result.channel_type == ChannelType.EMAIL
