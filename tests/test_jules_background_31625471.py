"""ISO 9001:2015 Agile V Verification Suite for REQ-CUA-BG-01 Background Window Capture."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_capture_window_background_returns_complete_frame_dict() -> None:
    """REQ-CUA-BG-01: capture_window_background returns a fully populated frame record."""
    from agy_computer_use.background import capture_window_background

    result = capture_window_background(0, fallback_width=64, fallback_height=48, fallback_seed=7)
    assert isinstance(result, dict)
    for key in (
        "hwnd", "desktop_name", "backend", "width", "height", "window_rect",
        "rgb_bytes", "bmp_bytes", "png_bytes", "dhash64", "sha256", "timestamp",
    ):
        assert key in result, f"missing key: {key}"
    assert result["hwnd"] == 0
    assert result["desktop_name"] == "Default"
    assert result["backend"] in ("win32_printwindow", "synthetic_fallback")
    assert result["width"] == 64 and result["height"] == 48
    assert len(result["rgb_bytes"]) == 64 * 48 * 3
    assert result["bmp_bytes"][:2] == b"BM"
    assert result["png_bytes"][:8] == b"\x89PNG\r\n\x1a\n"
    assert isinstance(result["dhash64"], int)
    assert result["sha256"] == hashlib.sha256(result["png_bytes"]).hexdigest()
    assert isinstance(result["timestamp"], float) and result["timestamp"] > 0.0


def test_capture_window_background_fallback_is_deterministic() -> None:
    """REQ-CUA-BG-01: identical fallback seed yields byte-identical frames."""
    from agy_computer_use.background import capture_window_background

    a = capture_window_background(0, fallback_width=32, fallback_height=32, fallback_seed=42)
    b = capture_window_background(0, fallback_width=32, fallback_height=32, fallback_seed=42)
    assert a["rgb_bytes"] == b["rgb_bytes"]
    assert a["sha256"] == b["sha256"]
    assert a["dhash64"] == b["dhash64"]


def test_capture_window_background_clamps_tiny_fallback_dimensions() -> None:
    """REQ-CUA-BG-01: fallback dimensions are clamped to a minimum of 16 pixels."""
    from agy_computer_use.background import capture_window_background

    result = capture_window_background(0, fallback_width=1, fallback_height=1, fallback_seed=1)
    assert result["width"] >= 16
    assert result["height"] >= 16
    assert len(result["rgb_bytes"]) == result["width"] * result["height"] * 3
    assert result["window_rect"] == (0, 0, result["width"], result["height"])
