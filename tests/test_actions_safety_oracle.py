"""ISO 9001:2015 Agile V Verification Suite for GUI Action Dispatch & Visual Safety Oracle.

Covers REQ-CU-003 (Win32 SendInput Synthesis, SoM Mark Dispatch, Fail-Safe Corner Abort)
and REQ-CU-004 (64-bit dHash Perceptual Delta, SafetyPolicy Guardrails, RFC 6962 Merkle Audit).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_dispatch_all_nine_action_types_in_dry_run() -> None:
    """REQ-CU-003: Verify all 9 supported GUI action types synthesize Win32 INPUT records."""
    from agy_computer_use.actions import dispatch_gui_action

    mouse_actions = ("click", "double_click", "right_click", "move", "drag")
    for act in mouse_actions:
        res = dispatch_gui_action(
            act,
            norm_x=500,
            norm_y=500,
            screen_width=1920,
            screen_height=1080,
            dry_run=True,
        )
        assert res["ok"] is True
        assert res["action_type"] == act
        assert res["dry_run"] is True
        assert res["resolved_px"] == (960, 540)
        assert res["resolved_1000"] == (500, 500)
        assert isinstance(res["win32_inputs"], list) and len(res["win32_inputs"]) >= 1
        assert isinstance(res["timestamp"], float) and res["timestamp"] > 0.0

    scroll_res = dispatch_gui_action(
        "scroll",
        norm_x=400,
        norm_y=600,
        scroll_delta=-120,
        screen_width=1920,
        screen_height=1080,
        dry_run=True,
    )
    assert scroll_res["ok"] is True
    assert scroll_res["action_type"] == "scroll"
    assert len(scroll_res["win32_inputs"]) >= 1

    type_res = dispatch_gui_action("type_text", text="AGY-2026", dry_run=True)
    assert type_res["ok"] is True
    assert type_res["action_type"] == "type_text"
    assert len(type_res["win32_inputs"]) >= len("AGY-2026")

    hotkey_res = dispatch_gui_action("hotkey", keys=["ctrl", "shift", "s"], dry_run=True)
    assert hotkey_res["ok"] is True
    assert hotkey_res["action_type"] == "hotkey"
    assert len(hotkey_res["win32_inputs"]) >= 2

    tap_res = dispatch_gui_action("key_tap", keys=["enter"], text="enter", dry_run=True)
    assert tap_res["ok"] is True
    assert tap_res["action_type"] == "key_tap"
    assert len(tap_res["win32_inputs"]) >= 2


def test_dispatch_unsupported_action_type_raises_value_error() -> None:
    """REQ-CU-003: Verify unsupported action_type raises ValueError."""
    from agy_computer_use.actions import dispatch_gui_action

    with pytest.raises(ValueError):
        dispatch_gui_action("invalid_gesture_xyz", norm_x=500, norm_y=500, dry_run=True)


def test_dispatch_som_mark_id_resolution() -> None:
    """REQ-CU-003: Verify mark_id resolves target coordinates from SoM marks_catalog."""
    from agy_computer_use.actions import dispatch_gui_action

    catalog = {
        1: {
            "mark_id": 1,
            "title": "OK Button",
            "class_name": "Button",
            "control_type": "button",
            "bbox_px": (400, 200, 560, 270),
            "center_px": (480, 235),
            "center_1000": (250, 218),
        }
    }
    res = dispatch_gui_action(
        "click",
        mark_id=1,
        marks_catalog=catalog,
        screen_width=1920,
        screen_height=1080,
        dry_run=True,
    )
    assert res["ok"] is True
    assert res["resolved_1000"] == (250, 218)
    assert res["resolved_px"] is not None
    assert len(res["win32_inputs"]) >= 2


def test_dispatch_missing_mark_id_raises_key_error() -> None:
    """REQ-CU-003: Verify unknown mark_id raises KeyError."""
    from agy_computer_use.actions import dispatch_gui_action

    catalog = {
        1: {
            "mark_id": 1,
            "title": "Cancel",
            "class_name": "Button",
            "control_type": "button",
            "bbox_px": (100, 100, 200, 150),
            "center_px": (150, 125),
            "center_1000": (150, 125),
        }
    }
    with pytest.raises(KeyError):
        dispatch_gui_action("click", mark_id=99, marks_catalog=catalog, dry_run=True)


def test_dispatch_fail_safe_corner_0_0_raises_safety_abort() -> None:
    """REQ-CU-003: Verify (0, 0) fail-safe corner triggers ComputerUseSafetyAbort."""
    from agy_computer_use.actions import ComputerUseSafetyAbort, dispatch_gui_action

    assert issubclass(ComputerUseSafetyAbort, RuntimeError)

    for mouse_act in ("click", "double_click", "right_click", "move", "drag"):
        with pytest.raises(ComputerUseSafetyAbort):
            dispatch_gui_action(
                mouse_act,
                norm_x=0,
                norm_y=0,
                dry_run=True,
                fail_safe_corner=True,
            )


def test_dispatch_fail_safe_corner_mark_at_origin_aborts() -> None:
    """REQ-CU-003: Verify SoM mark resolving to (0, 0) triggers ComputerUseSafetyAbort."""
    from agy_computer_use.actions import ComputerUseSafetyAbort, dispatch_gui_action

    origin_catalog = {
        1: {
            "mark_id": 1,
            "title": "Corner Trap",
            "class_name": "Static",
            "control_type": "control",
            "bbox_px": (0, 0, 0, 0),
            "center_px": (0, 0),
            "center_1000": (0, 0),
        }
    }
    with pytest.raises(ComputerUseSafetyAbort):
        dispatch_gui_action(
            "click",
            mark_id=1,
            marks_catalog=origin_catalog,
            dry_run=True,
            fail_safe_corner=True,
        )


def test_dispatch_fail_safe_disabled_permits_origin() -> None:
    """REQ-CU-003: Verify fail_safe_corner=False allows (0, 0) coordinate dispatch in dry_run."""
    from agy_computer_use.actions import dispatch_gui_action

    res = dispatch_gui_action(
        "move",
        norm_x=0,
        norm_y=0,
        dry_run=True,
        fail_safe_corner=False,
    )
    assert res["ok"] is True
    assert res["resolved_1000"] == (0, 0)
    assert res["resolved_px"] == (0, 0)


def test_compute_frame_dhash64_properties() -> None:
    """REQ-CU-004: Verify 64-bit horizontal gradient difference hash calculation."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import compute_frame_dhash64

    # Uniform solid color image has zero horizontal gradient -> dhash64 == 0
    flat_rgb = b"\x80\x80\x80" * (64 * 64)
    h_flat = compute_frame_dhash64(flat_rgb, 64, 64)
    assert isinstance(h_flat, int)
    assert h_flat == 0

    # Strictly increasing horizontal gradient across columns has all bits 1 or deterministic non-zero
    frame_1 = capture_screen_frame(width=160, height=120, synthetic_seed=11)
    frame_2 = capture_screen_frame(width=160, height=120, synthetic_seed=22)
    h1 = compute_frame_dhash64(frame_1["rgb_bytes"], 160, 120)
    h2 = compute_frame_dhash64(frame_2["rgb_bytes"], 160, 120)
    assert 0 <= h1 < (1 << 64)
    assert 0 <= h2 < (1 << 64)
    assert h1 != h2


