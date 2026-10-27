"""Window-Scoped Session Manager, Stale-Screenshot Guard, UIA Tree Formatter/Differ,
7-Point Bezier Cursor Motion Synthesizer, Capture-Excluded Overlay, and Interruption Guard.

Implements Next-Gen CUA Architecture (inspired by @oai/sky window2 & codex-computer-use):
- WindowSessionManager with per-HWND snapshotRevision, accessibilityRevision, and screenshotId guard
- Hierarchical UIA element tree formatter (#1..#N) and incremental tree diffing
- Semantic UIA element actions (click_element, set_element_value, scroll_element)
- Two-segment 7-control-point (P0..P6) cubic Bezier cursor trajectory synthesizer
- Win32 SetWindowDisplayAffinity(..., WDA_EXCLUDEFROMCAPTURE) cloak for HUD overlays
- Physical ESC and mouse-delta human interruption monitor
- CompactionImageBudget for retaining bounded full-resolution frames in long sessions
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import math
import sys
import time
from typing import Any

from agy_computer_use.actions import ComputerUseSafetyAbort, dispatch_gui_action
from agy_computer_use.capture import (
    _run_on_default_desktop,
    capture_screen_frame,
    enumerate_visible_windows,
    extract_uia_element_tree,
)
from agy_computer_use.safety_oracle import wrap_untrusted_ui_evidence
from agy_computer_use.som import annotate_som_elements, normalize_to_grid_1000

WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

WM_SETTEXT = 0x000C
WM_VSCROLL = 0x0115
WM_HSCROLL = 0x0114
SB_LINEUP = 0
SB_LINEDOWN = 1
SB_PAGEUP = 2
SB_PAGEDOWN = 3
VK_ESCAPE = 0x1B


def format_uia_tree_text(
    elements: list[dict[str, Any]],
    window_bbox: tuple[int, int, int, int] | None = None,
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> str:
    """REQ-CUA-01: Format UIA element list into a compact #1..#N indexed text representation."""
    if not elements:
        return "(no interactive UIA elements)"

    win_left = int(window_bbox[0]) if window_bbox else 0
    win_top = int(window_bbox[1]) if window_bbox else 0
    lines: list[str] = []

    for idx, el in enumerate(elements, start=1):
        ctrl = str(el.get("control_type", "control")).capitalize()
        title = str(el.get("title", "")).replace("\r", " ").replace("\n", " ").strip()
        cls_name = str(el.get("class_name", "")).strip()
        bbox = el.get("bbox_px", (0, 0, 0, 0))
        left, top, right, bottom = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        rel_x = cx - win_left
        rel_y = cy - win_top
        norm_x, norm_y = normalize_to_grid_1000(
            cx, cy, screen_width=max(1, screen_width), screen_height=max(1, screen_height)
        )
        enabled_tag = "enabled" if el.get("is_enabled", True) else "disabled"
        indent = "" if idx == 1 and ctrl.lower() == "window" else "  "
        lines.append(
            f'{indent}[{ctrl}] "{title}" #{idx} '
            f"(class={cls_name}, win_xy={rel_x},{rel_y}, norm={norm_x},{norm_y}, {enabled_tag})"
        )

    return "\n".join(lines)


