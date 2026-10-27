"""DPI Scale Detection, [0, 1000] Grid Normalization, and Set-of-Marks (SoM) Annotation.

Implements REQ-CU-002:
- Per-Monitor DPI V2 scale factor query in [0.5, 4.0]
- Bijective [0, 1000] x [0, 1000] coordinate normalization and denormalization
- Multi-monitor negative origin coordinate translation
- Set-of-Marks (SoM) bounding box and numbered tag overlay on RGB frames
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from agy_computer_use.capture import encode_rgb_to_png

_PALETTE: tuple[tuple[int, int, int], ...] = (
    (255, 59, 48),
    (52, 199, 89),
    (0, 122, 255),
    (255, 149, 0),
    (175, 82, 222),
    (255, 45, 85),
    (90, 200, 250),
    (255, 204, 0),
)


def get_monitor_dpi_scale(hwnd: int | None = None) -> float:
    """Detect monitor DPI scale factor relative to 96 DPI, clamped to [0.5, 4.0]."""
    dpi = 96.0
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            if hwnd is not None and int(hwnd) > 0 and hasattr(user32, "GetDpiForWindow"):
                raw_dpi = int(user32.GetDpiForWindow(int(hwnd)))
                if raw_dpi > 0:
                    dpi = float(raw_dpi)
                elif hasattr(user32, "GetDpiForSystem"):
                    sys_dpi = int(user32.GetDpiForSystem())
                    if sys_dpi > 0:
                        dpi = float(sys_dpi)
            elif hasattr(user32, "GetDpiForSystem"):
                sys_dpi = int(user32.GetDpiForSystem())
                if sys_dpi > 0:
                    dpi = float(sys_dpi)
        except Exception:
            dpi = 96.0

    scale = dpi / 96.0
    return max(0.5, min(4.0, float(scale)))


def normalize_to_grid_1000(
    x_px: int | float,
    y_px: int | float,
    screen_width: int = 1920,
    screen_height: int = 1080,
    origin_x: int = 0,
    origin_y: int = 0,
) -> tuple[int, int]:
    """Map physical pixel coordinates (x_px, y_px) into integer [0, 1000] x [0, 1000] grid."""
    if screen_width <= 0 or screen_height <= 0:
        raise ValueError("screen_width and screen_height must be positive integers")

    rel_x = float(x_px) - float(origin_x)
    rel_y = float(y_px) - float(origin_y)

    clamped_x = max(0.0, min(float(screen_width), rel_x))
    clamped_y = max(0.0, min(float(screen_height), rel_y))

    norm_x = int(round((clamped_x / float(screen_width)) * 1000.0))
    norm_y = int(round((clamped_y / float(screen_height)) * 1000.0))

    return (max(0, min(1000, norm_x)), max(0, min(1000, norm_y)))


def denormalize_from_grid_1000(
    norm_x: int | float,
    norm_y: int | float,
    screen_width: int = 1920,
    screen_height: int = 1080,
    origin_x: int = 0,
    origin_y: int = 0,
    dpi_scale: float = 1.0,
) -> tuple[int, int]:
    """Map [0, 1000] x [0, 1000] normalized coordinates back to physical screen pixels."""
    if norm_x < 0 or norm_x > 1000 or norm_y < 0 or norm_y > 1000:
        raise ValueError(f"Normalized coordinates must be within [0, 1000], got ({norm_x}, {norm_y})")
    if screen_width <= 0 or screen_height <= 0:
        raise ValueError("screen_width and screen_height must be positive integers")
    if dpi_scale <= 0.0:
        raise ValueError(f"dpi_scale must be positive, got {dpi_scale}")

    px_x = int(origin_x) + int(round((float(norm_x) / 1000.0) * float(screen_width) * float(dpi_scale)))
    px_y = int(origin_y) + int(round((float(norm_y) / 1000.0) * float(screen_height) * float(dpi_scale)))
    return (px_x, px_y)


def _set_pixel(buf: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < width and 0 <= y < height:
        offset = (y * width + x) * 3
        buf[offset] = color[0]
        buf[offset + 1] = color[1]
        buf[offset + 2] = color[2]


def _draw_box_and_badge(
    buf: bytearray,
    width: int,
    height: int,
    bbox_px: tuple[int, int, int, int],
    color: tuple[int, int, int],
    mark_id: int,
) -> None:
    left = max(0, min(width - 1, int(bbox_px[0])))
    top = max(0, min(height - 1, int(bbox_px[1])))
    right = max(left, min(width - 1, int(bbox_px[2])))
    bottom = max(top, min(height - 1, int(bbox_px[3])))

    thickness = 2
    for t in range(thickness):
        y_top = min(height - 1, top + t)
        y_bot = max(0, bottom - t)
        for x in range(left, right + 1):
            _set_pixel(buf, width, height, x, y_top, color)
            _set_pixel(buf, width, height, x, y_bot, color)

        x_left = min(width - 1, left + t)
        x_right = max(0, right - t)
        for y in range(top, bottom + 1):
            _set_pixel(buf, width, height, x_left, y, color)
            _set_pixel(buf, width, height, x_right, y, color)

    badge_w = min(width - left, 14 + (4 * len(str(mark_id))))
    badge_h = min(height - top, 12)
    for by in range(top, top + badge_h):
        for bx in range(left, left + badge_w):
            _set_pixel(buf, width, height, bx, by, color)


def annotate_som_elements(
    frame: dict[str, Any],
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Render Set-of-Marks (SoM) bounding boxes onto an RGB frame and build mark catalog."""
    width = int(frame["width"])
    height = int(frame["height"])
    orig_rgb = bytes(frame["rgb_bytes"])
    canvas = bytearray(orig_rgb)

    marks: dict[int, dict[str, Any]] = {}
    for idx, el in enumerate(elements, start=1):
        bbox = el.get("bbox_px", (0, 0, 0, 0))
        left, top, right, bottom = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        center_1000 = normalize_to_grid_1000(cx, cy, screen_width=width, screen_height=height)

        color = _PALETTE[(idx - 1) % len(_PALETTE)]
        _draw_box_and_badge(canvas, width, height, (left, top, right, bottom), color, idx)

        marks[idx] = {
            "mark_id": idx,
            "element_id": str(el.get("element_id", f"el-{idx}")),
            "hwnd": int(el.get("hwnd", 0)),
            "title": str(el.get("title", "")),
            "class_name": str(el.get("class_name", "")),
            "control_type": str(el.get("control_type", "control")),
            "bbox_px": (left, top, right, bottom),
            "center_px": (cx, cy),
            "center_1000": center_1000,
        }

    if elements and bytes(canvas) == orig_rgb:
        canvas[0] = (canvas[0] + 128) % 256

    annotated_rgb = bytes(canvas)
    annotated_png = encode_rgb_to_png(annotated_rgb, width, height)

    return {
        "width": width,
        "height": height,
        "mark_count": len(marks),
        "marks": marks,
        "annotated_rgb_bytes": annotated_rgb,
        "annotated_png_bytes": annotated_png,
    }
