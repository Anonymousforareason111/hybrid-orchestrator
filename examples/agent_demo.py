#!/usr/bin/env python3
"""
Demo: Hybrid Human-AI Orchestration with Claude Agent

This example demonstrates actual AI decision-making:
    - AI analyzes user behavior patterns
    - AI decides when to intervene
    - AI generates contextual responses
    - AI knows when to escalate to humans

This uses MockClaudeAgent for testing without API calls.
Set ANTHROPIC_API_KEY to use real Claude.

Run: python examples/agent_demo.py
"""

import asyncio
import logging
import os
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
)
from core.agents import AgentConfig
from core.agents.claude import MockClaudeAgent, ClaudeAgent
from core.agents.base import ActionType as AgentActionType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_agent():
    """Get agent - real Claude if API key available, mock otherwise."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("Using real Claude agent (ANTHROPIC_API_KEY found)")
        return ClaudeAgent(AgentConfig(
            model="claude-sonnet-4-20250514",
            temperature=0.7,
        ))
    else:
        logger.info("Using mock agent (set ANTHROPIC_API_KEY for real Claude)")
        return MockClaudeAgent()


async def simulate_user_session(orchestrator, agent):
    """Simulate a user session with AI-powered intervention."""

    print("\n" + "=" * 70)
    print("SIMULATING USER SESSION")
    print("=" * 70)

    # Create session with recipient
    recipient = Recipient(
        id="user_456",
        name="Sarah Johnson",
        phone="+1-555-0123",
        email="sarah@example.com",
    )

    session = orchestrator.create_session(
        external_id="form_session_789",
        metadata={
            "form_type": "insurance_application",
            "step": "personal_info",
            "started_via": "web",
        },
        recipient=recipient,
    )

    print(f"\nSession started: {session.token}")
    print(f"User: {recipient.name}")

    # --- Phase 1: User starts filling form normally ---
    print("\n--- Phase 1: User starts filling form ---")

    activities = [
        ("field_change", {"field_id": "first_name", "value": "Sarah"}),
        ("field_change", {"field_id": "last_name", "value": "Johnson"}),
        ("field_change", {"field_id": "email", "value": "sarah@example.com"}),
    ]

    for activity_type, data in activities:
        orchestrator.record_activity(session.token, activity_type, data)
        print(f"  User filled: {data['field_id']}")
        await asyncio.sleep(0.1)

    # Ask AI to analyze
    session = orchestrator.get_session(session.token, include_activities=True)
    response = await agent.analyze(
        session_summary=f"User filling {session.metadata['form_type']}, step: {session.metadata['step']}",
        recent_activities=[{"type": a.activity_type, "data": a.data} for a in session.activities],
        context=session.metadata,
    )

    print(f"\n  AI Analysis: {response.action.value}")
    print(f"  AI Reasoning: {response.reasoning}")

    # --- Phase 2: User struggles with SSN field ---
    print("\n--- Phase 2: User struggles with SSN field ---")

    for i in range(4):
        orchestrator.record_activity(
            session.token,
            "field_change",
            {"field_id": "ssn", "value": f"invalid_attempt_{i+1}"},
        )
        print(f"  User attempt {i+1}: Invalid SSN entered")
        await asyncio.sleep(0.1)

    # Ask AI to analyze again
    session = orchestrator.get_session(session.token, include_activities=True)
    response = await agent.analyze(
        session_summary=f"User filling {session.metadata['form_type']}, step: {session.metadata['step']}",
        recent_activities=[{"type": a.activity_type, "data": a.data} for a in session.activities],
        context=session.metadata,
    )

    print(f"\n  AI Analysis: {response.action.value}")
    print(f"  AI Reasoning: {response.reasoning}")

    if response.action == AgentActionType.PROMPT_USER and response.message:
        print(f"\n  >>> AI INTERVENTION <<<")
        print(f"  AI says: \"{response.message}\"")

    # --- Phase 3: User asks for help ---
    print("\n--- Phase 3: User asks for help ---")

    user_message = "I don't understand what format you need for the SSN"
    print(f"  User: \"{user_message}\"")

    ai_response = await agent.generate_response(
        user_input=user_message,
        session_context={
            "current_field": "ssn",
            "attempts": 4,
            "form_type": "insurance_application",
        },
    )

    print(f"  AI: \"{ai_response}\"")

    # --- Phase 4: User requests human ---
    print("\n--- Phase 4: User requests human agent ---")

    user_message = "Can I please speak to a real person?"
    print(f"  User: \"{user_message}\"")

    ai_response = await agent.generate_response(
        user_input=user_message,
        session_context=session.metadata,
    )

    print(f"  AI: \"{ai_response}\"")

    # Check if AI suggests escalation
    response = await agent.analyze(
        session_summary="User explicitly requested human agent",
        recent_activities=[
            {"type": "user_request", "data": {"request": "speak to human"}}
        ],
        context={"escalation_requested": True},
    )

    if response.action == AgentActionType.ESCALATE:
        print(f"\n  >>> ESCALATING TO HUMAN <<<")
        print(f"  Reason: {response.escalation_reason or response.reasoning}")

    # Complete session
    orchestrator.complete(session.token)
    print(f"\nSession completed: {session.token}")

    return session


async def main():
    """Run the agent demo."""

    print("\n" + "=" * 70)
    print("HYBRID HUMAN-AI ORCHESTRATION - AGENT DEMO")
    print("=" * 70)

    # Create orchestrator
    orchestrator = Orchestrator(db_path=":memory:")
    orchestrator.channels.register(ConsoleChannel())

    # Get agent
    agent = get_agent()

    # Run simulation
    await simulate_user_session(orchestrator, agent)

    # Stats
    print("\n" + "=" * 70)
    print("DEMO STATISTICS")
    print("=" * 70)

    if hasattr(agent, 'call_count'):
        print(f"Agent calls: {agent.call_count}")

    print(f"Orchestrator stats: {orchestrator.stats()}")

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