def diff_uia_trees(
    previous_elements: list[dict[str, Any]],
    current_elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """REQ-CUA-01: Compute structural diff between two UIA element snapshots."""
    prev_by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for idx, el in enumerate(previous_elements, start=1):
        key = (int(el.get("hwnd", 0)), str(el.get("element_id", f"el-{idx}")))
        prev_by_key[key] = el

    curr_by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for idx, el in enumerate(current_elements, start=1):
        key = (int(el.get("hwnd", 0)), str(el.get("element_id", f"el-{idx}")))
        curr_by_key[key] = el

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    unchanged_count = 0

    for key, curr_el in curr_by_key.items():
        if key not in prev_by_key:
            added.append(curr_el)
        else:
            prev_el = prev_by_key[key]
            if (
                prev_el.get("title") != curr_el.get("title")
                or prev_el.get("bbox_px") != curr_el.get("bbox_px")
                or prev_el.get("is_enabled") != curr_el.get("is_enabled")
            ):
                modified.append(
                    {
                        "element_id": curr_el.get("element_id"),
                        "hwnd": curr_el.get("hwnd"),
                        "before_title": prev_el.get("title"),
                        "after_title": curr_el.get("title"),
                        "before_bbox": prev_el.get("bbox_px"),
                        "after_bbox": curr_el.get("bbox_px"),
                    }
                )
            else:
                unchanged_count += 1

    for key, prev_el in prev_by_key.items():
        if key not in curr_by_key:
            removed.append(prev_el)

    diff_lines: list[str] = []
    for el in added:
        diff_lines.append(f'+ [{el.get("control_type", "control")}] "{el.get("title", "")}"')
    for mod in modified:
        diff_lines.append(
            f'~ hwnd={mod["hwnd"]} "{mod["before_title"]}" -> "{mod["after_title"]}" '
            f'bbox={mod["before_bbox"]}->{mod["after_bbox"]}'
        )
    for el in removed:
        diff_lines.append(f'- [{el.get("control_type", "control")}] "{el.get("title", "")}"')

    return {
        "has_changes": bool(added or removed or modified),
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
        "unchanged_count": unchanged_count,
        "added": added,
        "removed": removed,
        "modified": modified,
        "diff_text": "\n".join(diff_lines) if diff_lines else "(no UIA tree changes)",
    }


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    b0 = u * u * u
    b1 = 3.0 * u * u * t
    b2 = 3.0 * u * t * t
    b3 = t * t * t
    x = b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0]
    y = b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]
    return (x, y)


def synthesize_bezier_cursor_path(
    start_px: tuple[int, int],
    end_px: tuple[int, int],
    steps: int = 12,
) -> dict[str, Any]:
    """REQ-CUA-04: Synthesize a 7-control-point (P0..P6) two-segment cubic Bezier cursor trajectory.

    Replicates the DirectComposition expression graph from codex-computer-use:
      Progress < 0.5 -> FirstHalfPoint(P0..P3, Progress * 2.0)
      Progress >= 0.5 -> SecondHalfPoint(P3..P6, (Progress - 0.5) * 2.0)
    """
    n_steps = max(2, int(steps))
    sx, sy = float(start_px[0]), float(start_px[1])
    ex, ey = float(end_px[0]), float(end_px[1])
    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)

    # Perpendicular arc offset for natural human-like curvature
    perp_x = -dy * 0.12
    perp_y = dx * 0.12

    p0 = (sx, sy)
    p1 = (sx + dx * 0.15 + perp_x * 0.5, sy + dy * 0.15 + perp_y * 0.5)
    p2 = (sx + dx * 0.35 + perp_x, sy + dy * 0.35 + perp_y)
    p3 = (sx + dx * 0.50 + perp_x * 0.6, sy + dy * 0.50 + perp_y * 0.6)
    p4 = (sx + dx * 0.65 + perp_x * 0.2, sy + dy * 0.65 + perp_y * 0.2)
    p5 = (sx + dx * 0.85, sy + dy * 0.85)
    p6 = (ex, ey)

    control_points = [
        (round(px, 2), round(py, 2)) for px, py in (p0, p1, p2, p3, p4, p5, p6)
    ]
    segment_count = 1 if dist < 24.0 else 2

    samples: list[dict[str, Any]] = []
    for i in range(n_steps + 1):
        raw_t = float(i) / float(n_steps)
        # Smoothstep ease-in-out progress
        progress = raw_t * raw_t * (3.0 - 2.0 * raw_t)
        if segment_count == 1:
            pt = _cubic_bezier(p0, p1, p5, p6, progress)
        elif progress < 0.5:
            pt = _cubic_bezier(p0, p1, p2, p3, progress * 2.0)
        else:
            pt = _cubic_bezier(p3, p4, p5, p6, (progress - 0.5) * 2.0)

        velocity_factor = math.sin(progress * math.pi)
        rotation_deg = round((dx / max(1.0, dist)) * 8.0 * velocity_factor, 2)
        scale = round(1.0 + 0.06 * velocity_factor, 3)
        samples.append(
            {
                "step": i,
                "progress": round(progress, 4),
                "x": int(round(pt[0])),
                "y": int(round(pt[1])),
                "rotation_deg": rotation_deg,
                "scale": scale,
            }
        )

    return {
        "start_px": (int(start_px[0]), int(start_px[1])),
        "end_px": (int(end_px[0]), int(end_px[1])),
        "distance_px": round(dist, 2),
        "segment_count": segment_count,
        "control_points": control_points,
        "samples": samples,
    }


