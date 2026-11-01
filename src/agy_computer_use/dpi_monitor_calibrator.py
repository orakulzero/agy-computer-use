"""Per-Monitor DPI Scaling & Multi-Display Coordinate Calibrator (REQ-CU-DPI-01).

Preserves the [0, 1000] x [0, 1000] normalized coordinate grid across arbitrary
multi-monitor topologies (including negative virtual screen offsets) while
enforcing the (0, 0) origin fail-safe abort invariant.
"""

from __future__ import annotations

from dataclasses import dataclass

STANDARD_WINDOWS_DPI: float = 96.0


@dataclass(frozen=True)
class MonitorGeometry:
    """Virtual screen bounding box and raw DPI for a display monitor (REQ-CU-DPI-01)."""

    monitor_id: str
    left: int
    top: int
    width: int
    height: int
    dpi: int = 96


class MultiMonitorDPICalibrator:
    """Calibrator for per-monitor DPI scaling and [0, 1000] virtual screen mapping (REQ-CU-DPI-01)."""

    def calibrate_dpi_scale(self, raw_dpi: int | float) -> float:
        """Compute scaling factor relative to standard 96 DPI baseline (REQ-CU-DPI-01)."""
        if raw_dpi <= 0:
            raise ValueError(f"raw_dpi must be positive, got {raw_dpi} (REQ-CU-DPI-01)")
        return float(raw_dpi) / STANDARD_WINDOWS_DPI

    def map_normalized_to_virtual_screen(
        self,
        norm_x: int | float,
        norm_y: int | float,
        monitor: MonitorGeometry,
    ) -> tuple[int, int]:
        """Map [0, 1000] normalized coordinates onto a monitor's virtual screen rect (REQ-CU-DPI-01)."""
        if float(norm_x) == 0.0 and float(norm_y) == 0.0:
            raise ValueError("Fail-safe abort triggered at origin (0, 0) (REQ-CU-DPI-01)")
        if monitor.width <= 0 or monitor.height <= 0:
            raise ValueError(f"Invalid monitor dimensions for {monitor.monitor_id!r} (REQ-CU-DPI-01)")

        clamped_x = max(0.0, min(1000.0, float(norm_x)))
        clamped_y = max(0.0, min(1000.0, float(norm_y)))

        vx = monitor.left + round((clamped_x / 1000.0) * monitor.width)
        vy = monitor.top + round((clamped_y / 1000.0) * monitor.height)
        return (int(vx), int(vy))

    def compensate_scaling_drift(
        self,
        logical_x: int | float,
        logical_y: int | float,
        dpi_scale: float,
    ) -> tuple[int, int]:
        """Convert logical coordinates into physical pixels using the monitor DPI scale (REQ-CU-DPI-01)."""
        if dpi_scale <= 0:
            raise ValueError(f"dpi_scale must be positive, got {dpi_scale} (REQ-CU-DPI-01)")
        phys_x = round(float(logical_x) * float(dpi_scale))
        phys_y = round(float(logical_y) * float(dpi_scale))
        return (int(phys_x), int(phys_y))

    def physical_to_normalized(
        self,
        phys_x: int | float,
        phys_y: int | float,
        monitor: MonitorGeometry,
    ) -> tuple[int, int]:
        """Convert physical virtual-screen coordinates into clamped [0, 1000] grid coordinates (REQ-CU-DPI-01)."""
        if monitor.width <= 0 or monitor.height <= 0:
            raise ValueError(f"Invalid monitor dimensions for {monitor.monitor_id!r} (REQ-CU-DPI-01)")
        rel_x = ((float(phys_x) - float(monitor.left)) / float(monitor.width)) * 1000.0
        rel_y = ((float(phys_y) - float(monitor.top)) / float(monitor.height)) * 1000.0
        nx = max(0, min(1000, round(rel_x)))
        ny = max(0, min(1000, round(rel_y)))
        return (int(nx), int(ny))
