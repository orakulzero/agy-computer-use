"""Antigravity Pure-Python Visual Anchor & Template Matcher (REQ-CUA-203).

Provides zero-dependency Sum of Absolute Differences (SAD) and Normalized Cross
Correlation (NCC) template matching with integral image prefix sums for fast
bounding box intensity normalization.
"""

from __future__ import annotations

import math
from typing import Any


def compute_integral_image(grayscale_matrix: list[list[int]]) -> list[list[int]]:
    """Compute (H+1) x (W+1) 2D prefix sums table with row 0 and col 0 zero-padded (REQ-CUA-203)."""
    if not grayscale_matrix or not grayscale_matrix[0]:
        return [[0]]

    h = len(grayscale_matrix)
    w = len(grayscale_matrix[0])

    integral: list[list[int]] = [[0] * (w + 1) for _ in range(h + 1)]

    for r in range(1, h + 1):
        row_sum = 0
        for c in range(1, w + 1):
            val = grayscale_matrix[r - 1][c - 1]
            row_sum += val
            integral[r][c] = integral[r - 1][c] + row_sum

    return integral


def _rgb_to_grayscale_matrix(rgb_bytes: bytes, width: int, height: int) -> list[list[int]]:
    """Convert raw 24-bit RGB bytes into an H x W grayscale integer matrix (0..255)."""
    matrix: list[list[int]] = []
    idx = 0
    for _ in range(height):
        row: list[int] = []
        for _ in range(width):
            r = rgb_bytes[idx]
            g = rgb_bytes[idx + 1]
            b = rgb_bytes[idx + 2]
            idx += 3
            gray = (r * 299 + g * 587 + b * 114) // 1000
            row.append(gray)
        matrix.append(row)
    return matrix


def find_visual_anchor_on_screen(
    screen_rgb: bytes,
    width: int,
    height: int,
    template_rgb: bytes,
    tmpl_width: int,
    tmpl_height: int,
    method: str = "SAD",
    threshold: float = 0.85,
) -> dict[str, Any]:
    """Locate a template RGB icon on screen RGB using pure Python SAD or NCC (REQ-CUA-203).

    Returns:
        found (bool): True if best match score >= threshold
        match_score (float): Best match score in [0.0, 1.0]
        location_px (tuple[int, int] | None): (x, y) top-left pixel
        bbox_px (tuple[int, int, int, int] | None): (left, top, right, bottom)
        center_norm_x (int | None): Normalized [0..1000] center X
        center_norm_y (int | None): Normalized [0..1000] center Y
        method (str): Method used ("SAD" or "NCC")
    """
    norm_method = method.upper()
    if norm_method not in ("SAD", "NCC"):
        raise ValueError(f"Unsupported matching method: {method}. Choose 'SAD' or 'NCC'.")

    if width <= 0 or height <= 0:
        raise ValueError("Screen dimensions must be positive integers")
    if tmpl_width <= 0 or tmpl_height <= 0:
        raise ValueError("Template dimensions must be positive integers")
    if tmpl_width > width or tmpl_height > height:
        raise ValueError("Template dimensions exceed screen dimensions")
    if len(screen_rgb) != width * height * 3:
        raise ValueError(f"screen_rgb byte length mismatch: expected {width * height * 3}, got {len(screen_rgb)}")
    if len(template_rgb) != tmpl_width * tmpl_height * 3:
        raise ValueError(f"template_rgb byte length mismatch: expected {tmpl_width * tmpl_height * 3}, got {len(template_rgb)}")

    screen_gray = _rgb_to_grayscale_matrix(screen_rgb, width, height)
    tmpl_gray = _rgb_to_grayscale_matrix(template_rgb, tmpl_width, tmpl_height)

    total_pixels = tmpl_width * tmpl_height
    best_score = -1.0
    best_loc: tuple[int, int] | None = None

    if norm_method == "SAD":
        max_possible_diff = total_pixels * 255.0
        for sy in range(height - tmpl_height + 1):
            for sx in range(width - tmpl_width + 1):
                diff_sum = 0
                for ty in range(tmpl_height):
                    s_row = screen_gray[sy + ty]
                    t_row = tmpl_gray[ty]
                    for tx in range(tmpl_width):
                        diff_sum += abs(s_row[sx + tx] - t_row[tx])
                score = 1.0 - (float(diff_sum) / max_possible_diff)
                if score > best_score:
                    best_score = score
                    best_loc = (sx, sy)
    else:  # NCC
        tmpl_sum = sum(sum(row) for row in tmpl_gray)
        tmpl_mean = float(tmpl_sum) / float(total_pixels)
        tmpl_diffs = [[tmpl_gray[ty][tx] - tmpl_mean for tx in range(tmpl_width)] for ty in range(tmpl_height)]
        tmpl_sq_sum = sum(sum(d * d for d in row) for row in tmpl_diffs)
        tmpl_std = math.sqrt(max(0.0, tmpl_sq_sum))

        for sy in range(height - tmpl_height + 1):
            for sx in range(width - tmpl_width + 1):
                patch_sum = 0
                for ty in range(tmpl_height):
                    s_row = screen_gray[sy + ty]
                    for tx in range(tmpl_width):
                        patch_sum += s_row[sx + tx]
                patch_mean = float(patch_sum) / float(total_pixels)

                cov = 0.0
                patch_sq_sum = 0.0
                for ty in range(tmpl_height):
                    s_row = screen_gray[sy + ty]
                    t_diff_row = tmpl_diffs[ty]
                    for tx in range(tmpl_width):
                        p_diff = s_row[sx + tx] - patch_mean
                        cov += p_diff * t_diff_row[tx]
                        patch_sq_sum += p_diff * p_diff

                patch_std = math.sqrt(max(0.0, patch_sq_sum))
                if patch_std > 0 and tmpl_std > 0:
                    ncc = cov / (patch_std * tmpl_std)
                else:
                    ncc = 1.0 if tmpl_std == 0 and patch_std == 0 and abs(patch_mean - tmpl_mean) < 1.0 else -1.0

                score = max(0.0, min(1.0, (ncc + 1.0) / 2.0))
                if score > best_score:
                    best_score = score
                    best_loc = (sx, sy)

    best_score = max(0.0, float(best_score))
    found = bool(best_score >= threshold and best_loc is not None)

    if found and best_loc is not None:
        bx, by = best_loc
        bbox = (bx, by, bx + tmpl_width, by + tmpl_height)
        cx = bx + tmpl_width // 2
        cy = by + tmpl_height // 2
        norm_cx = max(0, min(1000, int(round((float(cx) / float(width)) * 1000.0))))
        norm_cy = max(0, min(1000, int(round((float(cy) / float(height)) * 1000.0))))
        return {
            "found": True,
            "match_score": round(best_score, 4),
            "location_px": (bx, by),
            "bbox_px": bbox,
            "center_norm_x": norm_cx,
            "center_norm_y": norm_cy,
            "method": norm_method,
        }
    else:
        return {
            "found": False,
            "match_score": round(best_score if best_score >= 0 else 0.0, 4),
            "location_px": None,
            "bbox_px": None,
            "center_norm_x": None,
            "center_norm_y": None,
            "method": norm_method,
        }