def test_compute_visual_hamming_delta_epistemic_thresholds() -> None:
    """REQ-CU-004: Verify Hamming distance and [FACT] (>=2 bits) vs [NO_EFFECT] (<2 bits)."""
    from agy_computer_use.safety_oracle import compute_visual_hamming_delta

    # 0-bit difference -> [NO_EFFECT]
    d0 = compute_visual_hamming_delta(0xAAAAAAAAAAAAAAAA, 0xAAAAAAAAAAAAAAAA)
    assert d0["hamming_distance"] == 0
    assert d0["normalized_delta"] == 0.0
    assert d0["epistemic_status"] == "[NO_EFFECT]"
    assert d0["visual_change_detected"] is False

    # 1-bit difference -> [NO_EFFECT]
    d1 = compute_visual_hamming_delta(0b1000, 0b1001)
    assert d1["hamming_distance"] == 1
    assert d1["normalized_delta"] == 1.0 / 64.0
    assert d1["epistemic_status"] == "[NO_EFFECT]"
    assert d1["visual_change_detected"] is False

    # 2-bit difference -> [FACT]
    d2 = compute_visual_hamming_delta(0b1000, 0b1011)
    assert d2["hamming_distance"] == 2
    assert d2["normalized_delta"] == 2.0 / 64.0
    assert d2["epistemic_status"] == "[FACT]"
    assert d2["visual_change_detected"] is True

    # Full 64-bit inversion -> [FACT]
    d64 = compute_visual_hamming_delta(0, (1 << 64) - 1)
    assert d64["hamming_distance"] == 64
    assert d64["normalized_delta"] == 1.0
    assert d64["epistemic_status"] == "[FACT]"
    assert d64["visual_change_detected"] is True


