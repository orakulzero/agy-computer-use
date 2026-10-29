# tests/test_safe_overlay_validators.py
from __future__ import annotations

from agy_computer_use.safe_overlay import VALID_ANCHORS, SafeBadgePlacement

def test_validate_anchor_position():
    """Test the validation of anchor positions."""
    from agy_computer_use.safe_overlay import _validate_anchor_position

    # Test valid anchor positions
    assert _validate_anchor_position("top_left_outside") is True
    assert _validate_anchor_position("top_right_outside") is True
    assert _validate_anchor_position("bottom_left_outside") is True
    assert _validate_anchor_position("bottom_right_outside") is True
    assert _validate_anchor_position("interior_fallback") is True

    # Test invalid anchor positions
    assert _validate_anchor_position("invalid_anchor") is False
    assert _validate_anchor_position("top_left") is False
    assert _validate_anchor_position("") is False

    # Test edge cases
    assert _validate_anchor_position(None) is False
    assert _validate_anchor_position(123) is False

def _validate_anchor_position(anchor: str) -> bool:
    """Validate if the given anchor position is one of the valid options."""
    return anchor in VALID_ANCHORS
