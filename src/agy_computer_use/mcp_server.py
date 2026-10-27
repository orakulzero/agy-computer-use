"""MCP JSON-RPC 2.0 Stdio Server for Antigravity Computer Use & GUI Grounding.

Implements REQ-CU-005:
- 7 MCP tools with <=64-character composite identifiers:
  cu_capture_som, cu_click, cu_type, cu_hotkey, cu_scroll, cu_verify_oracle, cu_merkle_audit
- JSON-RPC 2.0 dispatch (initialize, ping, tools/list, tools/call)
- Stateful VisualActionOracle session tracking across tool calls
"""

from __future__ import annotations

import json
import sys
from typing import Any

from agy_computer_use.actions import dispatch_gui_action
from agy_computer_use.background import (
    capture_window_background,
    dispatch_background_window_action,
)
from agy_computer_use.capture import capture_screen_frame, extract_uia_element_tree
from agy_computer_use.safety_oracle import VisualActionOracle, wrap_untrusted_ui_evidence
from agy_computer_use.som import annotate_som_elements
from agy_computer_use.window_session import (
    WindowSessionManager,
    format_uia_tree_text,
    synthesize_bezier_cursor_path,
)

MCP_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "cu_capture_som",
        "description": "Capture screen frame, extract UIA controls, and render Set-of-Marks overlay.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Frame width in pixels."},
                "height": {"type": "integer", "description": "Frame height in pixels."},
                "max_elements": {"type": "integer", "description": "Max UIA elements."},
                "synthetic_seed": {"type": "integer", "description": "Optional seed."},
            },
        },
    },
    {
        "name": "cu_click",
        "description": "Dispatch mouse click, double_click, right_click, move, or drag on [0..1000] grid.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "description": "Pointer action type."},
                "norm_x": {"type": "integer", "description": "X on [0..1000] grid."},
                "norm_y": {"type": "integer", "description": "Y on [0..1000] grid."},
                "mark_id": {"type": "integer", "description": "Optional SoM mark ID."},
                "dry_run": {"type": "boolean", "description": "Synthesize without OS dispatch."},
            },
        },
    },
    {
        "name": "cu_type",
        "description": "Synthesize Unicode keyboard text entry via Win32 KEYEVENTF_UNICODE.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text string to type."},
                "dry_run": {"type": "boolean", "description": "Synthesize without OS dispatch."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "cu_hotkey",
        "description": "Dispatch multi-key chord sequence (e.g. ctrl+shift+s) or single key tap.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered key names.",
                },
                "dry_run": {"type": "boolean", "description": "Synthesize without OS dispatch."},
            },
            "required": ["keys"],
        },
    },
    {
        "name": "cu_scroll",
        "description": "Dispatch vertical mouse wheel scroll at [0..1000] normalized coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "norm_x": {"type": "integer", "description": "X on [0..1000] grid."},
                "norm_y": {"type": "integer", "description": "Y on [0..1000] grid."},
                "scroll_delta": {"type": "integer", "description": "Wheel delta (+/-120)."},
                "dry_run": {"type": "boolean", "description": "Synthesize without OS dispatch."},
            },
        },
    },
    {
        "name": "cu_verify_oracle",
        "description": "Verify visual frame delta via 64-bit dHash and record RFC 6962 Merkle receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "description": "Action type verified."},
                "norm_x": {"type": "integer", "description": "X on [0..1000] grid."},
                "norm_y": {"type": "integer", "description": "Y on [0..1000] grid."},
                "synthetic_seed_before": {"type": "integer", "description": "Pre-action seed."},
                "synthetic_seed_after": {"type": "integer", "description": "Post-action seed."},
                "target_title": {"type": "string", "description": "Target window title."},
            },
        },
    },
    {
        "name": "cu_merkle_audit",
        "description": "Retrieve RFC 6962 SHA-256 Merkle audit root, levels, and verified receipts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
)

