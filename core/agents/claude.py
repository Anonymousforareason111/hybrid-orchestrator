"""
Claude agent implementation using Anthropic API.

This is the actual AI integration - not just class names with "agent" in them.
"""

import json
import logging
import os
from typing import Optional

from .base import Agent, AgentConfig, AgentResponse, ActionType

logger = logging.getLogger(__name__)

# Check for anthropic library
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    anthropic = None


DEFAULT_SYSTEM_PROMPT = """You are an AI assistant helping users complete forms and processes.

Your job is to:
1. Analyze user behavior and session state
2. Decide if intervention is needed
3. Provide helpful guidance when users are stuck
4. Know when to escalate to a human

You must respond with a JSON object containing:
- action: one of "continue", "prompt_user", "escalate", "complete", "abort"
- message: what to say to the user (if prompting)
- reasoning: why you made this decision
- confidence: 0-1 how confident you are

Be concise. Users are busy. Don't over-explain."""


ANALYSIS_PROMPT = """Analyze this session and decide what action to take.

SESSION SUMMARY:
{session_summary}

RECENT ACTIVITIES:
{activities}

ADDITIONAL CONTEXT:
{context}

Based on this information, what should happen next?
Respond with a JSON object containing: action, message, reasoning, confidence."""


class ClaudeAgent(Agent):
    """
    Agent powered by Claude (Anthropic API).

    Requires ANTHROPIC_API_KEY environment variable.
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        if not HAS_ANTHROPIC:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        config = config or AgentConfig()
        super().__init__(config)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable required")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT

    async def analyze(
        self,
        session_summary: str,
        recent_activities: list[dict],
        context: Optional[dict] = None,
    ) -> AgentResponse:
        """
        Use Claude to analyze session and decide action.
        """
        # Format activities for the prompt
        activities_text = "\n".join(
            f"- {a.get('type', 'unknown')}: {a.get('data', {})}"
            for a in recent_activities[-10:]  # Last 10
        )

        prompt = ANALYSIS_PROMPT.format(
            session_summary=session_summary,
            activities=activities_text or "(no activities)",
            context=json.dumps(context or {}, indent=2),
        )

        try:
            # Call Claude API (sync wrapper for now)
            message = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse response
            response_text = message.content[0].text
            return self._parse_response(response_text)

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            return AgentResponse(
                action=ActionType.CONTINUE,
                reasoning=f"API error, defaulting to continue: {e}",
                confidence=0.0,
            )

    async def generate_response(
        self,
        user_input: str,
        session_context: dict,
    ) -> str:
        """
        Generate a response to user input using Claude.
        """
        context_summary = json.dumps(session_context, indent=2)

        prompt = f"""The user said: "{user_input}"

Current session context:
{context_summary}

Respond helpfully and concisely. If they need human help, say so."""

        try:
            message = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )

            return message.content[0].text

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            return "I'm having trouble right now. Let me connect you with someone who can help."

    def _parse_response(self, text: str) -> AgentResponse:
        """Parse Claude's JSON response into AgentResponse."""
        try:
            # Try to extract JSON from response
            # Claude might wrap it in markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())

            action_str = data.get("action", "continue").lower()
            action_map = {
                "continue": ActionType.CONTINUE,
                "prompt_user": ActionType.PROMPT_USER,
                "escalate": ActionType.ESCALATE,
                "complete": ActionType.COMPLETE,
                "abort": ActionType.ABORT,
            }

            return AgentResponse(
                action=action_map.get(action_str, ActionType.CONTINUE),
                message=data.get("message"),
                reasoning=data.get("reasoning"),
                confidence=float(data.get("confidence", 0.8)),
                escalation_reason=data.get("escalation_reason"),
                suggested_human_action=data.get("suggested_human_action"),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {text}")

            # Fall back to treating entire response as a message
            return AgentResponse(
                action=ActionType.PROMPT_USER,
                message=text[:500],  # Truncate if too long
                reasoning="Could not parse structured response",
                confidence=0.5,
            )


class MockClaudeAgent(Agent):
    """
    Mock agent for testing without API calls.
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        super().__init__(config or AgentConfig())
        self.call_count = 0
        self.last_input = None

    async def analyze(
        self,
        session_summary: str,
        recent_activities: list[dict],
        context: Optional[dict] = None,
    ) -> AgentResponse:
        self.call_count += 1
        self.last_input = {
            "summary": session_summary,
            "activities": recent_activities,
            "context": context,
        }

        # Simple rule-based mock
        activity_count = len(recent_activities)

        if activity_count == 0:
            return AgentResponse(
                action=ActionType.PROMPT_USER,
                message="Hi! How can I help you today?",
                reasoning="No activities yet, greeting user",
                confidence=0.9,
            )

        # Check for repeated field errors
        field_changes = [a for a in recent_activities if a.get("type") == "field_change"]
        if len(field_changes) >= 3:
            fields = [a.get("data", {}).get("field_id") for a in field_changes]
            if len(set(fields)) == 1:  # Same field repeated
                return AgentResponse(
                    action=ActionType.PROMPT_USER,
                    message=f"I notice you're having trouble with the {fields[0]} field. Need help?",
                    reasoning="User changed same field multiple times",
                    confidence=0.85,
                )

        return AgentResponse(
            action=ActionType.CONTINUE,
            reasoning="User progressing normally",
            confidence=0.9,
        )

    async def generate_response(
        self,
        user_input: str,
        session_context: dict,
    ) -> str:
        self.call_count += 1
        self.last_input = {"user_input": user_input, "context": session_context}

        # Simple mock responses
        lower = user_input.lower()

        if "help" in lower:
            return "I'm here to help! What are you stuck on?"
        if "human" in lower or "person" in lower:
            return "Let me connect you with a human agent. One moment please."
        if "thank" in lower:
            return "You're welcome! Is there anything else?"

        return "I understand. Let me know if you need any assistance."
