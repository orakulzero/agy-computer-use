"""Command-Line Interface for Antigravity Computer Use & GUI Grounding (v1.1.0).

Supports subcommands:
- capture: Capture desktop frame and render Set-of-Marks (SoM) metadata
- windows: Enumerate visible top-level windows
- audit: Run 5-Gate open-source hygiene & plugin bundle validation
- mcp: Launch stdio MCP JSON-RPC 2.0 server
- bg-capture: Non-intrusive background window capture via PrintWindow
- bg-dispatch: Focusless background input message dispatch via PostMessageW
- ghost-desktop: Manage isolated WinSta0\\AGY_GhostDesktop session and processes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from collections.abc import Sequence

from agy_computer_use.background import (
    GhostDesktopSession,
    capture_window_background,
    dispatch_background_window_action,
)
from agy_computer_use.capture import (
    capture_screen_frame,
    enumerate_visible_windows,
    extract_uia_element_tree,
)
from agy_computer_use.mcp_server import MCP_TOOLS, run_stdio_server
from agy_computer_use.oss_audit import audit_git_repository
from agy_computer_use.som import annotate_som_elements, get_monitor_dpi_scale


def _resolve_hwnd(hwnd: int, title: str | None = None) -> tuple[int, str]:
    """Resolve target HWND from integer handle or window title substring."""
    if hwnd != 0:
        return hwnd, ""
    if title:
        wins = enumerate_visible_windows(include_minimized=True)
        t_low = title.lower()
        for w in wins:
            if t_low in str(w.get("title", "")).lower():
                return int(w["hwnd"]), str(w.get("title", ""))
    return hwnd, title or ""


def build_parser() -> argparse.ArgumentParser:
    """REQ-CU-006: Build CLI argument parser with capture, windows, audit, mcp, and background subcommands."""
    parser = argparse.ArgumentParser(
        prog="agy-computer-use",
        description="Antigravity Computer Use & GUI Grounding CLI (v1.1.0)",
    )
    parser.add_argument("--version", action="store_true", help="Print package version and exit.")
    subparsers = parser.add_subparsers(dest="command")

    cap_p = subparsers.add_parser("capture", help="Capture screen frame and SoM overlay.")
    cap_p.add_argument("--width", type=int, default=320)
    cap_p.add_argument("--height", type=int, default=200)
    cap_p.add_argument("--seed", type=int, default=None)
    cap_p.add_argument("--max-elements", type=int, default=16)

    win_p = subparsers.add_parser("windows", help="List visible top-level windows.")
    win_p.add_argument("--include-minimized", action="store_true")

    aud_p = subparsers.add_parser("audit", help="Run 5-Gate OSS hygiene and plugin audit.")
    aud_p.add_argument("--path", type=str, default=".")

    subparsers.add_parser("mcp", help="Run stdio MCP JSON-RPC 2.0 server.")

    bg_cap = subparsers.add_parser(
        "bg-capture",
        help="Capture background window via PrintWindow(PW_RENDERFULLCONTENT).",
    )
    bg_cap.add_argument("--hwnd", type=int, default=0, help="Target window handle (HWND).")
    bg_cap.add_argument("--title", type=str, default=None, help="Target window title substring.")
    bg_cap.add_argument("--desktop", type=str, default="Default", help="Desktop session name.")
    bg_cap.add_argument("--width", type=int, default=320, help="Fallback frame width.")
    bg_cap.add_argument("--height", type=int, default=200, help="Fallback frame height.")
    bg_cap.add_argument("--seed", type=int, default=None, help="Fallback synthetic seed.")
    bg_cap.add_argument("--output", type=str, default=None, help="Optional output PNG file path.")

    bg_disp = subparsers.add_parser(
        "bg-dispatch",
        help="Dispatch focusless input actions via PostMessageW without focus theft.",
    )
    bg_disp.add_argument("--hwnd", type=int, default=0, help="Target window handle (HWND).")
    bg_disp.add_argument("--title", type=str, default=None, help="Target window title substring.")
    bg_disp.add_argument(
        "--action",
        type=str,
        default="click",
        choices=["click", "double_click", "right_click", "move", "drag", "scroll", "type_text", "wm_settext"],
        help="Action type to dispatch.",
    )
    bg_disp.add_argument("--norm-x", type=int, default=500, help="X on [0..1000] grid.")
    bg_disp.add_argument("--norm-y", type=int, default=500, help="Y on [0..1000] grid.")
    bg_disp.add_argument("--end-norm-x", type=int, default=None, help="End X on [0..1000] grid for drag.")
    bg_disp.add_argument("--end-norm-y", type=int, default=None, help="End Y on [0..1000] grid for drag.")
    bg_disp.add_argument("--text", type=str, default="", help="Text to type or set.")
    bg_disp.add_argument("--wheel-delta", type=int, default=-120, help="Scroll wheel delta.")
    bg_disp.add_argument("--drag-steps", type=int, default=16, help="Intermediate drag steps.")
    bg_disp.add_argument("--desktop", type=str, default="Default", help="Desktop session name.")
    bg_disp.add_argument("--dry-run", action="store_true", default=False, help="Synthesize without OS dispatch.")

    ghost_p = subparsers.add_parser(
        "ghost-desktop",
        help="Manage isolated WinSta0\\AGY_GhostDesktop session.",
    )
    ghost_p.add_argument(
        "--action",
        type=str,
        default="launch",
        choices=["launch", "windows", "enumerate", "capture", "dispatch", "close", "create"],
        help="Ghost desktop action.",
    )
    ghost_p.add_argument("--name", type=str, default="AGY_GhostDesktop", help="Desktop session name.")
    ghost_p.add_argument("--cmd", type=str, default="notepad.exe", help="Command line to launch.")
    ghost_p.add_argument("--hwnd", type=int, default=0, help="Target window handle on ghost desktop.")
    ghost_p.add_argument("--act-type", type=str, default="click", help="Action type for dispatch.")
    ghost_p.add_argument("--norm-x", type=int, default=500, help="X on [0..1000] grid.")
    ghost_p.add_argument("--norm-y", type=int, default=500, help="Y on [0..1000] grid.")
    ghost_p.add_argument("--end-norm-x", type=int, default=None, help="End X on [0..1000] grid.")
    ghost_p.add_argument("--end-norm-y", type=int, default=None, help="End Y on [0..1000] grid.")
    ghost_p.add_argument("--text", type=str, default="", help="Text to type or set.")
    ghost_p.add_argument("--wait", type=float, default=2.0, help="Seconds to wait for window after launch.")
    ghost_p.add_argument("--seed", type=int, default=202, help="Fallback synthetic seed.")
    ghost_p.add_argument("--dry-run", action="store_true", default=False, help="Synthesize without OS dispatch.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """REQ-CU-006: Execute CLI entry point and return POSIX exit code."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.version:
        sys.stdout.write("agy-computer-use 1.1.0\n")
        return 0

    if args.command == "capture":
        frame = capture_screen_frame(
            width=args.width,
            height=args.height,
            synthetic_seed=args.seed,
        )
        elements = extract_uia_element_tree(max_elements=args.max_elements)
        som = annotate_som_elements(frame, elements)
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "backend": frame["backend"],
                    "width": frame["width"],
                    "height": frame["height"],
                    "sha256": frame["sha256"],
                    "dpi_scale": get_monitor_dpi_scale(),
                    "mark_count": som["mark_count"],
                },
                indent=2,
            )
            + "\n"
        )
        return 0

    if args.command == "windows":
        wins = enumerate_visible_windows(include_minimized=bool(args.include_minimized))
        sys.stdout.write(json.dumps({"count": len(wins), "windows": wins}, indent=2) + "\n")
        return 0

    if args.command == "audit":
        target = Path(args.path).resolve()
        report = audit_git_repository(target)
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
        return 0 if report["passed"] else 1

    if args.command == "mcp":
        return run_stdio_server()

    if args.command == "bg-capture":
        target_hwnd, resolved_title = _resolve_hwnd(args.hwnd, args.title)
        frame = capture_window_background(
            target_hwnd,
            desktop_name=args.desktop,
            fallback_seed=args.seed if args.seed is not None else 101,
            fallback_width=args.width,
            fallback_height=args.height,
        )
        if args.output:
            out_p = Path(args.output).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_bytes(frame["png_bytes"])
        payload = {
            "ok": True,
            "hwnd": target_hwnd,
            "title": resolved_title,
            "width": frame["width"],
            "height": frame["height"],
            "backend": frame["backend"],
            "sha256": frame["sha256"],
            "dhash64": frame["dhash64"],
            "desktop": frame["desktop_name"],
            "output_saved": str(args.output) if args.output else None,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0

    if args.command == "bg-dispatch":
        target_hwnd, _ = _resolve_hwnd(args.hwnd, args.title)
        res = dispatch_background_window_action(
            target_hwnd,
            args.action,
            norm_x=args.norm_x,
            norm_y=args.norm_y,
            end_norm_x=args.end_norm_x,
            end_norm_y=args.end_norm_y,
            text=args.text,
            wheel_delta=args.wheel_delta,
            drag_steps=args.drag_steps,
            desktop_name=args.desktop,
            dry_run=args.dry_run,
        )
        sys.stdout.write(json.dumps(res, indent=2) + "\n")
        return 0 if res.get("dispatched") else 1

    if args.command == "ghost-desktop":
        session = GhostDesktopSession(args.name)
        action = args.action.lower()
        if action in ("create", "open"):
            sys.stdout.write(
                json.dumps({"ok": True, "action": "create", "desktop": f"WinSta0\\{args.name}"}, indent=2) + "\n"
            )
            return 0
        if action == "launch":
            res = session.launch_process(args.cmd, wait_for_window_sec=args.wait)
            sys.stdout.write(json.dumps({"ok": True, "action": "launch", **res}, indent=2) + "\n")
            return 0
        if action in ("windows", "enumerate"):
            wins = session.enumerate_windows()
            sys.stdout.write(
                json.dumps(
                    {
                        "ok": True,
                        "action": "windows",
                        "desktop": f"WinSta0\\{args.name}",
                        "count": len(wins),
                        "windows": wins,
                    },
                    indent=2,
                )
                + "\n"
            )
            return 0
        if action == "capture":
            cap = session.capture_window(args.hwnd, fallback_seed=args.seed)
            sys.stdout.write(
                json.dumps(
                    {
                        "ok": True,
                        "action": "capture",
                        "hwnd": args.hwnd,
                        "width": cap["width"],
                        "height": cap["height"],
                        "backend": cap["backend"],
                        "sha256": cap["sha256"],
                        "dhash64": cap["dhash64"],
                        "desktop": cap["desktop_name"],
                    },
                    indent=2,
                )
                + "\n"
            )
            return 0
        if action == "dispatch":
            disp = session.dispatch_action(
                args.hwnd,
                args.act_type,
                norm_x=args.norm_x,
                norm_y=args.norm_y,
                end_norm_x=args.end_norm_x,
                end_norm_y=args.end_norm_y,
                text=args.text,
                wheel_delta=args.wheel_delta,
                dry_run=args.dry_run,
            )
            sys.stdout.write(json.dumps({"ok": True, "action": "dispatch", **disp}, indent=2) + "\n")
            return 0 if disp.get("dispatched") else 1
        if action == "close":
            session.close()
            sys.stdout.write(
                json.dumps({"ok": True, "action": "close", "desktop": f"WinSta0\\{args.name}"}, indent=2) + "\n"
            )
            return 0

    status_payload = {
        "name": "agy-computer-use",
        "version": "1.1.0",
        "dpi_scale": get_monitor_dpi_scale(),
        "mcp_tools": [t["name"] for t in MCP_TOOLS],
        "status": "ready",
    }
    sys.stdout.write(json.dumps(status_payload) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
