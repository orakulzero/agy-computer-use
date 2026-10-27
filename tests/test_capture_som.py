"""ISO 9001:2015 Agile V Verification Suite for Screen Capture, UIA & Set-of-Marks (SoM).

Covers REQ-CU-001 (Win32 GDI & Synthetic Screen Capture, Window Enumeration, UIA Tree)
and REQ-CU-002 (DPI Scale Detection, [0..1000] Grid Normalization, Set-of-Marks Overlay).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_package_version_and_public_reexports() -> None:
    """Verify package version 1.0.0 and top-level re-exports across all submodules."""
    import agy_computer_use

    assert agy_computer_use.__version__ == "1.0.0"
    expected_symbols = (
        "capture_screen_frame",
        "enumerate_visible_windows",
        "extract_uia_element_tree",
        "get_monitor_dpi_scale",
        "normalize_to_grid_1000",
        "denormalize_from_grid_1000",
        "annotate_som_elements",
        "ComputerUseSafetyAbort",
        "dispatch_gui_action",
        "compute_frame_dhash64",
        "compute_visual_hamming_delta",
        "SafetyPolicy",
        "VisualActionOracle",
        "MCP_TOOLS",
        "handle_jsonrpc_request",
        "audit_git_repository",
    )
    for sym in expected_symbols:
        assert hasattr(agy_computer_use, sym), f"Missing top-level export: {sym}"


def test_capture_screen_frame_synthetic_determinism() -> None:
    """REQ-CU-001: Deterministic synthetic frame generation with identical seed."""
    from agy_computer_use.capture import capture_screen_frame

    frame_a = capture_screen_frame(width=320, height=200, synthetic_seed=42)
    frame_b = capture_screen_frame(width=320, height=200, synthetic_seed=42)
    frame_c = capture_screen_frame(width=320, height=200, synthetic_seed=99)

    assert frame_a["width"] == 320
    assert frame_a["height"] == 200
    assert frame_a["backend"] == "synthetic"
    assert isinstance(frame_a["rgb_bytes"], bytes)
    assert len(frame_a["rgb_bytes"]) == 320 * 200 * 3
    assert frame_a["rgb_bytes"] == frame_b["rgb_bytes"]
    assert frame_a["sha256"] == frame_b["sha256"]
    assert frame_a["sha256"] == hashlib.sha256(frame_a["rgb_bytes"]).hexdigest()
    assert frame_a["sha256"] != frame_c["sha256"]
    assert isinstance(frame_a["timestamp"], float) and frame_a["timestamp"] > 0.0


def test_capture_screen_frame_bmp_and_png_magic_bytes() -> None:
    """REQ-CU-001: Verify BMP and PNG container encodings and magic signatures."""
    from agy_computer_use.capture import capture_screen_frame

    frame = capture_screen_frame(width=128, height=96, synthetic_seed=101)
    bmp_bytes = frame["bmp_bytes"]
    png_bytes = frame["png_bytes"]

    assert isinstance(bmp_bytes, bytes)
    assert bmp_bytes.startswith(b"BM")
    assert len(bmp_bytes) >= 54 + (128 * 96 * 3)

    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in png_bytes
    assert b"IDAT" in png_bytes
    assert b"IEND" in png_bytes


def test_capture_screen_frame_region_cropping() -> None:
    """REQ-CU-001: Verify region capture honors bounding box geometry."""
    from agy_computer_use.capture import capture_screen_frame

    frame = capture_screen_frame(
        region=(0, 0, 160, 120),
        width=160,
        height=120,
        synthetic_seed=7,
    )
    assert frame["width"] == 160
    assert frame["height"] == 120
    assert len(frame["rgb_bytes"]) == 160 * 120 * 3
    assert frame["bmp_bytes"].startswith(b"BM")
    assert frame["png_bytes"].startswith(b"\x89PNG\r\n\x1a\n")


def test_capture_screen_frame_live_or_headless_fallback() -> None:
    """REQ-CU-001: Live Win32 GDI capture (or synthetic fallback if headless)."""
    from agy_computer_use.capture import capture_screen_frame

    frame = capture_screen_frame(width=256, height=144, synthetic_seed=None)
    assert frame["backend"] in ("win32_gdi", "synthetic")
    assert frame["width"] > 0
    assert frame["height"] > 0
    assert len(frame["rgb_bytes"]) == frame["width"] * frame["height"] * 3
    assert frame["bmp_bytes"].startswith(b"BM")
    assert frame["png_bytes"].startswith(b"\x89PNG\r\n\x1a\n")
    assert len(frame["sha256"]) == 64


def test_enumerate_visible_windows_contract() -> None:
    """REQ-CU-001: Enumerate visible top-level windows with complete metadata."""
    from agy_computer_use.capture import enumerate_visible_windows

    windows = enumerate_visible_windows(include_minimized=False)
    assert isinstance(windows, list)
    assert len(windows) >= 1

    required_keys = {
        "hwnd",
        "title",
        "class_name",
        "bbox_px",
        "width",
        "height",
        "is_visible",
        "pid",
    }
    for win in windows:
        assert required_keys.issubset(set(win.keys()))
        assert isinstance(win["hwnd"], int)
        assert isinstance(win["title"], str)
        assert isinstance(win["class_name"], str)
        assert isinstance(win["bbox_px"], tuple) and len(win["bbox_px"]) == 4
        assert isinstance(win["width"], int) and win["width"] >= 0
        assert isinstance(win["height"], int) and win["height"] >= 0
        assert isinstance(win["is_visible"], bool)
        assert isinstance(win["pid"], int)


def test_enumerate_visible_windows_include_minimized() -> None:
    """REQ-CU-001: Verify include_minimized flag returns at least as many windows."""
    from agy_computer_use.capture import enumerate_visible_windows

    visible_only = enumerate_visible_windows(include_minimized=False)
    with_minimized = enumerate_visible_windows(include_minimized=True)
    assert isinstance(with_minimized, list)
    assert len(with_minimized) >= len(visible_only)


def test_extract_uia_element_tree_default_and_limit() -> None:
    """REQ-CU-001: Extract interactive UIA element tree respecting max_elements."""
    from agy_computer_use.capture import extract_uia_element_tree

    elements = extract_uia_element_tree(hwnd=None, max_elements=12)
    assert isinstance(elements, list)
    assert 1 <= len(elements) <= 12

    allowed_types = {"button", "edit", "menuitem", "window", "control"}
    required_keys = {
        "element_id",
        "hwnd",
        "title",
        "class_name",
        "control_type",
        "bbox_px",
        "is_enabled",
    }
    for el in elements:
        assert required_keys.issubset(set(el.keys()))
        assert isinstance(el["element_id"], str) and len(el["element_id"]) > 0
        assert isinstance(el["hwnd"], int)
        assert isinstance(el["title"], str)
        assert isinstance(el["class_name"], str)
        assert el["control_type"] in allowed_types
        assert isinstance(el["bbox_px"], tuple) and len(el["bbox_px"]) == 4
        left, top, right, bottom = el["bbox_px"]
        assert right >= left
        assert bottom >= top
        assert isinstance(el["is_enabled"], bool)


def test_extract_uia_element_tree_for_specific_hwnd() -> None:
    """REQ-CU-001: Extract UIA elements scoped to a specific window handle."""
    from agy_computer_use.capture import enumerate_visible_windows, extract_uia_element_tree

    windows = enumerate_visible_windows(include_minimized=False)
    target_hwnd = windows[0]["hwnd"]
    elements = extract_uia_element_tree(hwnd=target_hwnd, max_elements=8)
    assert isinstance(elements, list)
    assert 1 <= len(elements) <= 8
    for el in elements:
        assert "bbox_px" in el
        assert "control_type" in el


def test_get_monitor_dpi_scale_range() -> None:
    """REQ-CU-002: Verify monitor DPI scale factor lies within [0.5, 4.0]."""
    from agy_computer_use.som import get_monitor_dpi_scale

    scale_default = get_monitor_dpi_scale()
    scale_hwnd = get_monitor_dpi_scale(hwnd=0)
    assert isinstance(scale_default, float)
    assert 0.5 <= scale_default <= 4.0
    assert isinstance(scale_hwnd, float)
    assert 0.5 <= scale_hwnd <= 4.0


def test_normalize_to_grid_1000_cardinal_points_and_clamping() -> None:
    """REQ-CU-002: Verify [0, 1000] grid mapping and out-of-bounds clamping."""
    from agy_computer_use.som import normalize_to_grid_1000

    assert normalize_to_grid_1000(0, 0, 1920, 1080) == (0, 0)
    assert normalize_to_grid_1000(960, 540, 1920, 1080) == (500, 500)
    assert normalize_to_grid_1000(1920, 1080, 1920, 1080) == (1000, 1000)

    # Clamping outside screen boundaries
    assert normalize_to_grid_1000(-250, -100, 1920, 1080) == (0, 0)
    assert normalize_to_grid_1000(3000, 2000, 1920, 1080) == (1000, 1000)

    # Multi-monitor negative origin offset
    assert normalize_to_grid_1000(
        -960, 540, screen_width=1920, screen_height=1080, origin_x=-1920, origin_y=0
    ) == (500, 500)


def test_normalize_to_grid_1000_invalid_dimensions_raise() -> None:
    """REQ-CU-002: Verify ValueError on non-positive screen width or height."""
    from agy_computer_use.som import normalize_to_grid_1000

    with pytest.raises(ValueError):
        normalize_to_grid_1000(100, 100, screen_width=0, screen_height=1080)

    with pytest.raises(ValueError):
        normalize_to_grid_1000(100, 100, screen_width=1920, screen_height=-5)


def test_denormalize_from_grid_1000_cardinal_points_and_dpi() -> None:
    """REQ-CU-002: Verify denormalization from [0, 1000] back to physical pixels."""
    from agy_computer_use.som import denormalize_from_grid_1000

    assert denormalize_from_grid_1000(0, 0, 1920, 1080) == (0, 0)
    assert denormalize_from_grid_1000(500, 500, 1920, 1080) == (960, 540)
    assert denormalize_from_grid_1000(1000, 1000, 1920, 1080) == (1920, 1080)

    # Multi-monitor negative origin offset
    px_x, px_y = denormalize_from_grid_1000(
        500, 500, screen_width=1920, screen_height=1080, origin_x=-1920, origin_y=0
    )
    assert px_x == -960
    assert px_y == 540

    # DPI scaling factor
    scaled_x, scaled_y = denormalize_from_grid_1000(
        500, 500, screen_width=1920, screen_height=1080, dpi_scale=1.5
    )
    assert isinstance(scaled_x, int) and isinstance(scaled_y, int)
    assert scaled_x != 960


def test_denormalize_from_grid_1000_invalid_arguments_raise() -> None:
    """REQ-CU-002: Verify ValueError when normalized coords or dimensions are invalid."""
    from agy_computer_use.som import denormalize_from_grid_1000

    with pytest.raises(ValueError):
        denormalize_from_grid_1000(-1, 500, 1920, 1080)

    with pytest.raises(ValueError):
        denormalize_from_grid_1000(500, 1001, 1920, 1080)

    with pytest.raises(ValueError):
        denormalize_from_grid_1000(500, 500, 0, 1080)

    with pytest.raises(ValueError):
        denormalize_from_grid_1000(500, 500, 1920, 0)

    with pytest.raises(ValueError):
        denormalize_from_grid_1000(500, 500, 1920, 1080, dpi_scale=0.0)

    with pytest.raises(ValueError):
        denormalize_from_grid_1000(500, 500, 1920, 1080, dpi_scale=-1.25)


def test_annotate_som_elements_renders_overlay_and_mark_catalog() -> None:
    """REQ-CU-002: Verify Set-of-Marks (SoM) bounding box rendering and 1..N mark catalog."""
    from agy_computer_use.capture import capture_screen_frame
    from agy_computer_use.som import annotate_som_elements

    frame = capture_screen_frame(width=400, height=300, synthetic_seed=55)
    sample_elements = [
        {
            "element_id": "btn-submit",
            "hwnd": 1001,
            "title": "Submit Order",
            "class_name": "Button",
            "control_type": "button",
            "bbox_px": (40, 30, 160, 90),
            "is_enabled": True,
        },
        {
            "element_id": "edit-query",
            "hwnd": 1002,
            "title": "Search Input",
            "class_name": "Edit",
            "control_type": "edit",
            "bbox_px": (200, 120, 360, 180),
            "is_enabled": True,
        },
    ]

    result = annotate_som_elements(frame, sample_elements)
    assert result["mark_count"] == 2
    assert isinstance(result["annotated_rgb_bytes"], bytes)
    assert len(result["annotated_rgb_bytes"]) == 400 * 300 * 3
    assert result["annotated_rgb_bytes"] != frame["rgb_bytes"]
    assert result["annotated_png_bytes"].startswith(b"\x89PNG\r\n\x1a\n")

    marks = result["marks"]
    assert set(marks.keys()) == {1, 2}
    m1 = marks[1]
    assert m1["mark_id"] == 1
    assert m1["title"] == "Submit Order"
    assert m1["class_name"] == "Button"
    assert m1["control_type"] == "button"
    assert m1["bbox_px"] == (40, 30, 160, 90)
    assert m1["center_px"] == (100, 60)
    assert m1["center_1000"] == (250, 200)

    m2 = marks[2]
    assert m2["mark_id"] == 2
    assert m2["center_px"] == (280, 150)
    assert m2["center_1000"] == (700, 500)
