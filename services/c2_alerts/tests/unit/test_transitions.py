"""Alert state machine (C2 plan §4.2): all 4 statuses x 3 actions."""

from __future__ import annotations

import pytest
from app.services.lifecycle import TRANSITIONS, allowed_actions

# (status, action) -> resulting status, or None when the action is invalid (409).
TABLE = {
    ("open", "acknowledge"): "acknowledged",
    ("open", "resolve"): None,
    ("open", "false_positive"): "false_positive",
    ("acknowledged", "acknowledge"): None,
    ("acknowledged", "resolve"): "resolved",
    ("acknowledged", "false_positive"): "false_positive",
    ("resolved", "acknowledge"): None,
    ("resolved", "resolve"): None,
    ("resolved", "false_positive"): None,
    ("false_positive", "acknowledge"): None,
    ("false_positive", "resolve"): None,
    ("false_positive", "false_positive"): None,
}


@pytest.mark.parametrize(("status", "action"), sorted(TABLE))
def test_transition_table(status, action):
    sources, target = TRANSITIONS[action]
    expected = TABLE[(status, action)]
    assert (status in sources) is (expected is not None)
    if expected is not None:
        assert target == expected


@pytest.mark.parametrize(
    ("status", "actions"),
    [
        ("open", ["acknowledge", "false_positive"]),
        ("acknowledged", ["resolve", "false_positive"]),
        ("resolved", []),
        ("false_positive", []),
    ],
)
def test_allowed_actions(status, actions):
    assert allowed_actions(status) == actions
