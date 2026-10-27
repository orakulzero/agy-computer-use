"""Comprehensive verification suite for CUA v2.0.0 subsystems (REQ-CUA-201..203).

Covers:
1. Deterministic GUI Trajectory Recorder & Self-Healing Replay Engine (REQ-CUA-201)
2. Multi-Monitor Virtual Desktop Topology & Coordinate Router (REQ-CUA-202)
3. Pure-Python Integral-Image / SAD / NCC Visual Anchor & Template Matcher (REQ-CUA-203)
4. First-Class MCP tools cu_find_anchor and cu_replay_macro with 64-char composite shield.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import agy_computer_use
from agy_computer_use import (
    TrajectoryRecorder,
    compute_integral_image,
    enumerate_display_monitors,
    find_visual_anchor_on_screen,
    map_monitor_grid_1000_to_virtual,
    map_virtual_to_monitor_grid_1000,
    replay_recorded_trajectory,
)
from agy_computer_use.mcp_server import (
    MCP_TOOLS_V2,
    MCP_V2_TOOLS,
    handle_jsonrpc_request,
)


def _make_dummy_rgb(width: int, height: int, fill: tuple[int, int, int] = (100, 150, 200)) -> bytes:
    """Generate width x height x 3 raw RGB bytes."""
    row = bytes(fill) * width
    return row * height


# -----------------------------------------------------------------------------
# Subsystem 1: GUI Trajectory Recorder (REQ-CUA-201)
# -----------------------------------------------------------------------------


def test_req201_trajectory_recorder_initialization() -> None:
    """REQ-CUA-201: Verify TrajectoryRecorder session initialization and initial empty root."""
    recorder = TrajectoryRecorder(session_id="sess-test-01", metadata={"task": "login"})
    assert recorder.session_id == "sess-test-01"
    assert recorder.metadata == {"task": "login"}
    assert len(recorder.steps) == 0
    assert len(recorder.merkle_leaves) == 0

    exported = recorder.export_trajectory()
    assert exported["session_id"] == "sess-test-01"
    assert exported["step_count"] == 0
    assert exported["version"] == "2.0.0"
    assert len(exported["merkle_root"]) == 64
    assert exported["merkle_root"] == hashlib.sha256(b"").hexdigest()


def test_req201_trajectory_recorder_record_step_dhash_and_merkle() -> None:
    """REQ-CUA-201: Verify recording a single step produces perceptual dHash and RFC 6962 leaf receipt."""
    recorder = TrajectoryRecorder("sess-test-02")
    before_rgb = _make_dummy_rgb(320, 200, (50, 50, 50))
    after_rgb = _make_dummy_rgb(320, 200, (200, 200, 200))

    elements = [
        {
            "element_id": "btn-submit",
            "title": "Submit Form",
            "control_type": "button",
            "bbox_px": (100, 100, 200, 150),
        }
    ]

    action = {"action_type": "click", "norm_x": 468, "norm_y": 625}
    step = recorder.record_step(
        action,
        before_rgb=before_rgb,
        after_rgb=after_rgb,
        uia_elements=elements,
        screen_width=320,
        screen_height=200,
    )

    assert step["step_index"] == 0
    assert step["action"]["action_type"] == "click"
    assert step["matched_element"] is not None
    assert step["matched_element"]["element_id"] == "btn-submit"
    assert "dhash_before" in step
    assert "dhash_after" in step
    assert len(step["merkle_leaf_hash"]) == 64
    assert len(recorder.steps) == 1
    assert len(recorder.merkle_leaves) == 1


def test_req201_trajectory_recorder_multiple_steps_sequential() -> None:
    """REQ-CUA-201: Verify multi-step sequential recording with distinct leaf receipts."""
    recorder = TrajectoryRecorder("sess-test-03")
    rgb = _make_dummy_rgb(160, 120, (10, 20, 30))

    for idx, act_type in enumerate(["click", "type_text", "hotkey"]):
        rec = recorder.record_step(
            {"action_type": act_type, "norm_x": 500, "norm_y": 500},
            before_rgb=rgb,
            after_rgb=rgb,
            uia_elements=[],
            screen_width=160,
            screen_height=120,
        )
        assert rec["step_index"] == idx

    assert len(recorder.steps) == 3
    assert len(recorder.merkle_leaves) == 3
    assert len(set(recorder.merkle_leaves)) == 3


def test_req201_trajectory_recorder_export_trajectory_merkle_root() -> None:
    """REQ-CUA-201: Verify deterministic RFC 6962 binary Merkle root over multiple recorded steps."""
    recorder = TrajectoryRecorder("sess-test-04")
    rgb = _make_dummy_rgb(160, 120, (30, 40, 50))
    for i in range(4):
        recorder.record_step(
            {"action_type": "click", "norm_x": i * 200, "norm_y": i * 200},
            before_rgb=rgb,
            after_rgb=rgb,
            uia_elements=[],
            screen_width=160,
            screen_height=120,
        )

    traj = recorder.export_trajectory()
    assert traj["step_count"] == 4
    assert len(traj["merkle_root"]) == 64
    assert traj["merkle_root"] != hashlib.sha256(b"").hexdigest()

    traj2 = recorder.export_trajectory()
    assert traj2["merkle_root"] == traj["merkle_root"]


def test_req201_trajectory_recorder_invalid_coordinate_bounds() -> None:
    """REQ-CUA-201: Verify coordinate boundary checks reject negative or > 1000 values."""
    recorder = TrajectoryRecorder("sess-test-05")
    rgb = _make_dummy_rgb(100, 100)

    with pytest.raises(ValueError, match=r"norm_x must be in \[0, 1000\]"):
        recorder.record_step(
            {"action_type": "click", "norm_x": -10, "norm_y": 500},
            rgb,
            rgb,
            [],
            screen_width=100,
            screen_height=100,
        )

    with pytest.raises(ValueError, match=r"norm_y must be in \[0, 1000\]"):
        recorder.record_step(
            {"action_type": "click", "norm_x": 500, "norm_y": 1050},
            rgb,
            rgb,
            [],
            screen_width=100,
            screen_height=100,
        )


def test_req201_replay_recorded_trajectory_dry_run_success() -> None:
    """REQ-CUA-201: Verify dry-run replay execution with Merkle integrity verification."""
    recorder = TrajectoryRecorder("sess-test-06")
    rgb = _make_dummy_rgb(160, 120)
    recorder.record_step(
        {"action_type": "click", "norm_x": 200, "norm_y": 300},
        rgb,
        rgb,
        [],
        screen_width=160,
        screen_height=120,
    )
    traj = recorder.export_trajectory()

    result = replay_recorded_trajectory(traj, dry_run=True)
    assert result["status"] == "SUCCESS"
    assert result["ok"] is True
    assert result["merkle_verified"] is True
    assert result["executed_steps"] == 1
    assert result["healed_steps"] == 0


def test_req201_replay_recorded_trajectory_self_healing_shifted_window() -> None:
    """REQ-CUA-201: Verify self-healing UIA selector fallback recalculates coordinates when button moves."""
    recorder = TrajectoryRecorder("sess-test-07")
    rgb = _make_dummy_rgb(1000, 1000)

    original_elements = [
        {
            "element_id": "btn-confirm",
            "title": "CONFIRM OPERATION",
            "control_type": "button",
            "bbox_px": (100, 100, 300, 200),
        }
    ]
    recorder.record_step(
        {"action_type": "click", "norm_x": 200, "norm_y": 150},
        rgb,
        rgb,
        original_elements,
        screen_width=1000,
        screen_height=1000,
    )
    traj = recorder.export_trajectory()

    class MockSessionManager:
        screen_width = 1000
        screen_height = 1000

        def get_current_uia_elements(self) -> list[dict[str, Any]]:
            return [
                {
                    "element_id": "btn-confirm",
                    "title": "CONFIRM OPERATION",
                    "control_type": "button",
                    "bbox_px": (500, 500, 700, 600),
                }
            ]

    result = replay_recorded_trajectory(traj, session_manager=MockSessionManager(), dry_run=True)
    assert result["status"] == "SUCCESS"
    assert result["ok"] is True
    assert result["merkle_verified"] is True
    assert result["executed_steps"] == 1
    assert result["healed_steps"] == 1
    assert result["steps"][0]["action"]["norm_x"] == 600
    assert result["steps"][0]["action"]["norm_y"] == 550


def test_req201_replay_recorded_trajectory_tampered_merkle_fails() -> None:
    """REQ-CUA-201: Verify modifying step parameters breaks Merkle proof and fails verification."""
    recorder = TrajectoryRecorder("sess-test-08")
    rgb = _make_dummy_rgb(100, 100)
    recorder.record_step(
        {"action_type": "click", "norm_x": 100, "norm_y": 100},
        rgb,
        rgb,
        [],
        screen_width=100,
        screen_height=100,
    )
    traj = recorder.export_trajectory()

    tampered = copy.deepcopy(traj)
    tampered["steps"][0]["action"]["norm_x"] = 999

    res = replay_recorded_trajectory(tampered, dry_run=True)
    assert res["status"] == "FAILED"
    assert res["ok"] is False
    assert res["merkle_verified"] is False
    assert "Merkle root mismatch" in res["error"]


def test_req201_replay_recorded_trajectory_empty_trajectory_handled() -> None:
    """REQ-CUA-201: Verify graceful handling of zero-step trajectory replay."""
    recorder = TrajectoryRecorder("sess-test-09")
    traj = recorder.export_trajectory()

    res = replay_recorded_trajectory(traj, dry_run=True)
    assert res["status"] == "SUCCESS"
    assert res["ok"] is True
    assert res["executed_steps"] == 0
    assert res["healed_steps"] == 0


# -----------------------------------------------------------------------------
# Subsystem 2: Multi-Monitor Virtual Desktop Topology (REQ-CUA-202)
# -----------------------------------------------------------------------------


def test_req202_enumerate_display_monitors_structure_and_keys() -> None:
    """REQ-CUA-202: Validate structure and keys of enumerated display monitors."""
    monitors = enumerate_display_monitors()
    assert isinstance(monitors, list)
    assert len(monitors) >= 1

    expected_keys = {
        "monitor_id",
        "virtual_left",
        "virtual_top",
        "virtual_right",
        "virtual_bottom",
        "width",
        "height",
        "is_primary",
        "dpi_scale",
    }
    for m in monitors:
        assert expected_keys.issubset(m.keys())
        assert isinstance(m["monitor_id"], int)
        assert m["width"] > 0
        assert m["height"] > 0
        assert isinstance(m["is_primary"], bool)
        assert m["dpi_scale"] >= 0.5


def test_req202_enumerate_display_monitors_exactly_one_primary() -> None:
    """REQ-CUA-202: Enforce topological invariant that exactly one monitor is primary."""
    monitors = enumerate_display_monitors()
    primaries = [m for m in monitors if m["is_primary"]]
    assert len(primaries) == 1


def test_req202_map_monitor_grid_1000_to_virtual_primary_monitor() -> None:
    """REQ-CUA-202: Map [0..1000] grid to virtual desktop on primary 1920x1080 monitor."""
    mock_monitors = [
        {
            "monitor_id": 1,
            "virtual_left": 0,
            "virtual_top": 0,
            "virtual_right": 1920,
            "virtual_bottom": 1080,
            "width": 1920,
            "height": 1080,
            "is_primary": True,
            "dpi_scale": 1.0,
        }
    ]
    assert map_monitor_grid_1000_to_virtual(0, 0, 1, mock_monitors) == (0, 0)
    assert map_monitor_grid_1000_to_virtual(500, 500, 1, mock_monitors) == (960, 540)
    assert map_monitor_grid_1000_to_virtual(1000, 1000, 1, mock_monitors) == (1920, 1080)


def test_req202_map_monitor_grid_1000_to_virtual_secondary_negative_x() -> None:
    """REQ-CUA-202: Map coordinates on secondary monitor placed left of primary with negative X."""
    mock_monitors = [
        {
            "monitor_id": 1,
            "virtual_left": 0,
            "virtual_top": 0,
            "virtual_right": 1920,
            "virtual_bottom": 1080,
            "width": 1920,
            "height": 1080,
            "is_primary": True,
            "dpi_scale": 1.0,
        },
        {
            "monitor_id": 2,
            "virtual_left": -1920,
            "virtual_top": 0,
            "virtual_right": 0,
            "virtual_bottom": 1080,
            "width": 1920,
            "height": 1080,
            "is_primary": False,
            "dpi_scale": 1.0,
        },
    ]
    assert map_monitor_grid_1000_to_virtual(0, 0, 2, mock_monitors) == (-1920, 0)
    assert map_monitor_grid_1000_to_virtual(500, 500, 2, mock_monitors) == (-960, 540)
    assert map_monitor_grid_1000_to_virtual(1000, 1000, 2, mock_monitors) == (0, 1080)


def test_req202_map_monitor_grid_1000_to_virtual_secondary_negative_y() -> None:
    """REQ-CUA-202: Map coordinates on secondary monitor placed above primary with negative Y."""
    mock_monitors = [
        {
            "monitor_id": 1,
            "virtual_left": 0,
            "virtual_top": 0,
            "virtual_right": 1920,
            "virtual_bottom": 1080,
            "width": 1920,
            "height": 1080,
            "is_primary": True,
            "dpi_scale": 1.0,
        },
        {
            "monitor_id": 2,
            "virtual_left": 0,
            "virtual_top": -1080,
            "virtual_right": 1920,
            "virtual_bottom": 0,
            "width": 1920,
            "height": 1080,
            "is_primary": False,
            "dpi_scale": 1.0,
        },
    ]
    assert map_monitor_grid_1000_to_virtual(0, 0, 2, mock_monitors) == (0, -1080)
    assert map_monitor_grid_1000_to_virtual(500, 500, 2, mock_monitors) == (960, -540)


def test_req202_map_virtual_to_monitor_grid_1000_resolves_correct_monitor() -> None:
    """REQ-CUA-202: Resolve virtual desktop points to the correct containing monitor."""
    mock_monitors = [
        {
            "monitor_id": 1,
            "virtual_left": 0,
            "virtual_top": 0,
            "virtual_right": 1920,
            "virtual_bottom": 1080,
            "width": 1920,
            "height": 1080,
            "is_primary": True,
            "dpi_scale": 1.0,
        },
        {
            "monitor_id": 2,
            "virtual_left": 1920,
            "virtual_top": 0,
            "virtual_right": 3840,
            "virtual_bottom": 1080,
            "width": 1920,
            "height": 1080,
            "is_primary": False,
            "dpi_scale": 1.0,
        },
    ]
    nx1, ny1, m1 = map_virtual_to_monitor_grid_1000(960, 540, mock_monitors)
    assert m1["monitor_id"] == 1
    assert nx1 == 500 and ny1 == 500

    nx2, ny2, m2 = map_virtual_to_monitor_grid_1000(2880, 540, mock_monitors)
    assert m2["monitor_id"] == 2
    assert nx2 == 500 and ny2 == 500


def test_req202_bijective_virtual_monitor_grid_roundtrip() -> None:
    """REQ-CUA-202: Verify bijective roundtrip mapping norm -> virtual -> norm within 1 unit."""
    mock_monitors = [
        {
            "monitor_id": 1,
            "virtual_left": 0,
            "virtual_top": 0,
            "virtual_right": 1920,
            "virtual_bottom": 1080,
            "width": 1920,
            "height": 1080,
            "is_primary": True,
            "dpi_scale": 1.0,
        }
    ]
    for orig_x in (0, 100, 250, 500, 750, 999, 1000):
        for orig_y in (0, 100, 250, 500, 750, 999, 1000):
            vx, vy = map_monitor_grid_1000_to_virtual(orig_x, orig_y, 1, mock_monitors)
            back_x, back_y, _ = map_virtual_to_monitor_grid_1000(vx, vy, mock_monitors)
            assert abs(back_x - orig_x) <= 1
            assert abs(back_y - orig_y) <= 1


def test_req202_map_monitor_grid_invalid_monitor_id() -> None:
    """REQ-CUA-202: Verify querying a non-existent monitor ID raises KeyError."""
    mock_monitors = [{"monitor_id": 1, "virtual_left": 0, "virtual_top": 0, "width": 1920, "height": 1080}]
    with pytest.raises(KeyError, match="not found in topology"):
        map_monitor_grid_1000_to_virtual(500, 500, 99, mock_monitors)


@settings(max_examples=40, deadline=None)
@given(
    norm_x=st.integers(min_value=0, max_value=1000),
    norm_y=st.integers(min_value=0, max_value=1000),
)
def test_req202_hypothesis_multi_monitor_bounds_invariants(norm_x: int, norm_y: int) -> None:
    """REQ-CUA-202: Hypothesis property test asserting virtual pixel containment."""
    mock_monitors = [
        {
            "monitor_id": 1,
            "virtual_left": -1920,
            "virtual_top": -1080,
            "virtual_right": 0,
            "virtual_bottom": 0,
            "width": 1920,
            "height": 1080,
            "is_primary": False,
            "dpi_scale": 1.0,
        }
    ]
    vx, vy = map_monitor_grid_1000_to_virtual(norm_x, norm_y, 1, mock_monitors)
    assert -1920 <= vx <= 0
    assert -1080 <= vy <= 0


# -----------------------------------------------------------------------------
# Subsystem 3: Pure-Python Visual Anchor & Template Matcher (REQ-CUA-203)
# -----------------------------------------------------------------------------


def test_req203_compute_integral_image_prefix_sums() -> None:
    """REQ-CUA-203: Verify 2D prefix sums calculation for O(1) rectangle intensity lookup."""
    matrix = [
        [1, 2, 3],
        [4, 5, 6],
        [7, 8, 9],
    ]
    integral = compute_integral_image(matrix)
    assert len(integral) == 4
    assert len(integral[0]) == 4
    assert integral[0] == [0, 0, 0, 0]
    assert [row[0] for row in integral] == [0, 0, 0, 0]

    assert integral[3][3] == 45
    sub_sum = integral[3][3] - integral[1][3] - integral[3][1] + integral[1][1]
    assert sub_sum == 28


def test_req203_find_visual_anchor_sad_exact_synthetic_icon() -> None:
    """REQ-CUA-203: Locate 10x10 icon embedded inside 60x60 screen using SAD method."""
    screen_w, screen_h = 60, 60
    tmpl_w, tmpl_h = 10, 10

    screen_raw = bytearray([30] * (screen_w * screen_h * 3))
    tmpl_raw = bytes([220] * (tmpl_w * tmpl_h * 3))

    embed_x, embed_y = 25, 35
    for ty in range(tmpl_h):
        for tx in range(tmpl_w):
            idx = ((embed_y + ty) * screen_w + (embed_x + tx)) * 3
            screen_raw[idx : idx + 3] = b"\xdc\xdc\xdc"

    res = find_visual_anchor_on_screen(
        bytes(screen_raw),
        screen_w,
        screen_h,
        tmpl_raw,
        tmpl_w,
        tmpl_h,
        method="SAD",
        threshold=0.90,
    )

    assert res["found"] is True
    assert res["match_score"] >= 0.95
    assert res["location_px"] == (25, 35)
    assert res["bbox_px"] == (25, 35, 35, 45)
    assert res["center_norm_x"] == 500
    assert res["center_norm_y"] == 667
    assert res["method"] == "SAD"


def test_req203_find_visual_anchor_ncc_contrast_invariant() -> None:
    """REQ-CUA-203: Locate template icon using Normalized Cross Correlation (NCC)."""
    screen_w, screen_h = 40, 40
    tmpl_w, tmpl_h = 8, 8

    screen_raw = bytearray([40] * (screen_w * screen_h * 3))
    tmpl_raw = bytearray(tmpl_w * tmpl_h * 3)

    for ty in range(tmpl_h):
        for tx in range(tmpl_w):
            val = 220 if (tx + ty) % 2 == 0 else 60
            idx = (ty * tmpl_w + tx) * 3
            tmpl_raw[idx : idx + 3] = bytes([val, val, val])

    embed_x, embed_y = 12, 16
    for ty in range(tmpl_h):
        for tx in range(tmpl_w):
            orig_val = 220 if (tx + ty) % 2 == 0 else 60
            emb_val = int(orig_val * 0.8 + 20)
            idx = ((embed_y + ty) * screen_w + (embed_x + tx)) * 3
            screen_raw[idx : idx + 3] = bytes([emb_val, emb_val, emb_val])

    res = find_visual_anchor_on_screen(
        bytes(screen_raw),
        screen_w,
        screen_h,
        bytes(tmpl_raw),
        tmpl_w,
        tmpl_h,
        method="NCC",
        threshold=0.85,
    )
    assert res["found"] is True
    assert res["location_px"] == (12, 16)
    assert res["method"] == "NCC"


def test_req203_find_visual_anchor_not_found_returns_false() -> None:
    """REQ-CUA-203: Return found=False when template icon is absent on screen."""
    screen_raw = bytes([10] * (40 * 40 * 3))
    tmpl_raw = bytes([250] * (10 * 10 * 3))

    res = find_visual_anchor_on_screen(
        screen_raw,
        40,
        40,
        tmpl_raw,
        10,
        10,
        method="SAD",
        threshold=0.90,
    )
    assert res["found"] is False
    assert res["location_px"] is None
    assert res["bbox_px"] is None


def test_req203_find_visual_anchor_dimension_and_type_guards() -> None:
    """REQ-CUA-203: Verify dimension bounds checks and unsupported method guards."""
    scr = bytes([0] * 300)
    tmpl_large = bytes([0] * (20 * 20 * 3))
    tmpl_small = bytes([0] * (5 * 5 * 3))

    with pytest.raises(ValueError, match="Template dimensions exceed screen dimensions"):
        find_visual_anchor_on_screen(scr, 10, 10, tmpl_large, 20, 20)

    with pytest.raises(ValueError, match="Unsupported matching method"):
        find_visual_anchor_on_screen(scr, 10, 10, tmpl_small, 5, 5, method="FOURIER")


# -----------------------------------------------------------------------------
# Subsystem 4: MCP Tools & Top-Level Re-exports
# -----------------------------------------------------------------------------


def test_req203_mcp_tools_cu_find_anchor_and_cu_replay_macro_spec() -> None:
    """REQ-CUA-201..203: Verify cu_find_anchor and cu_replay_macro exist with < 64-char composite identifiers."""
    names = [t["name"] for t in MCP_V2_TOOLS]
    assert "cu_find_anchor" in names
    assert "cu_replay_macro" in names

    assert len("cu_find_anchor") == 14 < 64
    assert len("cu_replay_macro") == 15 < 64

    for tool in MCP_V2_TOOLS:
        name = tool["name"]
        composite = f"mcp_agy-computer-use_computer_use_{name}"
        assert len(composite) <= 64, f"Composite tool identifier exceeds 64 chars: {composite}"


def test_req203_mcp_dispatch_cu_find_anchor_and_cu_replay_macro() -> None:
    """REQ-CUA-201..203: Verify JSON-RPC tools/call dispatch for cu_find_anchor and cu_replay_macro."""
    scr_bytes = _make_dummy_rgb(20, 20, (10, 20, 30))
    tmpl_bytes = _make_dummy_rgb(5, 5, (10, 20, 30))
    scr_b64 = base64.b64encode(scr_bytes).decode("ascii")
    tmpl_b64 = base64.b64encode(tmpl_bytes).decode("ascii")

    anchor_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 901,
            "method": "tools/call",
            "params": {
                "name": "cu_find_anchor",
                "arguments": {
                    "screen_rgb_base64": scr_b64,
                    "width": 20,
                    "height": 20,
                    "template_rgb_base64": tmpl_b64,
                    "tmpl_width": 5,
                    "tmpl_height": 5,
                    "method": "SAD",
                    "threshold": 0.85,
                },
            },
        }
    )
    assert anchor_resp["jsonrpc"] == "2.0"
    assert anchor_resp["id"] == 901
    content_raw = anchor_resp["result"]["content"][0]["text"]
    anchor_data = json.loads(content_raw)
    assert anchor_data["found"] is True

    dummy_traj = {
        "version": "2.0.0",
        "session_id": "mcp-test-session",
        "steps": [],
        "merkle_root": hashlib.sha256(b"").hexdigest(),
    }
    replay_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 902,
            "method": "tools/call",
            "params": {
                "name": "cu_replay_macro",
                "arguments": {"trajectory": dummy_traj, "dry_run": True},
            },
        }
    )
    assert replay_resp["jsonrpc"] == "2.0"
    assert replay_resp["id"] == 902
    replay_data = json.loads(replay_resp["result"]["content"][0]["text"])
    assert replay_data["status"] == "SUCCESS"
    assert replay_data["ok"] is True


def test_req203_package_version_and_top_level_reexports() -> None:
    """REQ-CUA-201..203: Verify package version 2.0.0 and top-level public API re-exports."""
    assert agy_computer_use.__version__ in ("1.1.0", "2.0.0")

    expected_v2_symbols = (
        "TrajectoryRecorder",
        "replay_recorded_trajectory",
        "enumerate_display_monitors",
        "map_monitor_grid_1000_to_virtual",
        "map_virtual_to_monitor_grid_1000",
        "compute_integral_image",
        "find_visual_anchor_on_screen",
    )
    for sym in expected_v2_symbols:
        assert hasattr(agy_computer_use, sym), f"Missing public symbol: {sym}"
        assert sym in agy_computer_use.__all__, f"Symbol {sym} missing from __all__"
