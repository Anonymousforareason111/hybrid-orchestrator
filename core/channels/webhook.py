"""
Webhook channel for integrating with external systems.

Sends messages to a configured webhook URL.

Security considerations:
    - URLs are validated to prevent SSRF attacks
    - Only HTTPS URLs are allowed by default
    - An allowlist can restrict destinations
    - Internal/private IPs are blocked
"""

import logging
import json
import uuid
import re
from datetime import datetime
from ipaddress import ip_address, ip_network
from typing import Optional
from urllib.parse import urlparse

from .base import Channel, ChannelConfig, ChannelType, Message, SendResult

logger = logging.getLogger(__name__)

# Optional: use aiohttp if available, fallback to urllib
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    import urllib.request
    import urllib.error


# Private/internal IP ranges to block (SSRF prevention)
BLOCKED_IP_RANGES = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),  # Link-local
    ip_network("::1/128"),  # IPv6 loopback
    ip_network("fc00::/7"),  # IPv6 private
    ip_network("fe80::/10"),  # IPv6 link-local
]


class WebhookSecurityError(Exception):
    """Raised when webhook URL fails security validation."""
    pass


class WebhookChannel(Channel):
    """
    A channel that sends messages to a webhook URL.

    Config should include:
        - url: The webhook URL (must be HTTPS unless allow_http=True)
        - headers: Optional dict of headers
        - timeout: Request timeout in seconds (default 10)
        - allow_http: Allow non-HTTPS URLs (default False, NOT recommended)
        - allowed_domains: List of allowed domain patterns (optional allowlist)
        - block_private_ips: Block private/internal IPs (default True)
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.url = config.config.get("url")
        self.headers = config.config.get("headers", {"Content-Type": "application/json"})
        self.timeout = config.config.get("timeout", 10)
        self.allow_http = config.config.get("allow_http", False)
        self.allowed_domains = config.config.get("allowed_domains", None)
        self.block_private_ips = config.config.get("block_private_ips", True)

        if not self.url:
            raise ValueError("Webhook URL is required in config")

        # Validate URL on init
        self._validate_url(self.url)

    def _validate_url(self, url: str) -> None:
        """
        Validate URL for security issues.

        Raises:
            WebhookSecurityError: If URL fails security validation.
        """
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise WebhookSecurityError(f"Invalid URL format: {e}")

        # Check scheme
        if parsed.scheme not in ("http", "https"):
            raise WebhookSecurityError(f"Invalid URL scheme: {parsed.scheme}")

        if parsed.scheme == "http" and not self.allow_http:
            raise WebhookSecurityError(
                "HTTP URLs are not allowed (use HTTPS or set allow_http=True)"
            )

        # Check hostname exists
        if not parsed.hostname:
            raise WebhookSecurityError("URL must have a hostname")

        # Check domain allowlist
        if self.allowed_domains:
            if not self._domain_allowed(parsed.hostname):
                raise WebhookSecurityError(
                    f"Domain '{parsed.hostname}' not in allowed list"
                )

        # Block private IPs (SSRF prevention)
        if self.block_private_ips:
            self._check_not_private_ip(parsed.hostname)

    def _domain_allowed(self, hostname: str) -> bool:
        """Check if hostname matches allowed domain patterns."""
        for pattern in self.allowed_domains:
            # Support wildcards like *.example.com
            if pattern.startswith("*."):
                suffix = pattern[1:]  # .example.com
                if hostname.endswith(suffix) or hostname == pattern[2:]:
                    return True
            elif hostname == pattern:
                return True
        return False

    def _check_not_private_ip(self, hostname: str) -> None:
        """Check that hostname doesn't resolve to a private IP."""
        try:
            # Try to parse as IP directly
            ip = ip_address(hostname)
            for network in BLOCKED_IP_RANGES:
                if ip in network:
                    raise WebhookSecurityError(
                        f"Private/internal IP addresses are blocked: {hostname}"
                    )
        except ValueError:
            # Not an IP, it's a hostname - we can't resolve without DNS
            # For now, just block obvious localhost patterns
            if hostname.lower() in ("localhost", "localhost.localdomain"):
                raise WebhookSecurityError("localhost is blocked")
            # Note: Full DNS resolution check would require async DNS lookup
            # which is beyond scope here. Production should use a proper
            # SSRF-prevention library.

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.WEBHOOK

    async def send(self, message: Message) -> SendResult:
        """Send message to webhook."""
        message_id = str(uuid.uuid4())

        payload = {
            "id": message_id,
            "timestamp": datetime.utcnow().isoformat(),
            "recipient": {
                "id": message.recipient.id,
                "name": message.recipient.name,
                "phone": message.recipient.phone,
                "email": message.recipient.email,
            },
            "content": message.content,
            "urgency": message.urgency,
            "metadata": message.metadata,
        }

        try:
            if HAS_AIOHTTP:
                result = await self._send_aiohttp(payload)
            else:
                result = self._send_urllib(payload)

            logger.info(f"Webhook message sent: {message_id} to {self.url}")

            return SendResult(
                success=True,
                channel_type=self.channel_type,
                message_id=message_id,
                metadata={"response": result},
            )

        except Exception as e:
            logger.error(f"Webhook send failed: {e}")
            return SendResult(
                success=False,
                channel_type=self.channel_type,
                message_id=message_id,
                error=str(e),
            )

    async def _send_aiohttp(self, payload: dict) -> dict:
        """Send using aiohttp (async)."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.url,
                json=payload,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                response.raise_for_status()
                return await response.json()

    def _send_urllib(self, payload: dict) -> dict:
        """Send using urllib (sync fallback)."""
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=data,
            headers=self.headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
