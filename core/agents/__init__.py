"""
Agent module for AI agent integration.

This is where the actual AI lives.
"""

from .base import Agent, AgentConfig, AgentResponse
from .claude import ClaudeAgent

__all__ = ["Agent", "AgentConfig", "AgentResponse", "ClaudeAgent"]
