"""Tests for template matching edge cases and boundary inputs.

Covers REQ-CUA-203 (SAD/NCC template matching, zero-variance matching, dimensional checks).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agy_computer_use.template_matcher import find_visual_anchor_on_screen


def create_solid_rgb(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    """Create a solid color RGB byte sequence."""
    return bytes([color[0], color[1], color[2]] * (width * height))


def create_screen_with_patch(
    sw: int, sh: int, bg_color: tuple[int, int, int],
    pw: int, ph: int, px: int, py: int, p_color: tuple[int, int, int]
) -> bytes:
    """Create a solid background screen with a solid patch at (px, py)."""
    screen = bytearray(create_solid_rgb(sw, sh, bg_color))
    for y in range(ph):
        for x in range(pw):
            if 0 <= py + y < sh and 0 <= px + x < sw:
                idx = ((py + y) * sw + (px + x)) * 3
                screen[idx] = p_color[0]
                screen[idx + 1] = p_color[1]
                screen[idx + 2] = p_color[2]
    return bytes(screen)


def test_solid_color_template_exact_match_sad() -> None:
    """Test SAD method with a solid color template and a matching region."""
    sw, sh = 100, 100
    tw, th = 20, 20
    bg_color = (0, 0, 0)
    fg_color = (255, 0, 0)
    
    screen_rgb = create_screen_with_patch(sw, sh, bg_color, tw, th, 10, 10, fg_color)
    template_rgb = create_solid_rgb(tw, th, fg_color)
    
    res = find_visual_anchor_on_screen(
        screen_rgb, sw, sh,
        template_rgb, tw, th,
        method="SAD", threshold=0.9
    )
    
    assert res["found"] is True
    assert res["match_score"] == 1.0
    assert res["location_px"] == (10, 10)


def test_solid_color_template_exact_match_ncc() -> None:
    """Test NCC method with a solid color template and a matching region."""
    sw, sh = 100, 100
    tw, th = 20, 20
    bg_color = (0, 0, 0)
    fg_color = (255, 0, 0)
    
    screen_rgb = create_screen_with_patch(sw, sh, bg_color, tw, th, 10, 10, fg_color)
    template_rgb = create_solid_rgb(tw, th, fg_color)
    
    res = find_visual_anchor_on_screen(
        screen_rgb, sw, sh,
        template_rgb, tw, th,
        method="NCC", threshold=0.9
    )
    
    assert res["found"] is True
    assert res["match_score"] == 1.0
    assert res["location_px"] == (10, 10)


def test_invalid_dimensions() -> None:
    """Test boundary checks for invalid dimensions."""
    sw, sh = 100, 100
    screen_rgb = create_solid_rgb(sw, sh, (0, 0, 0))
    template_rgb = create_solid_rgb(10, 10, (255, 255, 255))
    
    with pytest.raises(ValueError, match="Screen dimensions must be positive integers"):
        find_visual_anchor_on_screen(screen_rgb, -1, sh, template_rgb, 10, 10)
        
    with pytest.raises(ValueError, match="Template dimensions must be positive integers"):
        find_visual_anchor_on_screen(screen_rgb, sw, sh, template_rgb, 10, -10)
        
    with pytest.raises(ValueError, match="Template dimensions exceed screen dimensions"):
        find_visual_anchor_on_screen(screen_rgb, 5, 5, template_rgb, 10, 10)


def test_byte_length_mismatch() -> None:
    """Test mismatch between dimensions and byte array length."""
    sw, sh = 10, 10
    screen_rgb = create_solid_rgb(sw, sh, (0, 0, 0))
    template_rgb = create_solid_rgb(5, 5, (255, 255, 255))
    
    with pytest.raises(ValueError, match="screen_rgb byte length mismatch"):
        find_visual_anchor_on_screen(screen_rgb[:-1], sw, sh, template_rgb, 5, 5)
        
    with pytest.raises(ValueError, match="template_rgb byte length mismatch"):
        find_visual_anchor_on_screen(screen_rgb, sw, sh, template_rgb[:-1], 5, 5)


def test_invalid_method() -> None:
    """Test unsupported matching method."""
    sw, sh = 10, 10
    screen_rgb = create_solid_rgb(sw, sh, (0, 0, 0))
    template_rgb = create_solid_rgb(5, 5, (255, 255, 255))
    
    with pytest.raises(ValueError, match="Unsupported matching method: UNKNOWN"):
        find_visual_anchor_on_screen(screen_rgb, sw, sh, template_rgb, 5, 5, method="UNKNOWN")