def test_safety_policy_blocks_sensitive_window_titles() -> None:
    """REQ-CU-004: Verify SafetyPolicy blocks password managers, UAC, and SmartScreen."""
    from agy_computer_use.safety_oracle import SafetyPolicy

    policy = SafetyPolicy()
    blocked_titles = (
        "Bitwarden - Vault Unlocked",
        "1Password - Main Vault",
        "KeePassXC - Database.kdbx",
        "Windows Credential Manager",
        "User Account Control (UAC)",
        "Windows Defender SmartScreen",
    )
    for title in blocked_titles:
        verdict = policy.evaluate_window_target(title=title, class_name="StandardWindow")
        assert verdict["allowed"] is False, f"Expected title '{title}' to be blocked"
        assert isinstance(verdict["reason"], str) and len(verdict["reason"]) > 0


def test_safety_policy_blocks_forbidden_window_classes() -> None:
    """REQ-CU-004: Verify SafetyPolicy blocks Credential Dialog Xaml Host class."""
    from agy_computer_use.safety_oracle import SafetyPolicy

    policy = SafetyPolicy()
    verdict = policy.evaluate_window_target(
        title="Windows Security",
        class_name="Credential Dialog Xaml Host",
    )
    assert verdict["allowed"] is False
    assert verdict["reason"] is not None


def test_safety_policy_allowlist_enforcement() -> None:
    """REQ-CU-004: Verify SafetyPolicy enforces optional allowed_titles whitelist."""
    from agy_computer_use.safety_oracle import SafetyPolicy

    default_policy = SafetyPolicy()
    assert default_policy.evaluate_window_target("Untitled - Notepad", "Notepad")["allowed"] is True

    strict_policy = SafetyPolicy(allowed_titles=("notepad", "calculator"))
    assert strict_policy.evaluate_window_target("Untitled - Notepad", "Notepad")["allowed"] is True
    assert strict_policy.evaluate_window_target("Scientific Calculator", "CalcFrame")["allowed"] is True
    denied = strict_policy.evaluate_window_target("External Terminal", "ConsoleWindowClass")
    assert denied["allowed"] is False
    assert denied["reason"] is not None


