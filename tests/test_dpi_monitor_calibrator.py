"""Locked Agile V verification suite for Multi-Monitor DPI Coordinate Calibrator.

Requirement Traceability:
- REQ-CU-DPI-01: Per-Monitor DPI Scaling & Multi-Display Virtual Screen Coordinate
  Calibrator preserving [0, 1000] x [0, 1000] normalized space and (0, 0) fail-safe
  abort invariant.

Hygiene: 100% English-only (0 Cyrillic characters).
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agy_computer_use.dpi_monitor_calibrator import (  # noqa: E402
    MonitorGeometry,
    MultiMonitorDPICalibrator,
)


def test_calibrate_dpi_scale_standard_factors() -> None:
    """Verify standard Windows DPI values map to exact scaling factors (REQ-CU-DPI-01)."""
    cal = MultiMonitorDPICalibrator()
    assert cal.calibrate_dpi_scale(raw_dpi=96) == pytest.approx(1.0)
    assert cal.calibrate_dpi_scale(raw_dpi=120) == pytest.approx(1.25)
    assert cal.calibrate_dpi_scale(raw_dpi=144) == pytest.approx(1.5)
    assert cal.calibrate_dpi_scale(raw_dpi=192) == pytest.approx(2.0)


def test_origin_zero_zero_failsafe_abort_strictly_preserved() -> None:
    """Verify (0, 0) raises Fail-safe abort across any monitor geometry or DPI scale (REQ-CU-DPI-01)."""
    cal = MultiMonitorDPICalibrator()
    monitors = [
        MonitorGeometry(monitor_id="mon_primary", left=0, top=0, width=1920, height=1080, dpi=96),
        MonitorGeometry(monitor_id="mon_left_4k", left=-3840, top=-2160, width=3840, height=2160, dpi=192),
    ]
    for mon in monitors:
        with pytest.raises((RuntimeError, ValueError), match=r"(?i)fail-safe abort"):
            cal.map_normalized_to_virtual_screen(0, 0, mon)


def test_multi_monitor_negative_offset_virtual_screen_mapping() -> None:
    """Verify secondary left monitor with negative virtual offset maps (500, 500) to (-960, 540) (REQ-CU-DPI-01)."""
    cal = MultiMonitorDPICalibrator()
    mon_left = MonitorGeometry(
        monitor_id="mon_left",
        left=-1920,
        top=0,
        width=1920,
        height=1080,
        dpi=144,
    )
    vx, vy = cal.map_normalized_to_virtual_screen(500, 500, mon_left)
    assert (vx, vy) == (-960, 540)


def test_compensate_scaling_drift_between_logical_and_physical_pixels() -> None:
    """Verify logical-to-physical DPI drift compensation and inverse normalized clamping (REQ-CU-DPI-01)."""
    cal = MultiMonitorDPICalibrator()
    phys_x, phys_y = cal.compensate_scaling_drift(logical_x=400, logical_y=300, dpi_scale=1.5)
    assert (phys_x, phys_y) == (600, 450)

    mon = MonitorGeometry(monitor_id="mon_primary", left=0, top=0, width=1920, height=1080, dpi=144)
    nx, ny = cal.physical_to_normalized(960, 540, mon)
    assert (nx, ny) == (500, 500)

    nx_out, ny_out = cal.physical_to_normalized(2500, -300, mon)
    assert 0 <= nx_out <= 1000
    assert 0 <= ny_out <= 1000


def test_out_of_bounds_normalized_coordinates_clamped_to_0_1000() -> None:
    """Verify out-of-bounds normalized coordinates clamp safely within monitor bounds (REQ-CU-DPI-01)."""
    cal = MultiMonitorDPICalibrator()
    mon = MonitorGeometry(
        monitor_id="mon_right",
        left=1920,
        top=0,
        width=1920,
        height=1080,
        dpi=120,
    )
    vx, vy = cal.map_normalized_to_virtual_screen(1250, -50, mon)
    assert mon.left <= vx <= mon.left + mon.width
    assert mon.top <= vy <= mon.top + mon.height
    assert vx == 3840
    assert vy == 0


def test_req_cu_dpi_01_traceability_and_english_hygiene() -> None:
    """Verify REQ-CU-DPI-01 tag and 0 Cyrillic characters in implementation and tests (REQ-CU-DPI-01)."""
    impl_path = SRC_DIR / "agy_computer_use" / "dpi_monitor_calibrator.py"
    assert impl_path.is_file(), f"Implementation file missing: {impl_path}"
    impl_text = impl_path.read_text(encoding="utf-8")
    test_text = Path(__file__).read_text(encoding="utf-8")

    assert "REQ-CU-DPI-01" in impl_text
    assert re.search(r"[\u0400-\u04FF]", impl_text) is None
    assert re.search(r"[\u0400-\u04FF]", test_text) is None
