"""Tests for AI agents."""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agents import AgentConfig, AgentResponse
from core.agents.base import ActionType
from core.agents.claude import MockClaudeAgent


class TestMockClaudeAgent:
    """Test mock agent for testing without API calls."""

    def setup_method(self):
        self.agent = MockClaudeAgent()

    @pytest.mark.asyncio
    async def test_greets_on_no_activity(self):
        """Agent greets user when no activities exist."""
        response = await self.agent.analyze(
            session_summary="New session",
            recent_activities=[],
        )

        assert response.action == ActionType.PROMPT_USER
        assert "help" in response.message.lower()

    @pytest.mark.asyncio
    async def test_detects_field_struggle(self):
        """Agent detects when user struggles with a field."""
        activities = [
            {"type": "field_change", "data": {"field_id": "ssn"}},
            {"type": "field_change", "data": {"field_id": "ssn"}},
            {"type": "field_change", "data": {"field_id": "ssn"}},
        ]

        response = await self.agent.analyze(
            session_summary="User filling form",
            recent_activities=activities,
        )

        assert response.action == ActionType.PROMPT_USER
        assert "ssn" in response.message.lower()
        assert "trouble" in response.message.lower() or "help" in response.message.lower()

    @pytest.mark.asyncio
    async def test_continues_on_normal_progress(self):
        """Agent returns CONTINUE when user progressing normally."""
        activities = [
            {"type": "field_change", "data": {"field_id": "name"}},
            {"type": "field_change", "data": {"field_id": "email"}},
            {"type": "field_change", "data": {"field_id": "phone"}},
        ]

        response = await self.agent.analyze(
            session_summary="User filling form",
            recent_activities=activities,
        )

        assert response.action == ActionType.CONTINUE

    @pytest.mark.asyncio
    async def test_generate_response_help(self):
        """Agent responds to help requests."""
        response = await self.agent.generate_response(
            user_input="I need help with this form",
            session_context={"form_type": "application"},
        )

        assert "help" in response.lower()

    @pytest.mark.asyncio
    async def test_generate_response_human_request(self):
        """Agent recognizes request for human agent."""
        response = await self.agent.generate_response(
            user_input="Can I talk to a real person?",
            session_context={},
        )

        assert "human" in response.lower() or "connect" in response.lower()

    @pytest.mark.asyncio
    async def test_tracks_call_count(self):
        """Agent tracks number of calls for testing."""
        await self.agent.analyze("test", [])
        await self.agent.analyze("test", [])
        await self.agent.generate_response("test", {})

        assert self.agent.call_count == 3


class TestAgentResponse:
    """Test AgentResponse dataclass."""

    def test_default_values(self):
        """AgentResponse has sensible defaults."""
        response = AgentResponse(action=ActionType.CONTINUE)

        assert response.action == ActionType.CONTINUE
        assert response.message is None
        assert response.confidence == 1.0
        assert response.metadata == {}

    def test_escalation_fields(self):
        """AgentResponse can include escalation details."""
        response = AgentResponse(
            action=ActionType.ESCALATE,
            escalation_reason="User frustrated",
            suggested_human_action="Review application manually",
        )

        assert response.action == ActionType.ESCALATE
        assert response.escalation_reason == "User frustrated"


class TestAgentConfig:
    """Test AgentConfig dataclass."""

    def test_defaults(self):
        """AgentConfig has sensible defaults."""
        config = AgentConfig()

        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_tokens == 1024
        assert config.temperature == 0.7
        assert config.tools == []

    def test_custom_values(self):
        """Can customize AgentConfig."""
        config = AgentConfig(
            model="claude-opus-4-20250514",
            max_tokens=4096,
            system_prompt="You are a helpful assistant.",
        )

        assert config.model == "claude-opus-4-20250514"
        assert config.max_tokens == 4096
        assert config.system_prompt == "You are a helpful assistant."
