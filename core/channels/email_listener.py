"""
Email listener that subscribes to email-agent events via WebSocket.

Bridges email-agent's listener system to the orchestrator's trigger system.
When emails arrive or events occur, this listener forwards them to the
orchestrator for processing.
"""

import asyncio
import json
import logging
from typing import Callable, Optional, Awaitable, Union
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Check for websockets library
try:
    import websockets
    from websockets.client import WebSocketClientProtocol
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    websockets = None


@dataclass
class EmailEvent:
    """Represents an email event from email-agent."""

    event_type: str  # email_received, email_sent, email_starred, etc.
    message_id: str
    subject: str
    sender: str
    recipient: str
    timestamp: str
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "EmailEvent":
        """Create EmailEvent from dictionary."""
        return cls(
            event_type=data.get("eventType", "unknown"),
            message_id=data.get("messageId", ""),
            subject=data.get("subject", ""),
            sender=data.get("from", ""),
            recipient=data.get("to", ""),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
            metadata=data,
        )


# Callback type for event handlers
EventCallback = Callable[[EmailEvent], Union[None, Awaitable[None]]]


class EmailAgentListener:
    """
    Listens to email-agent WebSocket for email events.

    Bridges email-agent's listener system to orchestrator triggers.
    When emails arrive or actions occur, callbacks are invoked.

    Example:
        async def handle_email(event: EmailEvent):
            print(f"New email from {event.sender}: {event.subject}")
            # Create session, record activity, etc.

        listener = EmailAgentListener(
            ws_url="ws://localhost:3001/ws",
            api_key="your-shared-secret",
            on_email_received=handle_email,
        )

        await listener.start()
        # ... listener runs in background ...
        await listener.stop()
    """

    def __init__(
        self,
        ws_url: str = "ws://localhost:3001/ws",
        api_key: Optional[str] = None,
        on_email_received: Optional[EventCallback] = None,
        on_email_sent: Optional[EventCallback] = None,
        on_email_starred: Optional[EventCallback] = None,
        on_email_archived: Optional[EventCallback] = None,
        on_any_event: Optional[EventCallback] = None,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 10,
    ):
        """
        Initialize the email listener.

        Args:
            ws_url: WebSocket URL of email-agent service.
            api_key: Shared secret for authentication.
            on_email_received: Callback for new emails.
            on_email_sent: Callback for sent emails.
            on_email_starred: Callback for starred emails.
            on_email_archived: Callback for archived emails.
            on_any_event: Callback for all events (fallback).
            reconnect_delay: Seconds to wait before reconnecting.
            max_reconnect_attempts: Max reconnection attempts (0 = unlimited).
        """
        if not HAS_WEBSOCKETS:
            raise ImportError(
                "websockets package required for EmailAgentListener. "
                "Install with: pip install websockets"
            )

        self.ws_url = ws_url
        self.api_key = api_key
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # Event callbacks
        self._callbacks = {
            "email_received": on_email_received,
            "email_sent": on_email_sent,
            "email_starred": on_email_starred,
            "email_archived": on_email_archived,
        }
        self._on_any_event = on_any_event

        # Internal state
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._reconnect_count = 0

    @property
    def is_running(self) -> bool:
        """Check if listener is currently running."""
        return self._running

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self._ws is not None and self._ws.open

    async def start(self) -> None:
        """Start listening to email-agent events."""
        if self._running:
            logger.warning("EmailAgentListener already running")
            return

        self._running = True
        self._reconnect_count = 0
        self._task = asyncio.create_task(self._listen_loop())
        logger.info(f"EmailAgentListener started, connecting to {self.ws_url}")

    async def stop(self) -> None:
        """Stop listening and close connection."""
        self._running = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("EmailAgentListener stopped")

    def on(self, event_type: str, callback: EventCallback) -> None:
        """
        Register a callback for an event type.

        Args:
            event_type: The event type (e.g., "email_received").
            callback: Function to call when event occurs.
        """
        self._callbacks[event_type] = callback

    async def _listen_loop(self) -> None:
        """Main WebSocket listen loop with automatic reconnection."""
        while self._running:
            try:
                await self._connect_and_listen()
            except websockets.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            if not self._running:
                break

            # Reconnection logic
            self._reconnect_count += 1
            if (
                self.max_reconnect_attempts > 0
                and self._reconnect_count > self.max_reconnect_attempts
            ):
                logger.error(
                    f"Max reconnection attempts ({self.max_reconnect_attempts}) reached"
                )
                self._running = False
                break

            logger.info(
                f"Reconnecting in {self.reconnect_delay}s "
                f"(attempt {self._reconnect_count})"
            )
            await asyncio.sleep(self.reconnect_delay)

    async def _connect_and_listen(self) -> None:
        """Establish connection and listen for messages."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with websockets.connect(
            self.ws_url,
            extra_headers=headers,
            ping_interval=30,
            ping_timeout=10,
        ) as ws:
            self._ws = ws
            self._reconnect_count = 0  # Reset on successful connection
            logger.info("WebSocket connected to email-agent")

            # Subscribe to orchestrator events channel
            await ws.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "channel": "orchestrator_events",
                    }
                )
            )

            # Listen for messages
            async for raw_message in ws:
                if not self._running:
                    break
                await self._handle_message(raw_message)

    async def _handle_message(self, raw_message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(raw_message)
            msg_type = data.get("type")

            if msg_type == "listener_log":
                # This is an event from email-agent's listener system
                event_data = data.get("data", {})
                event = EmailEvent.from_dict(event_data)
                await self._dispatch_event(event)

            elif msg_type == "inbox_update":
                # New email notification
                event_data = data.get("data", {})
                event = EmailEvent(
                    event_type="email_received",
                    message_id=event_data.get("messageId", ""),
                    subject=event_data.get("subject", ""),
                    sender=event_data.get("from", ""),
                    recipient=event_data.get("to", ""),
                    timestamp=datetime.utcnow().isoformat(),
                    metadata=event_data,
                )
                await self._dispatch_event(event)

            elif msg_type == "error":
                logger.error(f"Email-agent error: {data.get('message', 'Unknown')}")

            elif msg_type == "pong":
                # Keep-alive response, ignore
                pass

            else:
                logger.debug(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _dispatch_event(self, event: EmailEvent) -> None:
        """Dispatch event to appropriate callback(s)."""
        # Try specific callback first
        callback = self._callbacks.get(event.event_type)
        if callback:
            await self._safe_callback(callback, event)
        elif self._on_any_event:
            # Fall back to generic handler
            await self._safe_callback(self._on_any_event, event)
        else:
            logger.debug(f"No handler for event type: {event.event_type}")

    async def _safe_callback(self, callback: EventCallback, event: EmailEvent) -> None:
        """Safely execute callback, catching exceptions."""
        try:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Callback error for {event.event_type}: {e}")


class EmailAgentListenerContext:
    """
    Context manager for EmailAgentListener.

    Example:
        async with EmailAgentListenerContext(
            ws_url="ws://localhost:3001/ws",
            on_email_received=handle_email,
        ) as listener:
            # Listener is running
            await asyncio.sleep(3600)  # Run for an hour
        # Listener automatically stopped
    """

    def __init__(self, **kwargs):
        self.listener = EmailAgentListener(**kwargs)

    async def __aenter__(self) -> EmailAgentListener:
        await self.listener.start()
        return self.listener

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.listener.stop()