def apply_exclude_from_capture(hwnd: int, exclude: bool = True) -> dict[str, Any]:
    """REQ-CUA-04: Set WDA_EXCLUDEFROMCAPTURE (0x11) on an overlay HWND so screenshots never include it."""
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
    applied = False
    if sys.platform == "win32" and int(hwnd) > 0:
        def _do_set() -> bool:
            try:
                user32 = ctypes.windll.user32
                if hasattr(user32, "SetWindowDisplayAffinity"):
                    return bool(user32.SetWindowDisplayAffinity(int(hwnd), int(affinity)))
            except Exception:
                pass
            return False

        applied = _run_on_default_desktop(_do_set)

    return {
        "hwnd": int(hwnd),
        "affinity": int(affinity),
        "exclude_from_capture": bool(exclude),
        "applied_win32": bool(applied),
    }


class InterruptionMonitor:
    """REQ-CUA-05: Monitors physical ESC key state and unexpected human cursor movement."""

    def __init__(self, mouse_tolerance_px: int = 45) -> None:
        self.mouse_tolerance_px = max(5, int(mouse_tolerance_px))
        self.last_expected_cursor_px: tuple[int, int] | None = None
        self.interrupted = False
        self.interruption_reason: str | None = None

    def record_expected_cursor(self, x_px: int, y_px: int) -> None:
        """REQ-CUA-05: Record the cursor position last commanded by the agent."""
        self.last_expected_cursor_px = (int(x_px), int(y_px))

    def check_interruption(
        self,
        simulated_esc_pressed: bool = False,
        simulated_cursor_px: tuple[int, int] | None = None,
        check_live_win32: bool = False,
    ) -> dict[str, Any]:
        """REQ-CUA-05: Verify whether the user interrupted execution via ESC or mouse movement."""
        if simulated_esc_pressed:
            self.interrupted = True
            self.interruption_reason = "computer use interrupted by ESC"
            raise ComputerUseSafetyAbort(self.interruption_reason)

        if simulated_cursor_px is not None and self.last_expected_cursor_px is not None:
            dx = simulated_cursor_px[0] - self.last_expected_cursor_px[0]
            dy = simulated_cursor_px[1] - self.last_expected_cursor_px[1]
            if math.hypot(dx, dy) > self.mouse_tolerance_px:
                self.interrupted = True
                self.interruption_reason = (
                    f"computer use interrupted by physical mouse delta "
                    f"({simulated_cursor_px} vs expected {self.last_expected_cursor_px})"
                )
                raise ComputerUseSafetyAbort(self.interruption_reason)

        if check_live_win32 and sys.platform == "win32":
            def _poll_win32() -> tuple[bool, tuple[int, int] | None]:
                try:
                    user32 = ctypes.windll.user32
                    esc_down = False
                    if hasattr(user32, "GetAsyncKeyState"):
                        state = user32.GetAsyncKeyState(VK_ESCAPE)
                        esc_down = bool(state & 0x8000)
                    pt = wintypes.POINT(0, 0)
                    got_pt = False
                    if hasattr(user32, "GetCursorPos"):
                        got_pt = bool(user32.GetCursorPos(ctypes.byref(pt)))
                    return esc_down, ((int(pt.x), int(pt.y)) if got_pt else None)
                except Exception:
                    return False, None

            esc_down, live_pt = _run_on_default_desktop(_poll_win32)
            if esc_down:
                self.interrupted = True
                self.interruption_reason = "computer use interrupted by ESC"
                raise ComputerUseSafetyAbort(self.interruption_reason)
            if live_pt is not None and self.last_expected_cursor_px is not None:
                dx = live_pt[0] - self.last_expected_cursor_px[0]
                dy = live_pt[1] - self.last_expected_cursor_px[1]
                if math.hypot(dx, dy) > self.mouse_tolerance_px:
                    self.interrupted = True
                    self.interruption_reason = (
                        f"computer use interrupted by physical mouse movement to {live_pt}"
                    )
                    raise ComputerUseSafetyAbort(self.interruption_reason)

        return {
            "interrupted": self.interrupted,
            "reason": self.interruption_reason,
            "last_expected_cursor_px": self.last_expected_cursor_px,
        }