def test_visual_action_oracle_records_fact_and_no_effect() -> None:
    """REQ-CU-004: Verify VisualActionOracle classifies [FACT] vs [NO_EFFECT] across frames."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import VisualActionOracle

    oracle = VisualActionOracle()
    frame_a = capture_screen_frame(width=160, height=120, synthetic_seed=10)
    frame_b = capture_screen_frame(width=160, height=120, synthetic_seed=20)

    receipt_fact = oracle.record_and_verify_action(
        action_payload={"action_type": "click", "norm_x": 500, "norm_y": 500},
        frame_before=frame_a,
        frame_after=frame_b,
        target_window={"title": "Test Application", "class_name": "AppWindow"},
    )
    assert receipt_fact["index"] == 0
    assert receipt_fact["epistemic_status"] == "[FACT]"
    assert receipt_fact["visual_change_detected"] is True
    assert receipt_fact["hamming_distance"] >= 2
    assert isinstance(receipt_fact["receipt_id"], str) and len(receipt_fact["receipt_id"]) > 0
    assert isinstance(receipt_fact["merkle_root"], str) and len(receipt_fact["merkle_root"]) == 64

    receipt_noop = oracle.record_and_verify_action(
        action_payload={"action_type": "move", "norm_x": 500, "norm_y": 500},
        frame_before=frame_b,
        frame_after=frame_b,
        target_window={"title": "Test Application", "class_name": "AppWindow"},
    )
    assert receipt_noop["index"] == 1
    assert receipt_noop["epistemic_status"] == "[NO_EFFECT]"
    assert receipt_noop["visual_change_detected"] is False
    assert receipt_noop["hamming_distance"] == 0


def test_visual_action_oracle_aborts_on_forbidden_window() -> None:
    """REQ-CU-004: Verify VisualActionOracle raises ComputerUseSafetyAbort on blocked window."""
    from agy_computer_use.actions import ComputerUseSafetyAbort
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import VisualActionOracle

    oracle = VisualActionOracle()
    frame = capture_screen_frame(width=128, height=96, synthetic_seed=1)

    with pytest.raises(ComputerUseSafetyAbort):
        oracle.record_and_verify_action(
            action_payload={"action_type": "click", "norm_x": 200, "norm_y": 200},
            frame_before=frame,
            frame_after=frame,
            target_window={"title": "Bitwarden Password Manager", "class_name": "Chrome_WidgetWin_1"},
        )

    summary = oracle.get_merkle_audit_summary()
    assert summary["leaf_count"] == 0


def test_visual_action_oracle_rfc6962_merkle_proof_verification() -> None:
    """REQ-CU-004: Verify RFC 6962 Merkle audit tree summary and inclusion proofs across multiple actions."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import VisualActionOracle

    oracle = VisualActionOracle()
    frames = [capture_screen_frame(width=120, height=90, synthetic_seed=s) for s in range(1, 7)]

    for i in range(5):
        oracle.record_and_verify_action(
            action_payload={"action_type": "click", "step": i, "norm_x": 100 * (i + 1), "norm_y": 300},
            frame_before=frames[i],
            frame_after=frames[i + 1],
            target_window={"title": "Editor", "class_name": "EditorWnd"},
        )

    summary = oracle.get_merkle_audit_summary()
    assert summary["leaf_count"] == 5
    assert isinstance(summary["root"], str) and len(summary["root"]) == 64
    assert isinstance(summary["levels"], list) and len(summary["levels"]) >= 2
    assert len(summary["receipts"]) == 5

    for receipt in summary["receipts"]:
        proof = receipt["merkle_proof"]
        assert isinstance(proof, list)
        assert VisualActionOracle.verify_action_receipt(
            receipt,
            proof,
            summary["root"],
        ) is True


def test_visual_action_oracle_merkle_tamper_rejection() -> None:
    """REQ-CU-004: Verify tampered receipt payload, proof, or root fails verification."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.safety_oracle import VisualActionOracle

    oracle = VisualActionOracle()
    f1 = capture_screen_frame(width=120, height=90, synthetic_seed=100)
    f2 = capture_screen_frame(width=120, height=90, synthetic_seed=200)
    f3 = capture_screen_frame(width=120, height=90, synthetic_seed=300)

    oracle.record_and_verify_action({"action_type": "click", "norm_x": 200, "norm_y": 200}, f1, f2)
    oracle.record_and_verify_action({"action_type": "click", "norm_x": 400, "norm_y": 400}, f2, f3)

    summary = oracle.get_merkle_audit_summary()
    root = summary["root"]
    valid_receipt = summary["receipts"][0]
    valid_proof = valid_receipt["merkle_proof"]

    assert VisualActionOracle.verify_action_receipt(valid_receipt, valid_proof, root) is True

    # Tamper with receipt hamming_distance
    tampered_receipt = copy.deepcopy(valid_receipt)
    tampered_receipt["hamming_distance"] = int(valid_receipt["hamming_distance"]) + 1
    assert VisualActionOracle.verify_action_receipt(tampered_receipt, valid_proof, root) is False

    # Tamper with expected Merkle root
    bad_root = ("0" if root[0] != "0" else "f") + root[1:]
    assert VisualActionOracle.verify_action_receipt(valid_receipt, valid_proof, bad_root) is False

    # Tamper with sibling hash in proof
    if valid_proof:
        side, sibling_hex = valid_proof[0]
        bad_sibling = ("0" if sibling_hex[0] != "0" else "f") + sibling_hex[1:]
        tampered_proof = [(side, bad_sibling)] + list(valid_proof[1:])
        assert VisualActionOracle.verify_action_receipt(valid_receipt, tampered_proof, root) is False


def test_visual_action_oracle_empty_summary() -> None:
    """REQ-CU-004: Verify empty VisualActionOracle returns clean summary state."""
    from agy_computer_use.safety_oracle import VisualActionOracle

    oracle = VisualActionOracle()
    summary = oracle.get_merkle_audit_summary()
    assert summary["leaf_count"] == 0
    assert summary["receipts"] == []
    assert isinstance(summary["root"], str)
