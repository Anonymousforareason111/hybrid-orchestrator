"""
Trigger module for activity monitoring and intervention.

Pattern 3: Detect user behavior patterns and trigger interventions.
"""

from .engine import TriggerEngine, create_trigger_from_dict
from .models import (
    Trigger,
    TriggerCondition,
    TriggerAction,
    TriggerResult,
    ConditionType,
    ActionType,
)

__all__ = [
    "TriggerEngine",
    "create_trigger_from_dict",
    "Trigger",
    "TriggerCondition",
    "TriggerAction",
    "TriggerResult",
    "ConditionType",
    "ActionType",
]
