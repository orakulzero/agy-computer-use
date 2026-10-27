"""Verification Suite for Background Computer Use & Ghost Desktop (REQ-CUA-BG-01..03)."""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from agy_computer_use import (
    ComputerUseSafetyAbort,
    GhostDesktopSession,
    VisualActionOracle,
    capture_window_background,
    dispatch_background_window_action,
    enumerate_visible_windows,
    handle_jsonrpc_request,
    restore_window_onscreen,
    stage_window_offscreen,
)


def test_req_cua_bg_01_printwindow_background_capture() -> None:
    """REQ-CUA-BG-01: Verify background window capture via PrintWindow(PW_RENDERFULLCONTENT)."""
    windows = enumerate_visible_windows()
    if windows:
        target_hwnd = int(windows[0]["hwnd"])
        frame = capture_window_background(target_hwnd)
        assert frame["hwnd"] == target_hwnd
        assert frame["width"] > 0
        assert frame["height"] > 0
        assert frame["png_bytes"].startswith(b"\x89PNG\r\n\x1a\n")
        assert isinstance(frame["dhash64"], int)
        assert len(frame["sha256"]) == 64
    else:
        frame = capture_window_background(0, fallback_seed=303, fallback_width=320, fallback_height=240)
        assert frame["backend"] == "synthetic_fallback"
        assert frame["width"] == 320
        assert frame["height"] == 240
        assert frame["png_bytes"].startswith(b"\x89PNG\r\n\x1a\n")


def test_req_cua_bg_02_top_left_failsafe_guard() -> None:
    """REQ-CUA-BG-02: Verify (0, 0) fail-safe abort guard in dispatch_background_window_action."""
    with pytest.raises(ComputerUseSafetyAbort):
        dispatch_background_window_action(1001, "click", norm_x=0, norm_y=0, dry_run=True)

    with pytest.raises(ComputerUseSafetyAbort):
        dispatch_background_window_action(
            1001,
            "drag",
            norm_x=250,
            norm_y=250,
            end_norm_x=0,
            end_norm_y=0,
            dry_run=True,
        )


def test_req_cua_bg_02_postmessage_background_dispatch_dry_run() -> None:
    """REQ-CUA-BG-02: Verify focusless PostMessageW dispatch for click, drag, scroll, and type_text."""
    for act in ("click", "double_click", "right_click", "move", "drag", "scroll", "type_text", "wm_settext"):
        res = dispatch_background_window_action(
            12345,
            act,
            norm_x=400,
            norm_y=600,
            end_norm_x=700,
            end_norm_y=800,
            text="Background Test",
            dry_run=True,
        )
        assert res["dispatched"] is True
        assert res["method"] == "post_message_background"
        assert res["action_type"] == act


def test_req_cua_bg_03_ghost_desktop_session_lifecycle() -> None:
    """REQ-CUA-BG-03: Verify GhostDesktopSession creation, enumeration, and clean teardown."""
    ghost = GhostDesktopSession("AGY_GhostTestDesktop")
    try:
        wins = ghost.enumerate_windows()
        assert isinstance(wins, list)
        res = ghost.dispatch_action(1001, "click", norm_x=500, norm_y=500, dry_run=True)
        assert res["dispatched"] is True
    finally:
        ghost.close()


def test_req_cua_bg_01_02_mcp_background_tools() -> None:
    """REQ-CUA-BG-01 / REQ-CUA-BG-02: Verify MCP cu_capture_som and cu_click with background=True."""
    cap_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 91,
            "method": "tools/call",
            "params": {
                "name": "cu_capture_som",
                "arguments": {
                    "background": True,
                    "hwnd": 0,
                    "width": 320,
                    "height": 200,
                    "synthetic_seed": 77,
                },
            },
        }
    )
    cap_data = cap_resp["result"]["structuredContent"]
    assert cap_data["ok"] is True
    assert cap_data["width"] == 320
    assert cap_data["height"] == 200

    click_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 92,
            "method": "tools/call",
            "params": {
                "name": "cu_click",
                "arguments": {
                    "background": True,
                    "hwnd": 1001,
                    "action_type": "click",
                    "norm_x": 500,
                    "norm_y": 500,
                    "dry_run": True,
                },
            },
        }
    )
    click_data = click_resp["result"]["structuredContent"]
    assert click_data["dispatched"] is True
    assert click_data["method"] == "post_message_background"
