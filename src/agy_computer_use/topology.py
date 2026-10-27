"""Antigravity Multi-Monitor Desktop Topology Router (REQ-CUA-202).

Enumerates Win32 virtual multi-display topologies, normalizes negative virtual desktop
coordinates (e.g. secondary monitors left or above the primary monitor), and maps
bidirectionally between per-monitor [0, 1000] x [0, 1000] normalized grids and virtual
desktop pixels.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
from typing import Any

from agy_computer_use.som import get_monitor_dpi_scale


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORINFOF_PRIMARY = 1


def enumerate_display_monitors() -> list[dict[str, Any]]:
    """Enumerate all connected display monitors and their virtual bounding rects (REQ-CUA-202).

    Returns a list of dicts with keys:
        monitor_id (int): 1-based index
        virtual_left (int): Left pixel bound in virtual desktop
        virtual_top (int): Top pixel bound in virtual desktop
        virtual_right (int): Right pixel bound in virtual desktop
        virtual_bottom (int): Bottom pixel bound in virtual desktop
        width (int): Pixel width
        height (int): Pixel height
        is_primary (bool): True for primary display (at 0,0)
        dpi_scale (float): Per-monitor DPI scaling factor
    """
    monitors: list[dict[str, Any]] = []

    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32

            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                wintypes.HMONITOR,
                wintypes.HDC,
                ctypes.POINTER(_RECT),
                wintypes.LPARAM,
            )

            def _enum_proc(hmonitor: int, _hdc: int, _lprect: Any, _lparam: int) -> bool:
                info = _MONITORINFOEXW()
                info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
                if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                    left = int(info.rcMonitor.left)
                    top = int(info.rcMonitor.top)
                    right = int(info.rcMonitor.right)
                    bottom = int(info.rcMonitor.bottom)
                    w = max(1, right - left)
                    h = max(1, bottom - top)
                    is_prim = bool(info.dwFlags & MONITORINFOF_PRIMARY)
                    dpi = get_monitor_dpi_scale(int(hmonitor))

                    monitors.append(
                        {
                            "monitor_id": len(monitors) + 1,
                            "virtual_left": left,
                            "virtual_top": top,
                            "virtual_right": right,
                            "virtual_bottom": bottom,
                            "width": w,
                            "height": h,
                            "is_primary": is_prim,
                            "dpi_scale": float(dpi),
                        }
                    )
                return True

            callback = MONITORENUMPROC(_enum_proc)
            user32.EnumDisplayMonitors(0, 0, callback, 0)
        except Exception:
            pass

    if not monitors:
        monitors.append(
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
        )

    # Ensure exactly one monitor is designated primary
    primaries = [m for m in monitors if m.get("is_primary")]
    if len(primaries) == 0:
        monitors[0]["is_primary"] = True
    elif len(primaries) > 1:
        for m in monitors[1:]:
            m["is_primary"] = False
        monitors[0]["is_primary"] = True

    return monitors


def map_monitor_grid_1000_to_virtual(
    norm_x: int,
    norm_y: int,
    monitor_id: int,
    monitors: list[dict[str, Any]] | None = None,
) -> tuple[int, int]:
    """Map per-monitor [0..1000] normalized grid coordinates to virtual desktop pixels (REQ-CUA-202)."""
    if norm_x < 0 or norm_x > 1000 or norm_y < 0 or norm_y > 1000:
        raise ValueError(f"Normalized coordinates must be within [0, 1000], got ({norm_x}, {norm_y})")

    if monitors is None:
        monitors = enumerate_display_monitors()

    target: dict[str, Any] | None = None
    for m in monitors:
        if m.get("monitor_id") == monitor_id:
            target = m
            break

    if target is None:
        raise KeyError(f"Monitor with monitor_id={monitor_id} not found in topology")

    v_left = target["virtual_left"]
    v_top = target["virtual_top"]
    w = target["width"]
    h = target["height"]

    vx = int(v_left) + int(round((float(norm_x) / 1000.0) * float(w)))
    vy = int(v_top) + int(round((float(norm_y) / 1000.0) * float(h)))
    return (vx, vy)


def map_virtual_to_monitor_grid_1000(
    vx: int,
    vy: int,
    monitors: list[dict[str, Any]] | None = None,
) -> tuple[int, int, dict[str, Any]]:
    """Map global virtual desktop pixel coordinates to per-monitor [0..1000] grid (REQ-CUA-202)."""
    if monitors is None:
        monitors = enumerate_display_monitors()

    if not monitors:
        raise ValueError("Empty monitors list in topology")

    # First check containment: left <= vx <= right and top <= vy <= bottom
    matched: dict[str, Any] | None = None
    for m in monitors:
        if m["virtual_left"] <= vx <= m["virtual_right"] and m["virtual_top"] <= vy <= m["virtual_bottom"]:
            matched = m
            break

    # If point is outside all monitor bounds, find closest monitor by Euclidean center distance
    if matched is None:
        best_dist = float("inf")
        for m in monitors:
            cx = (m["virtual_left"] + m["virtual_right"]) / 2.0
            cy = (m["virtual_top"] + m["virtual_bottom"]) / 2.0
            dist = (vx - cx) ** 2 + (vy - cy) ** 2
            if dist < best_dist:
                best_dist = dist
                matched = m

    assert matched is not None
    v_left = matched["virtual_left"]
    v_top = matched["virtual_top"]
    w = max(1, matched["width"])
    h = max(1, matched["height"])

    rel_x = float(vx - v_left)
    rel_y = float(vy - v_top)

    norm_x = int(round((rel_x / float(w)) * 1000.0))
    norm_y = int(round((rel_y / float(h)) * 1000.0))

    norm_x = max(0, min(1000, norm_x))
    norm_y = max(0, min(1000, norm_y))

    return (norm_x, norm_y, matched)
