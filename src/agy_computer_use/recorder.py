"""Antigravity Deterministic GUI Trajectory Recorder & Replay Engine (REQ-CUA-201).

Records normalized [0..1000] GUI actions, UIA selector bindings, before/after perceptual
dHash64 signatures, and RFC 6962 binary Merkle inclusion receipts. Provides self-healing
replay execution with automatic UIA element fallback when target window geometry shifts.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from agy_computer_use.safety_oracle import (
    _build_merkle_levels_and_proofs,
    compute_frame_dhash64,
)
from agy_computer_use.som import denormalize_from_grid_1000


def _compute_rfc6962_merkle_root(leaf_bytes_list: list[bytes]) -> str:
    root_hex, _, _ = _build_merkle_levels_and_proofs(leaf_bytes_list)
    return root_hex



class TrajectoryRecorder:
    """Records normalized GUI actions and RFC 6962 Merkle receipts (REQ-CUA-201)."""

    def __init__(self, session_id: str, metadata: dict[str, Any] | None = None) -> None:
        self.session_id = str(session_id)
        self.metadata = copy.deepcopy(metadata) if metadata else {}
        self.steps: list[dict[str, Any]] = []
        self.merkle_leaves: list[str] = []

    def record_step(
        self,
        action: dict[str, Any],
        before_rgb: bytes,
        after_rgb: bytes,
        uia_elements: list[dict[str, Any]],
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> dict[str, Any]:
        """Record a single GUI action with perceptual dHash and RFC 6962 receipt (REQ-CUA-201)."""
        act = copy.deepcopy(action)
        norm_x = act.get("norm_x")
        norm_y = act.get("norm_y")

        if norm_x is not None and (int(norm_x) < 0 or int(norm_x) > 1000):
            raise ValueError(f"norm_x must be in [0, 1000], got {norm_x}")
        if norm_y is not None and (int(norm_y) < 0 or int(norm_y) > 1000):
            raise ValueError(f"norm_y must be in [0, 1000], got {norm_y}")

        dhash_before = (
            compute_frame_dhash64(before_rgb, screen_width, screen_height)
            if before_rgb and len(before_rgb) == screen_width * screen_height * 3
            else 0
        )
        dhash_after = (
            compute_frame_dhash64(after_rgb, screen_width, screen_height)
            if after_rgb and len(after_rgb) == screen_width * screen_height * 3
            else 0
        )

        # Match deepest UIA element containing normalized action coordinate
        matched_element: dict[str, Any] | None = None
        if norm_x is not None and norm_y is not None and uia_elements:
            px_x, px_y = denormalize_from_grid_1000(norm_x, norm_y, screen_width, screen_height)
            candidates: list[dict[str, Any]] = []
            for el in uia_elements:
                bbox = el.get("bbox_px")
                if bbox and len(bbox) == 4:
                    left, top, right, bottom = bbox
                    if left <= px_x <= right and top <= px_y <= bottom:
                        candidates.append(el)
            if candidates:
                candidates.sort(key=lambda e: (e["bbox_px"][2] - e["bbox_px"][0]) * (e["bbox_px"][3] - e["bbox_px"][1]))
                matched_element = copy.deepcopy(candidates[0])

        step_idx = len(self.steps)

        leaf_obj = {
            "step_index": step_idx,
            "action": act,
            "dhash_before": dhash_before,
            "dhash_after": dhash_after,
            "matched_element": matched_element,
        }
        leaf_raw = json.dumps(leaf_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        leaf_hash = hashlib.sha256(b"\x00" + leaf_raw).hexdigest()
        self.merkle_leaves.append(leaf_hash)

        record = {
            "step_index": step_idx,
            "action": act,
            "dhash_before": dhash_before,
            "dhash_after": dhash_after,
            "matched_element": matched_element,
            "merkle_leaf_hash": leaf_hash,
        }
        self.steps.append(record)
        return record

    def export_trajectory(self) -> dict[str, Any]:
        """Export completed trajectory with Merkle root certification (REQ-CUA-201)."""
        if not self.merkle_leaves:
            merkle_root = hashlib.sha256(b"").hexdigest()
        else:
            leaf_bytes = [bytes.fromhex(h) for h in self.merkle_leaves]
            merkle_root = _compute_rfc6962_merkle_root(leaf_bytes)

        return {
            "version": "2.0.0",
            "session_id": self.session_id,
            "metadata": copy.deepcopy(self.metadata),
            "step_count": len(self.steps),
            "steps": copy.deepcopy(self.steps),
            "merkle_root": merkle_root,
            "merkle_leaves": list(self.merkle_leaves),
        }


def replay_recorded_trajectory(
    trajectory: dict[str, Any],
    session_manager: Any = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Replay recorded trajectory with cryptographic verification and self-healing (REQ-CUA-201)."""
    steps = trajectory.get("steps") or []
    expected_root = trajectory.get("merkle_root")

    computed_leaves: list[bytes] = []
    for s in steps:
        leaf_obj = {
            "step_index": s["step_index"],
            "action": s["action"],
            "dhash_before": s["dhash_before"],
            "dhash_after": s["dhash_after"],
            "matched_element": s.get("matched_element"),
        }
        leaf_raw = json.dumps(leaf_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        leaf_hash = hashlib.sha256(b"\x00" + leaf_raw).digest()
        computed_leaves.append(leaf_hash)

    if not computed_leaves:
        recalculated_root = hashlib.sha256(b"").hexdigest()
    else:
        recalculated_root = _compute_rfc6962_merkle_root(computed_leaves)

    if expected_root and recalculated_root != expected_root:
        return {
            "status": "FAILED",
            "ok": False,
            "merkle_verified": False,
            "error": "Trajectory integrity verification failed: Merkle root mismatch",
            "executed_steps": 0,
            "healed_steps": 0,
        }

    if not steps:
        return {
            "status": "SUCCESS",
            "ok": True,
            "merkle_verified": True,
            "executed_steps": 0,
            "healed_steps": 0,
            "steps": [],
        }

    executed_steps = 0
    healed_steps = 0
    executed_log: list[dict[str, Any]] = []

    for step in steps:
        act = copy.deepcopy(step["action"])
        matched = step.get("matched_element")
        healed = False

        if session_manager is not None and matched is not None:
            live_elements: list[dict[str, Any]] = []
            if hasattr(session_manager, "get_current_uia_elements"):
                live_elements = session_manager.get_current_uia_elements()
            elif hasattr(session_manager, "extract_uia_elements"):
                live_elements = session_manager.extract_uia_elements()
            elif hasattr(session_manager, "get_window_state"):
                hwnd = act.get("hwnd", 0)
                st = session_manager.get_window_state(hwnd=hwnd, include_screenshot=False)
                live_elements = st.get("elements", [])

            live_match: dict[str, Any] | None = None
            for el in live_elements:
                if matched.get("title") and el.get("title") == matched.get("title") and el.get("control_type") == matched.get("control_type"):
                    live_match = el
                    break
                if matched.get("element_id") and el.get("element_id") == matched.get("element_id"):
                    live_match = el
                    break

            if live_match and "bbox_px" in live_match:
                orig_bbox = matched.get("bbox_px")
                curr_bbox = live_match.get("bbox_px")
                if orig_bbox != curr_bbox:
                    cl, ct, cr, cb = curr_bbox
                    cx = (cl + cr) // 2
                    cy = (ct + cb) // 2
                    screen_w = getattr(session_manager, "screen_width", 1920) or 1920
                    screen_h = getattr(session_manager, "screen_height", 1080) or 1080
                    if screen_w <= 0:
                        screen_w = 1000
                    if screen_h <= 0:
                        screen_h = 1000
                    act["norm_x"] = max(0, min(1000, int(round((float(cx) / float(screen_w)) * 1000.0))))
                    act["norm_y"] = max(0, min(1000, int(round((float(cy) / float(screen_h)) * 1000.0))))
                    healed = True
                    healed_steps += 1

        if not dry_run:
            from agy_computer_use.actions import dispatch_gui_action
            dispatch_gui_action(**act)

        executed_steps += 1
        executed_log.append({"step_index": step["step_index"], "action": act, "healed": healed})

    return {
        "status": "SUCCESS",
        "ok": True,
        "merkle_verified": True,
        "executed_steps": executed_steps,
        "healed_steps": healed_steps,
        "steps": executed_log,
    }