_SESSION_ORACLE = VisualActionOracle()
_SESSION_MANAGER = WindowSessionManager()
_LAST_SOM_MARKS: dict[int, dict[str, Any]] = {}


def _wrap_tool_result(req_id: Any, payload: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "structuredContent": payload,
            "isError": is_error,
        },
    }


def handle_jsonrpc_request(request: dict[str, Any]) -> dict[str, Any]:
    """Process a single MCP JSON-RPC 2.0 request and return a response dictionary."""
    global _LAST_SOM_MARKS

    req_id = request.get("id")
    method = str(request.get("method", ""))
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "agy-computer-use", "version": "1.0.0"},
                "capabilities": {"tools": {"listChanged": False}},
            },
        }

    if method in ("ping", "notifications/initialized"):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"ok": True},
        }

    if method == "diagnostic_state":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": _SESSION_MANAGER.get_diagnostic_state(hwnd=params.get("hwnd")),
        }

    if method == "reset":
        _LAST_SOM_MARKS = {}
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": _SESSION_MANAGER.reset(),
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": list(MCP_TOOLS)},
        }

    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        args = params.get("arguments") or {}

        try:
            if tool_name == "cu_capture_som":
                width = int(args.get("width", 320))
                height = int(args.get("height", 200))
                max_el = int(args.get("max_elements", 16))
                seed = args.get("synthetic_seed")
                hwnd_arg = args.get("hwnd")
                if args.get("background") and hwnd_arg is not None:
                    bg_frame = capture_window_background(
                        int(hwnd_arg),
                        desktop_name=str(args.get("desktop_name", "Default")),
                        fallback_seed=int(seed) if seed is not None else 101,
                        fallback_width=width,
                        fallback_height=height,
                    )
                    return _wrap_tool_result(
                        req_id,
                        {
                            "ok": True,
                            "hwnd": int(hwnd_arg),
                            "width": bg_frame["width"],
                            "height": bg_frame["height"],
                            "backend": bg_frame["backend"],
                            "sha256": bg_frame["sha256"],
                            "dhash64": bg_frame["dhash64"],
                            "desktop_name": bg_frame["desktop_name"],
                        },
                    )
                state = _SESSION_MANAGER.get_window_state(
                    hwnd=int(hwnd_arg) if hwnd_arg is not None else None,
                    include_screenshot=True,
                    include_text=True,
                    max_elements=max_el,
                    width=width,
                    height=height,
                    synthetic_seed=int(seed) if seed is not None else None,
                )
                frame_info = state["frame"] or {}
                marks_dict = frame_info.get("marks") or {}
                _LAST_SOM_MARKS = marks_dict
                return _wrap_tool_result(
                    req_id,
                    {
                        "ok": True,
                        "width": frame_info.get("width", width),
                        "height": frame_info.get("height", height),
                        "backend": frame_info.get("backend", "synthetic"),
                        "sha256": frame_info.get("sha256", ""),
                        "screenshot_id": state["screenshot_id"],
                        "snapshot_revision": state["snapshot_revision"],
                        "accessibility_revision": state["accessibility_revision"],
                        "mark_count": frame_info.get("mark_count", len(marks_dict)),
                        "marks": {str(k): v for k, v in marks_dict.items()},
                        "uia_tree_text": state["text"],
                        "untrusted_evidence": state["untrusted_evidence"],
                    },
                )

            if tool_name == "cu_click":
                act = str(args.get("action_type", "click"))
                if args.get("background") and args.get("hwnd") is not None:
                    bg_res = dispatch_background_window_action(
                        int(args["hwnd"]),
                        act,
                        norm_x=args.get("norm_x", 500),
                        norm_y=args.get("norm_y", 500),
                        end_norm_x=args.get("end_norm_x"),
                        end_norm_y=args.get("end_norm_y"),
                        desktop_name=str(args.get("desktop_name", "Default")),
                        dry_run=bool(args.get("dry_run", True)),
                    )
                    return _wrap_tool_result(req_id, bg_res)
                screenshot_id = args.get("screenshot_id")
                res = dispatch_gui_action(
                    act,
                    norm_x=args.get("norm_x", 500),
                    norm_y=args.get("norm_y", 500),
                    mark_id=args.get("mark_id"),
                    marks_catalog=_LAST_SOM_MARKS if _LAST_SOM_MARKS else None,
                    dry_run=bool(args.get("dry_run", True)),
                    screenshot_id=str(screenshot_id) if screenshot_id else None,
                    session_manager=_SESSION_MANAGER if screenshot_id else None,
                )
                if args.get("smooth_path") and res.get("resolved_px") is not None:
                    res["bezier_path"] = synthesize_bezier_cursor_path(
                        (0, 0), res["resolved_px"], steps=8
                    )
                return _wrap_tool_result(req_id, res)

            if tool_name == "cu_type":
                res = dispatch_gui_action(
                    "type_text",
                    text=str(args.get("text", "")),
                    dry_run=bool(args.get("dry_run", True)),
                    use_clipboard=bool(args.get("use_clipboard", False)),
                )
                return _wrap_tool_result(req_id, res)

            if tool_name == "cu_hotkey":
                res = dispatch_gui_action(
                    "hotkey",
                    keys=list(args.get("keys") or ["enter"]),
                    dry_run=bool(args.get("dry_run", True)),
                )
                return _wrap_tool_result(req_id, res)

            if tool_name == "cu_scroll":
                screenshot_id = args.get("screenshot_id")
                res = dispatch_gui_action(
                    "scroll",
                    norm_x=int(args.get("norm_x", 500)),
                    norm_y=int(args.get("norm_y", 500)),
                    scroll_delta=int(args.get("scroll_delta", -120)),
                    dry_run=bool(args.get("dry_run", True)),
                    screenshot_id=str(screenshot_id) if screenshot_id else None,
                    session_manager=_SESSION_MANAGER if screenshot_id else None,
                )
                return _wrap_tool_result(req_id, res)

            if tool_name == "cu_verify_oracle":
                seed_b = args.get("synthetic_seed_before", 10)
                seed_a = args.get("synthetic_seed_after", 20)
                f_before = capture_screen_frame(
                    width=int(args.get("width", 160)),
                    height=int(args.get("height", 120)),
                    synthetic_seed=int(seed_b) if seed_b is not None else None,
                )
                f_after = capture_screen_frame(
                    width=int(args.get("width", 160)),
                    height=int(args.get("height", 120)),
                    synthetic_seed=int(seed_a) if seed_a is not None else None,
                )
                receipt = _SESSION_ORACLE.record_and_verify_action(
                    action_payload={
                        "action_type": str(args.get("action_type", "click")),
                        "norm_x": int(args.get("norm_x", 500)),
                        "norm_y": int(args.get("norm_y", 500)),
                    },
                    frame_before=f_before,
                    frame_after=f_after,
                    target_window={
                        "title": str(args.get("target_title", "Workstation Window")),
                        "class_name": str(args.get("target_class", "StandardWindow")),
                    },
                )
                return _wrap_tool_result(req_id, receipt)

            if tool_name == "cu_merkle_audit":
                summary = _SESSION_ORACLE.get_merkle_audit_summary()
                summary["cacheDiagnostics"] = _SESSION_MANAGER.get_diagnostic_state()[
                    "cacheDiagnostics"
                ]
                return _wrap_tool_result(req_id, summary)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown tool name: {tool_name}"},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown JSON-RPC method: {method}"},
    }


def run_stdio_server() -> int:
    """Run MCP JSON-RPC 2.0 server over standard input/output streams."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                continue
            resp = handle_jsonrpc_request(req)
            if req.get("id") is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_stdio_server())
