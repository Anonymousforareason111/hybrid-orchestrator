#!/usr/bin/env python3
"""
Demo: Hybrid Human-AI Orchestration Framework

This script demonstrates all four design patterns:
    1. Session state externalization
    2. Multi-channel communication
    3. Activity monitoring with triggers
    4. Human escalation pathways

Run: python examples/demo.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    Orchestrator,
    Trigger,
    TriggerCondition,
    TriggerAction,
    ConditionType,
    ActionType,
    ConsoleChannel,
    Recipient,
    SessionStatus,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Demonstrate the hybrid orchestration framework."""

    print("\n" + "=" * 70)
    print("HYBRID HUMAN-AI ORCHESTRATION FRAMEWORK - DEMO")
    print("=" * 70)

    # -----------------------------------------------------
    # PATTERN 1: Session State Externalization
    # -----------------------------------------------------
    print("\n### PATTERN 1: Session State Externalization ###\n")

    # Create orchestrator with in-memory database
    orchestrator = Orchestrator(db_path=":memory:", check_interval=5.0)

    # Register console channel for demo output
    orchestrator.channels.register(ConsoleChannel())

    print("Created orchestrator with in-memory session store")
    print(f"Stats: {orchestrator.stats()}")

    # Start a session
    recipient = Recipient(
        id="user_123",
        name="John Smith",
        phone="+1234567890",
        email="john@example.com",
    )

    session = await orchestrator.start_session(
        external_id="vapi_call_abc123",
        metadata={
            "form_type": "insurance_application",
            "source": "voice_call",
        },
        recipient=recipient,
    )

    print(f"\nStarted session: {session.token}")
    print(f"  External ID: {session.external_id}")
    print(f"  Status: {session.status.value}")
    print(f"  Metadata: {session.metadata}")

    # -----------------------------------------------------
    # PATTERN 2: Multi-Channel Communication
    # -----------------------------------------------------
    print("\n### PATTERN 2: Multi-Channel Communication ###\n")

    print("Registered channels:")
    for ch in orchestrator.channels.list_channels():
        print(f"  - {ch['type']} (enabled: {ch['enabled']})")

    # Record some activities (sync)
    orchestrator.record_activity(
        session.token,
        activity_type="voice_input",
        data={"transcript": "I want to apply for life insurance"},
    )

    orchestrator.record_activity(
        session.token,
        activity_type="field_change",
        data={"field_id": "first_name", "value": "John"},
    )

    orchestrator.record_activity(
        session.token,
        activity_type="field_change",
        data={"field_id": "last_name", "value": "Smith"},
    )

    print("\nRecorded 3 activities in session")

    # Get session with activities
    updated_session = orchestrator.store.get_session(session.token, include_activities=True)
    if updated_session:
        print(f"Session now has {len(updated_session.activities)} activities")
        if updated_session.seconds_since_activity is not None:
            print(f"Last activity: {updated_session.seconds_since_activity:.1f}s ago")
        else:
            print("No activities recorded yet")

    # -----------------------------------------------------
    # PATTERN 3: Activity Monitoring with Triggers
    # -----------------------------------------------------
    print("\n### PATTERN 3: Activity Monitoring with Triggers ###\n")

    # Add inactivity trigger
    inactivity_trigger = Trigger(
        name="inactivity_warning",
        condition=TriggerCondition(
            type=ConditionType.NO_ACTIVITY,
            params={"duration_seconds": 2},  # Short for demo
        ),
        action=TriggerAction(
            type=ActionType.DASHBOARD_ALERT,
            params={
                "message": "User seems stuck. May need assistance.",
                "urgency": "high",
            },
        ),
        max_fires_per_session=3,
        cooldown_seconds=1,
    )
    orchestrator.add_trigger(inactivity_trigger)

    # Add field error trigger (user struggling)
    field_error_trigger = Trigger(
        name="field_struggle",
        condition=TriggerCondition(
            type=ConditionType.FIELD_ERROR,
            params={
                "field_pattern": "ssn*",
                "times": 3,
                "within_seconds": 60,
            },
        ),
        action=TriggerAction(
            type=ActionType.VOICE_PROMPT,
            params={
                "message": "I notice you're having trouble with the SSN field. Would you like me to help?",
            },
        ),
        max_fires_per_session=1,
    )
    orchestrator.add_trigger(field_error_trigger)

    print(f"Added {len(orchestrator.triggers.triggers)} triggers:")
    for t in orchestrator.triggers.triggers:
        print(f"  - {t.name} ({t.condition.type.value})")

    # Simulate user struggling with SSN field
    print("\nSimulating user struggling with SSN field...")
    for i in range(4):
        orchestrator.record_activity(
            session.token,
            activity_type="field_change",
            data={"field_id": "ssn", "value": f"invalid_{i}"},
        )
        await asyncio.sleep(0.1)

    # Check triggers manually
    print("\nChecking triggers...")
    results = await orchestrator.check_triggers()

    print(f"\nTrigger evaluation results:")
    for result in results:
        status = "FIRED" if result.fired else "not fired"
        print(f"  - {result.trigger_name}: {status}")
        if result.fired:
            print(f"    Reason: {result.reason}")

    # -----------------------------------------------------
    # PATTERN 4: Human Escalation Pathways
    # -----------------------------------------------------
    print("\n### PATTERN 4: Human Escalation Pathways ###\n")

    # Define trigger callback for human escalation
    def on_trigger(result):
        if result.fired:
            logger.info(
                f"ESCALATION: Trigger '{result.trigger_name}' suggests human intervention"
            )

    orchestrator.on_trigger_fired(on_trigger)

    # Simulate inactivity (wait for trigger)
    print("Simulating user inactivity (waiting 3 seconds)...")
    await asyncio.sleep(3)

    # Manual trigger check
    results = await orchestrator.check_triggers()
    fired_count = sum(1 for r in results if r.fired)
    print(f"\n{fired_count} trigger(s) fired during inactivity check")

    # -----------------------------------------------------
    # Session Lifecycle
    # -----------------------------------------------------
    print("\n### Session Lifecycle ###\n")

    # Complete the session
    orchestrator.complete(session.token)
    final_session = orchestrator.get_session(session.token, include_activities=True)

    if final_session:
        print(f"Session {final_session.token}:")
        print(f"  Final status: {final_session.status.value}")
        print(f"  Total activities: {len(final_session.activities)}")
        print(f"  Duration: {(final_session.updated_at - final_session.created_at).total_seconds():.1f}s")

    # Final stats
    print("\n### Final Statistics ###\n")
    print(f"Orchestrator stats: {orchestrator.stats()}")

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
