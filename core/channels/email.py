"""
Email channel for integrating with email-agent microservice.

Sends messages via the email-agent REST API (TypeScript/Bun service).
The email-agent handles actual IMAP/SMTP operations.

Security considerations:
    - API key authentication between services
    - HTTPS recommended for production
    - Timeout protection against hanging requests
"""

import logging
import json
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from .base import Channel, ChannelConfig, ChannelType, Message, SendResult, Recipient

logger = logging.getLogger(__name__)

# urllib is always needed for fallback and exception types
import urllib.request
import urllib.error

# Optional: use aiohttp if available
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


class EmailChannelError(Exception):
    """Raised when email-agent communication fails."""
    pass


class EmailChannel(Channel):
    """
    A channel that sends messages via the email-agent microservice.

    The email-agent is a separate TypeScript/Bun service that handles
    IMAP connections, email parsing, and sending. This channel acts
    as a REST API client to that service.

    Config should include:
        - base_url: The email-agent service URL (e.g., http://localhost:3001)
        - api_key: Shared secret for service-to-service authentication
        - timeout: Request timeout in seconds (default 30)
        - default_from: Default sender name (optional)

    Example:
        config = ChannelConfig(
            type=ChannelType.EMAIL,
            config={
                "base_url": "http://localhost:3001",
                "api_key": "your-shared-secret",
                "timeout": 30,
            }
        )
        channel = EmailChannel(config)
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.base_url = config.config.get("base_url", "http://localhost:3001")
        self.api_key = config.config.get("api_key")
        self.timeout = config.config.get("timeout", 30)
        self.default_from = config.config.get("default_from", "Orchestrator")

        if not self.api_key:
            raise ValueError("api_key is required for EmailChannel")

        # Ensure base_url doesn't have trailing slash
        self.base_url = self.base_url.rstrip("/")

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        logger.info(f"EmailChannel initialized with base_url: {self.base_url}")

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.EMAIL

    def can_reach(self, recipient: Recipient) -> bool:
        """Check if recipient has email address."""
        return self.enabled and bool(recipient.email)

    def matches_urgency(self, urgency: str) -> bool:
        """
        Email is appropriate for non-critical urgency levels.

        Voice/SMS preferred for critical/high urgency.
        """
        return urgency in ("low", "normal")

    async def send(self, message: Message) -> SendResult:
        """
        Send message via email-agent microservice.

        Args:
            message: The message to send. Must have recipient.email set.

        Returns:
            SendResult indicating success or failure.
        """
        message_id = str(uuid.uuid4())

        if not message.recipient.email:
            return SendResult(
                success=False,
                channel_type=self.channel_type,
                message_id=message_id,
                error="Recipient has no email address",
            )

        payload = {
            "to": message.recipient.email,
            "subject": self._build_subject(message),
            "body": self._build_body(message),
            "sessionToken": message.metadata.get("session_token"),
            "metadata": {
                "message_id": message_id,
                "recipient_id": message.recipient.id,
                "recipient_name": message.recipient.name,
                "urgency": message.urgency,
                "sent_at": datetime.utcnow().isoformat(),
                **message.metadata,
            },
        }

        try:
            url = f"{self.base_url}/api/orchestrator/send"

            if HAS_AIOHTTP:
                result = await self._send_aiohttp(url, payload)
            else:
                result = self._send_urllib(url, payload)

            logger.info(
                f"Email sent via email-agent: {message_id} to {message.recipient.email}"
            )

            return SendResult(
                success=True,
                channel_type=self.channel_type,
                message_id=result.get("messageId", message_id),
                metadata={"response": result},
            )

        except aiohttp.ClientError as e:
            logger.error(f"Email send failed (aiohttp): {e}")
            return SendResult(
                success=False,
                channel_type=self.channel_type,
                message_id=message_id,
                error=f"HTTP error: {e}",
            )
        except urllib.error.URLError as e:
            logger.error(f"Email send failed (urllib): {e}")
            return SendResult(
                success=False,
                channel_type=self.channel_type,
                message_id=message_id,
                error=f"URL error: {e}",
            )
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return SendResult(
                success=False,
                channel_type=self.channel_type,
                message_id=message_id,
                error=str(e),
            )

    def _build_subject(self, message: Message) -> str:
        """Build email subject from message context."""
        urgency_prefix = {
            "critical": "[URGENT] ",
            "high": "[Important] ",
            "normal": "",
            "low": "",
        }

        prefix = urgency_prefix.get(message.urgency, "")
        trigger_name = message.metadata.get("trigger_name", "")

        if trigger_name:
            return f"{prefix}Alert: {trigger_name}"

        # Use first 50 chars of content as subject
        content_preview = message.content[:50].replace("\n", " ").strip()
        if len(message.content) > 50:
            content_preview += "..."

        return f"{prefix}{content_preview}"

    def _build_body(self, message: Message) -> str:
        """Build email body with context."""
        parts = [message.content]

        # Add session info if available
        session_token = message.metadata.get("session_token")
        if session_token:
            parts.append(f"\n\n---\nSession: {session_token}")

        # Add trigger info if available
        trigger_name = message.metadata.get("trigger_name")
        trigger_reason = message.metadata.get("trigger_reason")
        if trigger_name:
            parts.append(f"Trigger: {trigger_name}")
        if trigger_reason:
            parts.append(f"Reason: {trigger_reason}")

        return "\n".join(parts)

    async def _send_aiohttp(self, url: str, payload: dict) -> dict:
        """Send using aiohttp (async)."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                response.raise_for_status()
                return await response.json()

    def _send_urllib(self, url: str, payload: dict) -> dict:
        """Send using urllib (sync fallback)."""
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=self.headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def check_health(self) -> bool:
        """
        Check if email-agent service is healthy.

        Returns:
            True if service is responding, False otherwise.
        """
        try:
            url = f"{self.base_url}/api/health"

            if HAS_AIOHTTP:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as response:
                        return response.status == 200
            else:
                request = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status == 200

        except Exception as e:
            logger.warning(f"Email-agent health check failed: {e}")
            return False

    async def get_inbox(self, limit: int = 20) -> list[dict]:
        """
        Get recent emails from inbox via email-agent.

        Args:
            limit: Maximum number of emails to return.

        Returns:
            List of email objects.

        Raises:
            EmailChannelError: If request fails.
        """
        try:
            url = f"{self.base_url}/api/emails/inbox?limit={limit}"

            if HAS_AIOHTTP:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        response.raise_for_status()
                        return await response.json()
            else:
                request = urllib.request.Request(
                    url,
                    headers=self.headers,
                    method="GET",
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))

        except Exception as e:
            raise EmailChannelError(f"Failed to get inbox: {e}")

    async def search_emails(self, query: str) -> list[dict]:
        """
        Search emails via email-agent.

        Args:
            query: Search query string.

        Returns:
            List of matching email objects.

        Raises:
            EmailChannelError: If request fails.
        """
        try:
            url = f"{self.base_url}/api/emails/search"
            payload = {"query": query}

            if HAS_AIOHTTP:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        response.raise_for_status()
                        return await response.json()
            else:
                data = json.dumps(payload).encode("utf-8")
                request = urllib.request.Request(
                    url,
                    data=data,
                    headers=self.headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))

        except Exception as e:
            raise EmailChannelError(f"Failed to search emails: {e}")
