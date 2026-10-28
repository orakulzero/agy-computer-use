"""ISO 9001:2015 Agile V Verification Suite for CLI HWND Resolution.

Covers REQ-CU-006: `_resolve_hwnd` must gracefully handle whitespace-only
title substrings without raising, returning the original (0, title) tuple.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_resolve_hwnd_whitespace_only_title_returns_original() -> None:
    """REQ-CU-006: Whitespace-only title must not match any window; returns (0, title)."""
    from agy_computer_use.cli import _resolve_hwnd

    hwnd, title = _resolve_hwnd(0, "  ")
    assert hwnd == 0
    assert title == "  "


def test_resolve_hwnd_nonzero_handle_short_circuits() -> None:
    """REQ-CU-006: Non-zero HWND bypasses title lookup and returns empty title."""
    from agy_computer_use.cli import _resolve_hwnd

    hwnd, title = _resolve_hwnd(4242, "  ")
    assert hwnd == 4242
    assert title == ""


def test_resolve_hwnd_none_title_returns_zero_and_empty() -> None:
    """REQ-CU-006: Missing title with zero HWND yields (0, "")."""
    from agy_computer_use.cli import _resolve_hwnd

    hwnd, title = _resolve_hwnd(0, None)
    assert hwnd == 0
    assert title == ""


def test_resolve_hwnd_returns_tuple_of_int_and_str() -> None:
    """REQ-CU-006: Return contract is a 2-tuple of (int, str)."""
    from agy_computer_use.cli import _resolve_hwnd

    result = _resolve_hwnd(0, "  ")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], int)
    assert isinstance(result[1], str)
