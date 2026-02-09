"""Tests for trigger engine."""

import pytest
from datetime import datetime, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage import Session, Activity, SessionStatus
from core.triggers import (
    TriggerEngine,
    Trigger,
    TriggerCondition,
    TriggerAction,
    ConditionType,
    ActionType,
    create_trigger_from_dict,
)


class TestTriggerEngine:
    """Test trigger evaluation."""

    def setup_method(self):
        self.engine = TriggerEngine()

    def test_add_trigger(self):
        """Can add triggers to engine."""
        trigger = Trigger(
            name="test",
            condition=TriggerCondition(type=ConditionType.NO_ACTIVITY),
            action=TriggerAction(type=ActionType.DASHBOARD_ALERT),
        )
        self.engine.add_trigger(trigger)
        assert len(self.engine.triggers) == 1

    def test_remove_trigger(self):
        """Can remove triggers by name."""
        trigger = Trigger(
            name="removable",
            condition=TriggerCondition(type=ConditionType.NO_ACTIVITY),
            action=TriggerAction(type=ActionType.DASHBOARD_ALERT),
        )
        self.engine.add_trigger(trigger)
        assert self.engine.remove_trigger("removable") is True
        assert len(self.engine.triggers) == 0

    def test_remove_nonexistent_trigger(self):
        """Removing nonexistent trigger returns False."""
        assert self.engine.remove_trigger("ghost") is False


class TestNoActivityCondition:
    """Test NO_ACTIVITY trigger condition."""

    def setup_method(self):
        self.engine = TriggerEngine()
        self.engine.add_trigger(
            Trigger(
                name="inactivity",
                condition=TriggerCondition(
                    type=ConditionType.NO_ACTIVITY,
                    params={"duration_seconds": 60},
                ),
                action=TriggerAction(type=ActionType.VOICE_PROMPT),
            )
        )

    def test_fires_when_inactive(self):
        """Fires when session has no activity for duration."""
        session = Session()
        session.activities = [
            Activity(
                session_id=session.token,
                activity_type="test",
                created_at=datetime.utcnow() - timedelta(seconds=120),
            )
        ]

        results = self.engine.evaluate(session)
        assert len(results) == 1
        assert results[0].fired is True

    def test_does_not_fire_when_active(self):
        """Does not fire when recent activity exists."""
        session = Session()
        session.activities = [
            Activity(
                session_id=session.token,
                activity_type="test",
                created_at=datetime.utcnow() - timedelta(seconds=10),
            )
        ]

        results = self.engine.evaluate(session)
        assert results[0].fired is False

    def test_fires_on_new_session_without_activity(self):
        """Fires when session is old but has no activities."""
        session = Session()
        session.created_at = datetime.utcnow() - timedelta(seconds=120)
        session.activities = []

        results = self.engine.evaluate(session)
        assert results[0].fired is True


class TestFieldErrorCondition:
    """Test FIELD_ERROR trigger condition (user struggling)."""

    def setup_method(self):
        self.engine = TriggerEngine()
        self.engine.add_trigger(
            Trigger(
                name="field_struggle",
                condition=TriggerCondition(
                    type=ConditionType.FIELD_ERROR,
                    params={
                        "field_pattern": "ssn*",
                        "times": 3,
                        "within_seconds": 60,
                    },
                ),
                action=TriggerAction(type=ActionType.VOICE_PROMPT),
            )
        )

    def test_fires_on_repeated_changes(self):
        """Fires when same field changed multiple times."""
        session = Session()
        now = datetime.utcnow()
        session.activities = [
            Activity(
                session_id=session.token,
                activity_type="field_change",
                data={"field_id": "ssn"},
                created_at=now - timedelta(seconds=30),
            ),
            Activity(
                session_id=session.token,
                activity_type="field_change",
                data={"field_id": "ssn"},
                created_at=now - timedelta(seconds=20),
            ),
            Activity(
                session_id=session.token,
                activity_type="field_change",
                data={"field_id": "ssn"},
                created_at=now - timedelta(seconds=10),
            ),
        ]

        results = self.engine.evaluate(session)
        assert results[0].fired is True

    def test_does_not_fire_under_threshold(self):
        """Does not fire when changes under threshold."""
        session = Session()
        session.activities = [
            Activity(
                session_id=session.token,
                activity_type="field_change",
                data={"field_id": "ssn"},
                created_at=datetime.utcnow(),
            ),
            Activity(
                session_id=session.token,
                activity_type="field_change",
                data={"field_id": "ssn"},
                created_at=datetime.utcnow(),
            ),
        ]

        results = self.engine.evaluate(session)
        assert results[0].fired is False

    def test_pattern_matching(self):
        """Field pattern matching works with wildcards."""
        session = Session()
        session.activities = [
            Activity(
                session_id=session.token,
                activity_type="field_change",
                data={"field_id": "ssn_primary"},
                created_at=datetime.utcnow(),
            )
            for _ in range(4)
        ]

        results = self.engine.evaluate(session)
        assert results[0].fired is True  # ssn* matches ssn_primary


