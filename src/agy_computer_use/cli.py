"""Command-Line Interface for Antigravity Computer Use & GUI Grounding.

Supports subcommands:
- capture: Capture desktop frame and render Set-of-Marks (SoM) metadata
- windows: Enumerate visible top-level windows
- audit: Run 5-Gate open-source hygiene & plugin bundle validation
- mcp: Launch stdio MCP JSON-RPC 2.0 server
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from agy_computer_use.capture import (
    capture_screen_frame,
    enumerate_visible_windows,
    extract_uia_element_tree,
)
from agy_computer_use.mcp_server import MCP_TOOLS, run_stdio_server
from agy_computer_use.oss_audit import audit_git_repository, validate_plugin_bundle
from agy_computer_use.som import annotate_som_elements, get_monitor_dpi_scale


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agy-computer-use",
        description="Antigravity Computer Use & GUI Grounding CLI (v1.0.0)",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute CLI entry point and return POSIX exit code."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.version:
        sys.stdout.write("agy-computer-use 1.0.0\n")
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

    status_payload = {
        "name": "agy-computer-use",
        "version": "1.0.0",
        "dpi_scale": get_monitor_dpi_scale(),
        "mcp_tools": [t["name"] for t in MCP_TOOLS],
        "status": "ready",
    }
    sys.stdout.write(json.dumps(status_payload) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
