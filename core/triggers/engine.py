"""
Trigger engine for evaluating conditions and firing actions.

The engine evaluates triggers against sessions and returns results.
Actual action execution is handled by the channel hub.
"""

import fnmatch
import logging
from datetime import datetime, timedelta
from typing import Optional

from ..storage import Session, Activity
from .models import (
    Trigger,
    TriggerResult,
    TriggerCondition,
    ConditionType,
    ActionType,
)

logger = logging.getLogger(__name__)


class TriggerEngine:
    """
    Engine for evaluating triggers against sessions.

    Usage:
        engine = TriggerEngine()

        # Add triggers
        engine.add_trigger(Trigger(
            name="inactivity_warning",
            condition=TriggerCondition(
                type=ConditionType.NO_ACTIVITY,
                params={"duration_seconds": 120}
            ),
            action=TriggerAction(
                type=ActionType.VOICE_PROMPT,
                params={"message": "Still there?"}
            ),
            max_fires_per_session=2,
        ))

        # Evaluate against a session
        results = engine.evaluate(session)
        for result in results:
            if result.fired:
                # Handle the action via channel hub
                channel_hub.execute(result)
    """

    def __init__(self):
        self.triggers: list[Trigger] = []

    def add_trigger(self, trigger: Trigger) -> None:
        """Add a trigger to the engine."""
        self.triggers.append(trigger)
        logger.info(f"Added trigger: {trigger.name}")

    def remove_trigger(self, name: str) -> bool:
        """Remove a trigger by name. Returns True if found."""
        for i, t in enumerate(self.triggers):
            if t.name == name:
                self.triggers.pop(i)
                logger.info(f"Removed trigger: {name}")
                return True
        return False

    def evaluate(self, session: Session) -> list[TriggerResult]:
        """
        Evaluate all triggers against a session.

        Args:
            session: Session to evaluate (should include activities).

        Returns:
            List of TriggerResults (one per trigger, fired or not).
        """
        results = []

        for trigger in self.triggers:
            result = self._evaluate_trigger(trigger, session)
            results.append(result)

            if result.fired:
                logger.info(
                    f"Trigger '{trigger.name}' fired for session {session.token}: {result.reason}"
                )

        return results

    def evaluate_all(self, sessions: list[Session]) -> list[TriggerResult]:
        """Evaluate triggers against multiple sessions."""
        all_results = []
        for session in sessions:
            results = self.evaluate(session)
            all_results.extend([r for r in results if r.fired])
        return all_results

    def _evaluate_trigger(self, trigger: Trigger, session: Session) -> TriggerResult:
        """Evaluate a single trigger against a session."""

        # Check session filter
        if trigger.session_filter and not trigger.session_filter(session):
            return TriggerResult(
                trigger_name=trigger.name,
                session_token=session.token,
                fired=False,
                reason="Session filtered out",
            )

        # Check max fires
        fires = trigger.fires_count.get(session.token, 0)
        if fires >= trigger.max_fires_per_session:
            return TriggerResult(
                trigger_name=trigger.name,
                session_token=session.token,
                fired=False,
                reason=f"Max fires reached ({fires}/{trigger.max_fires_per_session})",
            )

        # Check cooldown
        last_fired = trigger.last_fired.get(session.token)
        if last_fired:
            elapsed = (datetime.utcnow() - last_fired).total_seconds()
            if elapsed < trigger.cooldown_seconds:
                return TriggerResult(
                    trigger_name=trigger.name,
                    session_token=session.token,
                    fired=False,
                    reason=f"Cooldown active ({elapsed:.0f}s < {trigger.cooldown_seconds}s)",
                )

        # Evaluate condition
        condition_met, reason = self._check_condition(trigger.condition, session)

        if not condition_met:
            return TriggerResult(
                trigger_name=trigger.name,
                session_token=session.token,
                fired=False,
                reason=reason,
            )

        # Condition met - update tracking
        trigger.fires_count[session.token] = fires + 1
        trigger.last_fired[session.token] = datetime.utcnow()

        return TriggerResult(
            trigger_name=trigger.name,
            session_token=session.token,
            fired=True,
            action_type=trigger.action.type,
            action_params=trigger.action.params,
            reason=reason,
        )

    def _check_condition(
        self, condition: TriggerCondition, session: Session
    ) -> tuple[bool, str]:
        """
        Check if a condition is met.

        Returns:
            (met, reason) tuple.
        """

        if condition.type == ConditionType.NO_ACTIVITY:
            return self._check_no_activity(condition, session)

        elif condition.type == ConditionType.FIELD_CHANGED:
            return self._check_field_changed(condition, session)

        elif condition.type == ConditionType.FIELD_ERROR:
            return self._check_field_error(condition, session)

        elif condition.type == ConditionType.STATUS_CHANGED:
            return self._check_status_changed(condition, session)

        elif condition.type == ConditionType.CUSTOM:
            if condition.custom_fn:
                try:
                    result = condition.custom_fn(session)
                    return bool(result), "Custom condition"
                except Exception as e:
                    logger.error(f"Custom condition error: {e}")
                    return False, f"Custom condition error: {e}"
            return False, "No custom function defined"

        return False, f"Unknown condition type: {condition.type}"

    def _check_no_activity(
        self, condition: TriggerCondition, session: Session
    ) -> tuple[bool, str]:
        """Check if session has been inactive for N seconds."""
        duration = condition.params.get("duration_seconds", 120)

        if session.seconds_since_activity is None:
            # No activities yet - check session creation time
            elapsed = (datetime.utcnow() - session.created_at).total_seconds()
            if elapsed >= duration:
                return True, f"No activities and session is {elapsed:.0f}s old"
            return False, f"Session too new ({elapsed:.0f}s < {duration}s)"

        if session.seconds_since_activity >= duration:
            return True, f"No activity for {session.seconds_since_activity:.0f}s (threshold: {duration}s)"

        return False, f"Activity {session.seconds_since_activity:.0f}s ago (threshold: {duration}s)"

    def _check_field_changed(
        self, condition: TriggerCondition, session: Session
    ) -> tuple[bool, str]:
        """Check if a specific field was changed."""
        field_pattern = condition.params.get("field_pattern", "*")

        # Look at recent activities for field changes
        for activity in session.activities[:10]:  # Check last 10
            if activity.activity_type == "field_change":
                field_id = activity.data.get("field_id", "")
                if fnmatch.fnmatch(field_id, field_pattern):
                    return True, f"Field '{field_id}' changed"

        return False, f"No matching field change for pattern '{field_pattern}'"

    def _check_field_error(
        self, condition: TriggerCondition, session: Session
    ) -> tuple[bool, str]:
        """Check if same field was changed multiple times (user struggling)."""
        field_pattern = condition.params.get("field_pattern", "*")
        times = condition.params.get("times", 3)
        within_seconds = condition.params.get("within_seconds", 60)

        cutoff = datetime.utcnow() - timedelta(seconds=within_seconds)
        field_counts: dict[str, int] = {}

        for activity in session.activities:
            if activity.created_at < cutoff:
                continue
            if activity.activity_type == "field_change":
                field_id = activity.data.get("field_id", "")
                if fnmatch.fnmatch(field_id, field_pattern):
                    field_counts[field_id] = field_counts.get(field_id, 0) + 1

        for field_id, count in field_counts.items():
            if count >= times:
                return True, f"Field '{field_id}' changed {count} times in {within_seconds}s"

        return False, f"No field changed {times}+ times in {within_seconds}s"

    def _check_status_changed(
        self, condition: TriggerCondition, session: Session
    ) -> tuple[bool, str]:
        """Check if session status matches a value."""
        target_status = condition.params.get("status")
        if target_status and session.status.value == target_status:
            return True, f"Session status is '{target_status}'"
        return False, f"Session status is '{session.status.value}', not '{target_status}'"


def create_trigger_from_dict(config: dict) -> Trigger:
    """
    Create a trigger from a dictionary configuration.

    Useful for loading triggers from YAML/JSON config files.

    Example config:
        {
            "name": "inactivity_warning",
            "condition": {
                "type": "no_activity",
                "params": {"duration_seconds": 120}
            },
            "action": {
                "type": "voice_prompt",
                "params": {"message": "Need help?"}
            },
            "max_fires_per_session": 2,
            "cooldown_seconds": 60
        }
    """
    from .models import TriggerCondition, TriggerAction

    condition_config = config.get("condition", {})
    action_config = config.get("action", {})

    condition = TriggerCondition(
        type=ConditionType(condition_config.get("type", "no_activity")),
        params=condition_config.get("params", {}),
    )

    action = TriggerAction(
        type=ActionType(action_config.get("type", "dashboard_alert")),
        params=action_config.get("params", {}),
    )

    return Trigger(
        name=config.get("name", "unnamed_trigger"),
        condition=condition,
        action=action,
        max_fires_per_session=config.get("max_fires_per_session", 1),
        cooldown_seconds=config.get("cooldown_seconds", 60),
    )