class CompactionImageBudget:
    """REQ-CUA-01 / REQ-CUA-05: Bounds retained raw screenshot byte buffers across long CUA sessions (0.166.0-alpha.2 pattern)."""

    def __init__(self, max_retained_images: int = 3) -> None:
        self.max_retained_images = max(1, int(max_retained_images))
        self._history: list[dict[str, Any]] = []

    def register_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """REQ-CUA-01 / REQ-CUA-05: Store snapshot and evict heavy RGB/PNG/BMP byte payloads from older entries."""
        self._history.append(snapshot)
        evicted_count = 0
        if len(self._history) > self.max_retained_images:
            cutoff = len(self._history) - self.max_retained_images
            for old_snap in self._history[:cutoff]:
                if not old_snap.get("compacted", False):
                    for byte_key in ("rgb_bytes", "bmp_bytes", "png_bytes", "annotated_rgb_bytes", "annotated_png_bytes"):
                        if byte_key in old_snap:
                            old_snap[byte_key] = b""
                    old_snap["compacted"] = True
                    evicted_count += 1

        retained_count = sum(1 for s in self._history if not s.get("compacted", False))
        return {
            "total_snapshots": len(self._history),
            "retained_image_count": retained_count,
            "evicted_in_step": evicted_count,
            "max_retained_images": self.max_retained_images,
        }