class TestTriggerLimits:
    """Test max fires and cooldown behavior."""

    def test_max_fires_per_session(self):
        """Trigger stops firing after max fires reached."""
        engine = TriggerEngine()
        engine.add_trigger(
            Trigger(
                name="limited",
                condition=TriggerCondition(
                    type=ConditionType.NO_ACTIVITY,
                    params={"duration_seconds": 1},
                ),
                action=TriggerAction(type=ActionType.DASHBOARD_ALERT),
                max_fires_per_session=2,
                cooldown_seconds=0,  # No cooldown for this test
            )
        )

        session = Session()
        session.created_at = datetime.utcnow() - timedelta(seconds=60)

        # First two should fire
        assert engine.evaluate(session)[0].fired is True
        assert engine.evaluate(session)[0].fired is True

        # Third should not (max reached)
        assert engine.evaluate(session)[0].fired is False

    def test_cooldown(self):
        """Trigger respects cooldown period."""
        engine = TriggerEngine()
        engine.add_trigger(
            Trigger(
                name="cooldown_test",
                condition=TriggerCondition(
                    type=ConditionType.NO_ACTIVITY,
                    params={"duration_seconds": 1},
                ),
                action=TriggerAction(type=ActionType.DASHBOARD_ALERT),
                cooldown_seconds=60,
                max_fires_per_session=10,
            )
        )

        session = Session()
        session.created_at = datetime.utcnow() - timedelta(seconds=60)

        # First fires
        assert engine.evaluate(session)[0].fired is True

        # Second blocked by cooldown
        result = engine.evaluate(session)[0]
        assert result.fired is False
        assert "Cooldown" in result.reason


class TestCustomCondition:
    """Test custom condition function."""

    def test_custom_function(self):
        """Custom function can determine trigger firing."""
        engine = TriggerEngine()

        def check_vip(session):
            return session.metadata.get("is_vip", False)

        engine.add_trigger(
            Trigger(
                name="vip_alert",
                condition=TriggerCondition(
                    type=ConditionType.CUSTOM,
                    custom_fn=check_vip,
                ),
                action=TriggerAction(type=ActionType.DASHBOARD_ALERT),
            )
        )

        # Non-VIP doesn't fire
        session = Session(metadata={"is_vip": False})
        assert engine.evaluate(session)[0].fired is False

        # VIP fires
        vip_session = Session(metadata={"is_vip": True})
        assert engine.evaluate(vip_session)[0].fired is True


class TestCreateTriggerFromDict:
    """Test trigger creation from dictionary config."""

    def test_basic_config(self):
        """Can create trigger from dict config."""
        config = {
            "name": "from_config",
            "condition": {
                "type": "no_activity",
                "params": {"duration_seconds": 120},
            },
            "action": {
                "type": "voice_prompt",
                "params": {"message": "Hello"},
            },
            "max_fires_per_session": 3,
            "cooldown_seconds": 30,
        }

        trigger = create_trigger_from_dict(config)

        assert trigger.name == "from_config"
        assert trigger.condition.type == ConditionType.NO_ACTIVITY
        assert trigger.condition.params["duration_seconds"] == 120
        assert trigger.action.type == ActionType.VOICE_PROMPT
        assert trigger.max_fires_per_session == 3
        assert trigger.cooldown_seconds == 30

    def test_defaults(self):
        """Missing config values get defaults."""
        config = {"name": "minimal"}
        trigger = create_trigger_from_dict(config)

        assert trigger.name == "minimal"
        assert trigger.condition.type == ConditionType.NO_ACTIVITY
        assert trigger.max_fires_per_session == 1
