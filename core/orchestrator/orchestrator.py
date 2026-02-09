"""
Main orchestrator class that ties together all components.

The orchestrator coordinates:
- Session state management
- Trigger evaluation
- Channel routing
- Human escalation
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable

from ..storage import SessionStore, Session, Activity, SessionStatus
from ..triggers import TriggerEngine, Trigger, TriggerResult
from ..channels import ChannelHub, Recipient, Message

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Central orchestrator for hybrid human-AI workflows.

    Combines:
        - Pattern 1: Session state externalization (SessionStore)
        - Pattern 2: Multi-channel communication (ChannelHub)
        - Pattern 3: Activity monitoring with triggers (TriggerEngine)
        - Pattern 4: Human escalation (via channels)

    Usage:
        # Initialize
        orchestrator = Orchestrator(db_path="sessions.db")

        # Register channels
        orchestrator.channels.register(ConsoleChannel())

        # Add triggers
        orchestrator.triggers.add_trigger(inactivity_trigger)

        # Start session
        session = await orchestrator.start_session(
            external_id="user_123",
            metadata={"form_type": "application"}
        )

        # Record activity
        await orchestrator.record_activity(
            session.token,
            activity_type="field_change",
            data={"field_id": "email", "value": "test@example.com"}
        )

        # Check triggers (call periodically)
        await orchestrator.check_triggers()

        # Complete session
        await orchestrator.complete_session(session.token)
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        check_interval: float = 30.0,
    ):
        """
        Initialize the orchestrator.

        Args:
            db_path: Path to SQLite database for session storage.
            check_interval: Seconds between automatic trigger checks.
        """
        self.store = SessionStore(db_path)
        self.triggers = TriggerEngine()
        self.channels = ChannelHub()

        self.check_interval = check_interval
        self._check_task: Optional[asyncio.Task] = None
        self._running = False

        # Callbacks
        self._on_trigger_fired: Optional[Callable[[TriggerResult], None]] = None
        self._on_session_expired: Optional[Callable[[Session], None]] = None

        logger.info(f"Orchestrator initialized with db: {db_path}")

    # --- Session Management (Sync) ---
    # These are synchronous because SQLite operations are blocking.
    # Use the async versions when you need to mix with channel operations.

    def create_session(
        self,
        external_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        recipient: Optional[Recipient] = None,
    ) -> Session:
        """
        Start a new orchestrated session (sync).

        Args:
            external_id: External system identifier (e.g., VAPI call ID).
            metadata: Initial session metadata.
            recipient: Recipient info for channel routing.

        Returns:
            The created Session object.
        """
        session = self.store.create_session(
            external_id=external_id,
            metadata=metadata or {},
        )

        # Store recipient in metadata if provided
        if recipient:
            session.metadata["recipient"] = {
                "id": recipient.id,
                "name": recipient.name,
                "phone": recipient.phone,
                "email": recipient.email,
            }
            self.store.update_session(session)

        logger.info(f"Started session: {session.token}")
        return session

    def get_session(self, token: str, include_activities: bool = False) -> Optional[Session]:
        """Get a session by token (sync)."""
        return self.store.get_session(token, include_activities=include_activities)

    def record_activity(
        self,
        session_token: str,
        activity_type: str,
        data: Optional[dict] = None,
    ) -> Optional[Activity]:
        """
        Record an activity in a session (sync).

        Args:
            session_token: The session to record activity for.
            activity_type: Type of activity (e.g., "field_change", "voice_input").
            data: Activity-specific data.

        Returns:
            The created Activity, or None if session not found.
        """
        activity = self.store.add_activity(
            session_token=session_token,
            activity_type=activity_type,
            data=data or {},
        )

        if activity:
            logger.debug(f"Recorded activity: {activity_type} for {session_token}")

        return activity

    def update_status(self, token: str, status: SessionStatus) -> Optional[Session]:
        """Update a session's status (sync)."""
        session = self.store.get_session(token)
        if session:
            session.status = status
            session.updated_at = datetime.utcnow()
            self.store.update_session(session)
            logger.info(f"Session {token} status -> {status.value}")
        return session

    def complete(self, token: str) -> Optional[Session]:
        """Mark a session as completed (sync)."""
        return self.update_status(token, SessionStatus.COMPLETED)

    def abandon(self, token: str) -> Optional[Session]:
        """Mark a session as abandoned (sync)."""
        return self.update_status(token, SessionStatus.ABANDONED)

    # --- Async Wrappers ---
    # For compatibility with async code and channel operations.

    async def start_session(
        self,
        external_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        recipient: Optional[Recipient] = None,
    ) -> Session:
        """Start a new orchestrated session (async wrapper)."""
        return self.create_session(external_id, metadata, recipient)

    async def async_get_session(self, token: str) -> Optional[Session]:
        """Get a session by token (async wrapper)."""
        return self.get_session(token)

    async def async_record_activity(
        self,
        session_token: str,
        activity_type: str,
        data: Optional[dict] = None,
    ) -> Optional[Activity]:
        """Record an activity in a session (async wrapper)."""
        return self.record_activity(session_token, activity_type, data)

    async def complete_session(self, token: str) -> Optional[Session]:
        """Mark a session as completed (async wrapper)."""
        return self.complete(token)

    async def abandon_session(self, token: str) -> Optional[Session]:
        """Mark a session as abandoned (async wrapper)."""
        return self.abandon(token)

    # --- Trigger Management ---

    def add_trigger(self, trigger: Trigger) -> None:
        """Add a trigger to the engine."""
        self.triggers.add_trigger(trigger)

    def remove_trigger(self, name: str) -> bool:
        """Remove a trigger by name."""
        return self.triggers.remove_trigger(name)

    async def check_triggers(self) -> list[TriggerResult]:
        """
        Check all triggers against all active sessions.

        Returns:
            List of fired trigger results.
        """
        sessions = self.store.get_active_sessions(include_activities=True)
        results = self.triggers.evaluate_all(sessions)

        # Execute fired triggers
        for result in results:
            if result.fired:
                await self._execute_trigger(result)
                if self._on_trigger_fired:
                    self._on_trigger_fired(result)

        return results

    async def _execute_trigger(self, result: TriggerResult) -> None:
        """Execute a fired trigger via channels."""
        session = self.store.get_session(result.session_token)
        if not session:
            return

        # Build recipient from session metadata
        recipient_data = session.metadata.get("recipient", {})
        recipient = Recipient(
            id=recipient_data.get("id", session.token),
            name=recipient_data.get("name"),
            phone=recipient_data.get("phone"),
            email=recipient_data.get("email"),
        )

        send_result = await self.channels.execute_trigger(result, recipient)
        if send_result:
            logger.info(
                f"Trigger {result.trigger_name} executed: "
                f"success={send_result.success}, channel={send_result.channel_type.value}"
            )

    # --- Background Processing ---

    async def start(self) -> None:
        """Start background trigger checking."""
        if self._running:
            return

        self._running = True
        self._check_task = asyncio.create_task(self._background_loop())
        logger.info("Orchestrator background loop started")

    async def stop(self) -> None:
        """Stop background processing."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Orchestrator background loop stopped")

    async def _background_loop(self) -> None:
        """Background loop for periodic trigger checks and cleanup."""
        while self._running:
            try:
                # Check triggers
                await self.check_triggers()

                # Cleanup expired sessions
                expired = self.store.cleanup_expired()
                for session in expired:
                    logger.info(f"Session expired: {session.token}")
                    if self._on_session_expired:
                        self._on_session_expired(session)

                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background loop error: {e}")
                await asyncio.sleep(self.check_interval)

    # --- Callbacks ---

    def on_trigger_fired(self, callback: Callable[[TriggerResult], None]) -> None:
        """Register a callback for when triggers fire."""
        self._on_trigger_fired = callback

    def on_session_expired(self, callback: Callable[[Session], None]) -> None:
        """Register a callback for when sessions expire."""
        self._on_session_expired = callback

    # --- Context Manager ---

    async def __aenter__(self) -> "Orchestrator":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()

    # --- Utility ---

    def stats(self) -> dict:
        """Get current orchestrator statistics."""
        sessions = self.store.get_active_sessions()
        return {
            "active_sessions": len(sessions),
            "total_triggers": len(self.triggers.triggers),
            "registered_channels": len(self.channels.channels),
            "channels": self.channels.list_channels(),
        }
