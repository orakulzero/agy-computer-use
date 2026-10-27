"""Antigravity Computer Use & GUI Grounding Station (v1.0.0).

Provides Win32 GDI screen capture, UIA control tree extraction, Set-of-Marks (SoM)
visual grounding, [0, 1000] coordinate normalization, Win32 SendInput synthesis,
64-bit dHash perceptual safety oracle, RFC 6962 Merkle audit trail, and MCP server.
"""

from __future__ import annotations

from agy_computer_use.actions import (
    SUPPORTED_ACTION_TYPES,
    ComputerUseSafetyAbort,
    dispatch_gui_action,
)
from agy_computer_use.capture import (
    capture_screen_frame,
    encode_rgb_to_bmp,
    encode_rgb_to_png,
    enumerate_visible_windows,
    extract_uia_element_tree,
)
from agy_computer_use.mcp_server import (
    MCP_TOOLS,
    handle_jsonrpc_request,
    run_stdio_server,
)
from agy_computer_use.oss_audit import (
    audit_git_repository,
    validate_plugin_bundle,
)
from agy_computer_use.safety_oracle import (
    SafetyPolicy,
    VisualActionOracle,
    compute_frame_dhash64,
    compute_visual_hamming_delta,
)
from agy_computer_use.som import (
    annotate_som_elements,
    denormalize_from_grid_1000,
    get_monitor_dpi_scale,
    normalize_to_grid_1000,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "MCP_TOOLS",
    "SUPPORTED_ACTION_TYPES",
    "ComputerUseSafetyAbort",
    "SafetyPolicy",
    "VisualActionOracle",
    "annotate_som_elements",
    "audit_git_repository",
    "capture_screen_frame",
    "compute_frame_dhash64",
    "compute_visual_hamming_delta",
    "denormalize_from_grid_1000",
    "dispatch_gui_action",
    "encode_rgb_to_bmp",
    "encode_rgb_to_png",
    "enumerate_visible_windows",
    "extract_uia_element_tree",
    "get_monitor_dpi_scale",
    "handle_jsonrpc_request",
    "normalize_to_grid_1000",
    "run_stdio_server",
    "validate_plugin_bundle",
]
