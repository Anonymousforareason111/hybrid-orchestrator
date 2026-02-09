"""
Base agent interface.

Agents are AI models that can analyze sessions and decide actions.
This is the actual "AI" in "Hybrid Human-AI Orchestrator."
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


class ActionType(Enum):
    """What the agent decided to do."""
    CONTINUE = "continue"           # Keep going, no intervention needed
    PROMPT_USER = "prompt_user"     # Say something to the user
    ESCALATE = "escalate"           # Hand off to human
    COMPLETE = "complete"           # Task is done
    ABORT = "abort"                 # Something is wrong, stop


@dataclass
class AgentConfig:
    """Configuration for an agent."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    temperature: float = 0.7
    system_prompt: Optional[str] = None
    tools: list[dict] = field(default_factory=list)


@dataclass
class AgentResponse:
    """What the agent decided after analyzing the session."""
    action: ActionType
    message: Optional[str] = None       # What to say to user (if PROMPT_USER)
    reasoning: Optional[str] = None     # Why the agent made this decision
    confidence: float = 1.0             # How confident (0-1)
    metadata: dict = field(default_factory=dict)

    # For escalation
    escalation_reason: Optional[str] = None
    suggested_human_action: Optional[str] = None


class Agent(ABC):
    """
    Abstract base class for AI agents.

    An agent analyzes session state and decides what to do next.
    This is the decision-making brain of the orchestrator.
    """

    def __init__(self, config: AgentConfig):
        self.config = config

    @abstractmethod
    async def analyze(
        self,
        session_summary: str,
        recent_activities: list[dict],
        context: Optional[dict] = None,
    ) -> AgentResponse:
        """
        Analyze the current session state and decide what to do.

        Args:
            session_summary: Human-readable summary of the session.
            recent_activities: Last N activities in the session.
            context: Additional context (form data, user history, etc.)

        Returns:
            AgentResponse with the decision and reasoning.
        """
        pass

    @abstractmethod
    async def generate_response(
        self,
        user_input: str,
        session_context: dict,
    ) -> str:
        """
        Generate a response to user input.

        Args:
            user_input: What the user said/did.
            session_context: Current session state.

        Returns:
            Text response to send to user.
        """
        pass
