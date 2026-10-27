"""Antigravity Computer Use & GUI Grounding Station (v2.0.0).

Provides Win32 GDI screen capture, UIA control tree extraction, Set-of-Marks (SoM)
visual grounding, [0, 1000] coordinate normalization, Win32 SendInput synthesis,
64-bit dHash perceptual safety oracle, RFC 6962 Merkle audit trail, and MCP server.
"""

from __future__ import annotations

from agy_computer_use.actions import (
    SUPPORTED_ACTION_TYPES,
    ComputerUseSafetyAbort,
    clipboard_paste_text,
    dispatch_gui_action,
)
from agy_computer_use.background import (
    PW_RENDERFULLCONTENT,
    GhostDesktopSession,
    capture_window_background,
    dispatch_background_window_action,
    restore_window_onscreen,
    stage_window_offscreen,
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
    DEFAULT_PROMPT_INJECTION_PATTERNS,
    SafetyPolicy,
    VisualActionOracle,
    compute_frame_dhash64,
    compute_visual_hamming_delta,
    detect_ui_prompt_injection,
    wrap_untrusted_ui_evidence,
)
from agy_computer_use.som import (
    annotate_som_elements,
    denormalize_from_grid_1000,
    get_monitor_dpi_scale,
    normalize_to_grid_1000,
)
from agy_computer_use.recorder import (
    TrajectoryRecorder,
    replay_recorded_trajectory,
)
from agy_computer_use.template_matcher import (
    compute_integral_image,
    find_visual_anchor_on_screen,
)
from agy_computer_use.topology import (
    enumerate_display_monitors,
    map_monitor_grid_1000_to_virtual,
    map_virtual_to_monitor_grid_1000,
)
from agy_computer_use.window_session import (
    WDA_EXCLUDEFROMCAPTURE,
    WDA_NONE,
    CompactionImageBudget,
    InterruptionMonitor,
    WindowSessionManager,
    apply_exclude_from_capture,
    diff_uia_trees,
    format_uia_tree_text,
    synthesize_bezier_cursor_path,
)


__version__ = "2.0.0"

__all__ = [
    "__version__",
    "DEFAULT_PROMPT_INJECTION_PATTERNS",
    "MCP_TOOLS",
    "PW_RENDERFULLCONTENT",
    "SUPPORTED_ACTION_TYPES",
    "TrajectoryRecorder",
    "WDA_EXCLUDEFROMCAPTURE",
    "WDA_NONE",
    "CompactionImageBudget",
    "ComputerUseSafetyAbort",
    "GhostDesktopSession",
    "InterruptionMonitor",
    "SafetyPolicy",
    "VisualActionOracle",
    "WindowSessionManager",
    "annotate_som_elements",
    "apply_exclude_from_capture",
    "audit_git_repository",
    "capture_screen_frame",
    "capture_window_background",
    "clipboard_paste_text",
    "compute_frame_dhash64",
    "compute_integral_image",
    "compute_visual_hamming_delta",
    "denormalize_from_grid_1000",
    "detect_ui_prompt_injection",
    "diff_uia_trees",
    "dispatch_background_window_action",
    "dispatch_gui_action",
    "encode_rgb_to_bmp",
    "encode_rgb_to_png",
    "enumerate_display_monitors",
    "enumerate_visible_windows",
    "extract_uia_element_tree",
    "find_visual_anchor_on_screen",
    "format_uia_tree_text",
    "get_monitor_dpi_scale",
    "handle_jsonrpc_request",
    "map_monitor_grid_1000_to_virtual",
    "map_virtual_to_monitor_grid_1000",
    "normalize_to_grid_1000",
    "replay_recorded_trajectory",
    "restore_window_onscreen",
    "run_stdio_server",
    "stage_window_offscreen",
    "synthesize_bezier_cursor_path",
    "validate_plugin_bundle",
    "wrap_untrusted_ui_evidence",
]