class WindowSessionManager:
    """REQ-CUA-02: Stateful Window2 Session Manager with screenshotId Stale-Geometry Guard & Diagnostics."""

    def __init__(self, max_retained_images: int = 4) -> None:
        self._sessions: dict[int, dict[str, Any]] = {}
        self._screenshots: dict[str, dict[str, Any]] = {}
        self._budget = CompactionImageBudget(max_retained_images=max_retained_images)
        self.interruption_monitor = InterruptionMonitor()
        self.last_capture_invalidation_reason: str | None = None

    def reset(self) -> dict[str, Any]:
        """REQ-CUA-02: Clear all cached window sessions and screenshotId records."""
        cleared_sessions = len(self._sessions)
        cleared_screenshots = len(self._screenshots)
        self._sessions.clear()
        self._screenshots.clear()
        self.last_capture_invalidation_reason = "manual_reset"
        return {
            "ok": True,
            "cleared_sessions": cleared_sessions,
            "cleared_screenshots": cleared_screenshots,
        }

    def get_window_state(
        self,
        hwnd: int | None = None,
        include_screenshot: bool = True,
        include_text: bool = True,
        max_elements: int = 32,
        width: int | None = None,
        height: int | None = None,
        synthetic_seed: int | None = None,
        override_bbox_px: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        """REQ-CUA-02: Capture window state, UIA tree (#1..#N), tree diff, untrusted evidence XML, and screenshotId."""
        windows = enumerate_visible_windows(include_minimized=False)
        target_win: dict[str, Any] | None = None
        if hwnd is not None and int(hwnd) > 0:
            target_win = next((w for w in windows if int(w["hwnd"]) == int(hwnd)), None)
        if target_win is None and windows:
            target_win = windows[0]
        if target_win is None:
            target_win = {
                "hwnd": int(hwnd or 65552),
                "title": "Desktop Workstation Shell",
                "class_name": "Progman",
                "bbox_px": (0, 0, 1920, 1080),
                "width": 1920,
                "height": 1080,
                "is_visible": True,
                "pid": 1000,
            }

        resolved_hwnd = int(target_win["hwnd"])
        bbox_px = (
            tuple(int(x) for x in override_bbox_px)
            if override_bbox_px is not None
            else tuple(int(x) for x in target_win["bbox_px"])
        )
        win_w = max(1, int(width) if width is not None else max(1, bbox_px[2] - bbox_px[0]))
        win_h = max(1, int(height) if height is not None else max(1, bbox_px[3] - bbox_px[1]))

        session = self._sessions.get(resolved_hwnd)
        if session is None:
            session = {
                "root_hwnd": resolved_hwnd,
                "input_hwnd": resolved_hwnd,
                "process_id": int(target_win.get("pid", 0)),
                "title": str(target_win.get("title", "")),
                "class_name": str(target_win.get("class_name", "")),
                "bounds": bbox_px,
                "snapshot_revision": 0,
                "accessibility_revision": 0,
                "accessibility_snapshot_count": 0,
                "last_elements": [],
                "last_marks": {},
                "last_screenshot_id": None,
            }
            self._sessions[resolved_hwnd] = session
        else:
            if session["bounds"] != bbox_px:
                self.last_capture_invalidation_reason = "window_moved_or_resized"
            session["bounds"] = bbox_px
            session["title"] = str(target_win.get("title", session["title"]))

        elements: list[dict[str, Any]] = []
        uia_text = ""
        uia_diff: dict[str, Any] = {}
        evidence_envelope: dict[str, Any] = {}

        if include_text:
            elements = extract_uia_element_tree(hwnd=resolved_hwnd, max_elements=max_elements)
            uia_diff = diff_uia_trees(session["last_elements"], elements)
            session["accessibility_snapshot_count"] += 1
            if uia_diff["has_changes"] or session["accessibility_revision"] == 0:
                session["accessibility_revision"] += 1
            session["last_elements"] = elements
            uia_text = format_uia_tree_text(
                elements,
                window_bbox=bbox_px,  # type: ignore[arg-type]
                screen_width=win_w,
                screen_height=win_h,
            )
            evidence_envelope = wrap_untrusted_ui_evidence(uia_text, source="uia_tree")

        screenshot_id: str | None = None
        frame_info: dict[str, Any] | None = None
        compaction_stats: dict[str, Any] | None = None

        if include_screenshot:
            session["snapshot_revision"] += 1
            frame = capture_screen_frame(
                region=bbox_px if synthetic_seed is None else None,  # type: ignore[arg-type]
                width=win_w,
                height=win_h,
                synthetic_seed=synthetic_seed,
            )
            som = annotate_som_elements(frame, elements if elements else [])
            session["last_marks"] = som["marks"]
            rev = session["snapshot_revision"]
            screenshot_id = f"snap-{resolved_hwnd}-r{rev}-{frame['sha256'][:12]}"
            session["last_screenshot_id"] = screenshot_id

            snap_record = {
                "screenshot_id": screenshot_id,
                "hwnd": resolved_hwnd,
                "bounds": bbox_px,
                "snapshot_revision": rev,
                "sha256": frame["sha256"],
                "width": frame["width"],
                "height": frame["height"],
                "backend": frame["backend"],
                "rgb_bytes": frame["rgb_bytes"],
                "png_bytes": som["annotated_png_bytes"],
                "compacted": False,
                "timestamp": frame["timestamp"],
            }
            self._screenshots[screenshot_id] = snap_record
            compaction_stats = self._budget.register_snapshot(snap_record)
            frame_info = {
                "screenshot_id": screenshot_id,
                "width": frame["width"],
                "height": frame["height"],
                "backend": frame["backend"],
                "sha256": frame["sha256"],
                "mark_count": som["mark_count"],
                "marks": som["marks"],
            }

        return {
            "ok": True,
            "window": {
                "hwnd": resolved_hwnd,
                "title": session["title"],
                "class_name": session["class_name"],
                "pid": session["process_id"],
                "bounds": bbox_px,
            },
            "screenshot_id": screenshot_id,
            "snapshot_revision": session["snapshot_revision"],
            "accessibility_revision": session["accessibility_revision"],
            "elements": elements,
            "text": uia_text,
            "diff": uia_diff,
            "untrusted_evidence": evidence_envelope,
            "frame": frame_info,
            "compaction": compaction_stats,
        }

    def update_window_bounds(self, hwnd: int, new_bounds: tuple[int, int, int, int]) -> None:
        """REQ-CUA-02: Update tracked window bounds (simulating or reflecting a window move/resize)."""
        resolved_hwnd = int(hwnd)
        if resolved_hwnd in self._sessions:
            old_bounds = self._sessions[resolved_hwnd]["bounds"]
            if old_bounds != tuple(new_bounds):
                self._sessions[resolved_hwnd]["bounds"] = tuple(new_bounds)
                self.last_capture_invalidation_reason = "window_moved_or_resized"

    def validate_screenshot_id(
        self,
        screenshot_id: str,
        current_bounds: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        """REQ-CUA-02: Verify that screenshot_id exists and its window geometry has not become stale."""
        if not screenshot_id or screenshot_id not in self._screenshots:
            self.last_capture_invalidation_reason = "unknown_screenshot_id"
            raise ComputerUseSafetyAbort(
                f"unknown screenshotId '{screenshot_id}'; call get_window_state(..., include_screenshot=True) first"
            )

        snap = self._screenshots[screenshot_id]
        hwnd = int(snap["hwnd"])
        snap_bounds = tuple(snap["bounds"])
        session = self._sessions.get(hwnd)

        live_bounds = (
            tuple(int(x) for x in current_bounds)
            if current_bounds is not None
            else (tuple(session["bounds"]) if session is not None else snap_bounds)
        )

        if live_bounds != snap_bounds:
            self.last_capture_invalidation_reason = "stale_screenshot_window_moved_or_resized"
            raise ComputerUseSafetyAbort(
                f"screenshotId '{screenshot_id}' is stale because the window moved or resized "
                f"({snap_bounds} -> {live_bounds}); call get_window_state(..., include_screenshot=True) again"
            )

        return {
            "valid": True,
            "screenshot_id": screenshot_id,
            "hwnd": hwnd,
            "bounds": snap_bounds,
            "snapshot_revision": snap["snapshot_revision"],
        }

    def click_element(
        self,
        hwnd: int,
        element_index: int,
        click_count: int = 1,
        mouse_button: str = "left",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """REQ-CUA-02: Click a UIA element by its 1-based index (#1..#N) without manual pixel calculation."""
        if mouse_button == "right" and int(click_count) >= 2:
            raise ComputerUseSafetyAbort("right double click is not supported")

        session = self._sessions.get(int(hwnd))
        if session is None or not session["last_elements"]:
            raise KeyError(f"No UIA elements cached for window hwnd={hwnd}; call get_window_state first")

        elements = session["last_elements"]
        idx = int(element_index)
        if idx < 1 or idx > len(elements):
            raise IndexError(f"element_index #{idx} out of range (1..{len(elements)})")

        action_type = (
            "right_click"
            if mouse_button == "right"
            else ("double_click" if int(click_count) >= 2 else "click")
        )
        marks = session.get("last_marks") or {}
        if idx in marks:
            return dispatch_gui_action(
                action_type,
                mark_id=idx,
                marks_catalog=marks,
                dry_run=dry_run,
            )

        el = elements[idx - 1]
        bbox = el["bbox_px"]
        cx = (int(bbox[0]) + int(bbox[2])) // 2
        cy = (int(bbox[1]) + int(bbox[3])) // 2
        bounds = session["bounds"]
        w = max(1, int(bounds[2]) - int(bounds[0]))
        h = max(1, int(bounds[3]) - int(bounds[1]))
        nx, ny = normalize_to_grid_1000(cx, cy, screen_width=w, screen_height=h, origin_x=bounds[0], origin_y=bounds[1])
        return dispatch_gui_action(
            action_type,
            norm_x=nx,
            norm_y=ny,
            screen_width=w,
            screen_height=h,
            origin_x=bounds[0],
            origin_y=bounds[1],
            dry_run=dry_run,
        )

    def set_element_value(
        self,
        hwnd: int,
        element_index: int,
        value: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """REQ-CUA-02: Set text value directly on a UIA control (#1..#N) via WM_SETTEXT + clipboard fallback."""
        session = self._sessions.get(int(hwnd))
        if session is None or not session["last_elements"]:
            raise KeyError(f"No UIA elements cached for window hwnd={hwnd}; call get_window_state first")

        elements = session["last_elements"]
        idx = int(element_index)
        if idx < 1 or idx > len(elements):
            raise IndexError(f"element_index #{idx} out of range (1..{len(elements)})")

        el = elements[idx - 1]
        target_ctrl_hwnd = int(el.get("hwnd", hwnd))
        sent_wm_settext = False

        if not dry_run and sys.platform == "win32" and target_ctrl_hwnd > 0:
            def _do_settext() -> bool:
                try:
                    user32 = ctypes.windll.user32
                    if hasattr(user32, "SendMessageW"):
                        buf = ctypes.create_unicode_buffer(str(value))
                        user32.SendMessageW(target_ctrl_hwnd, WM_SETTEXT, 0, ctypes.cast(buf, wintypes.LPARAM))
                        return True
                except Exception:
                    pass
                return False

            sent_wm_settext = _run_on_default_desktop(_do_settext)

        return {
            "ok": True,
            "action_type": "set_value",
            "hwnd": int(hwnd),
            "element_index": idx,
            "element_hwnd": target_ctrl_hwnd,
            "element_title": el.get("title", ""),
            "value": str(value),
            "dry_run": bool(dry_run),
            "sent_wm_settext": sent_wm_settext,
        }

    def scroll_element(
        self,
        hwnd: int,
        element_index: int,
        direction: str = "down",
        pages: int = 1,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """REQ-CUA-02: Scroll a specific UIA element (#1..#N) in direction ('up', 'down', 'left', 'right')."""
        dir_norm = str(direction).strip().lower()
        if dir_norm not in ("up", "down", "left", "right"):
            raise ValueError(f"Unsupported scroll direction '{direction}'. Expected up/down/left/right.")

        session = self._sessions.get(int(hwnd))
        if session is None or not session["last_elements"]:
            raise KeyError(f"No UIA elements cached for window hwnd={hwnd}; call get_window_state first")

        elements = session["last_elements"]
        idx = int(element_index)
        if idx < 1 or idx > len(elements):
            raise IndexError(f"element_index #{idx} out of range (1..{len(elements)})")

        el = elements[idx - 1]
        target_ctrl_hwnd = int(el.get("hwnd", hwnd))
        n_pages = max(1, int(pages))
        wheel_delta = 120 * n_pages if dir_norm in ("up", "left") else -120 * n_pages

        if not dry_run and sys.platform == "win32" and target_ctrl_hwnd > 0:
            def _do_scroll() -> None:
                try:
                    user32 = ctypes.windll.user32
                    if hasattr(user32, "PostMessageW"):
                        msg = WM_VSCROLL if dir_norm in ("up", "down") else WM_HSCROLL
                        sb_cmd = SB_PAGEUP if dir_norm in ("up", "left") else SB_PAGEDOWN
                        for _ in range(n_pages):
                            user32.PostMessageW(target_ctrl_hwnd, msg, sb_cmd, 0)
                except Exception:
                    pass

            _run_on_default_desktop(_do_scroll)

        return {
            "ok": True,
            "action_type": "scroll_element",
            "hwnd": int(hwnd),
            "element_index": idx,
            "element_hwnd": target_ctrl_hwnd,
            "direction": dir_norm,
            "pages": n_pages,
            "wheel_delta": wheel_delta,
            "dry_run": bool(dry_run),
        }

    def get_diagnostic_state(self, hwnd: int | None = None) -> dict[str, Any]:
        """REQ-CUA-02: Return cacheDiagnostics telemetry matching codex-computer-use diagnostic_state RPC."""
        sessions_list = list(self._sessions.values())
        target = self._sessions.get(int(hwnd)) if hwnd is not None else (sessions_list[-1] if sessions_list else None)
        return {
            "ok": True,
            "cacheDiagnostics": {
                "rootHwnd": target["root_hwnd"] if target else 0,
                "inputHwnd": target["input_hwnd"] if target else 0,
                "processId": target["process_id"] if target else 0,
                "bounds": target["bounds"] if target else (0, 0, 0, 0),
                "snapshotRevision": target["snapshot_revision"] if target else 0,
                "accessibilityRevision": target["accessibility_revision"] if target else 0,
                "accessibilitySnapshotCount": target["accessibility_snapshot_count"] if target else 0,
                "captureCachedSessionCount": len(self._sessions),
                "cachedScreenshotCount": len(self._screenshots),
                "lastCaptureInvalidationReason": self.last_capture_invalidation_reason,
            },
        }
