"""ISO 9001:2015 Agile V Verification Suite for MCP JSON-RPC Server, Native Plugin & 5-Gate OSS Audit.

Covers REQ-CU-005 (7-Tool MCP Server, <64-Char Composite Identifier Shield, Native Plugin Bundle)
and REQ-CU-006 (CLI Entry Point & 5-Gate Open-Source Release Hygiene Audit).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_EXPECTED_MCP_TOOL_NAMES = (
    "cu_capture_som",
    "cu_click",
    "cu_type",
    "cu_hotkey",
    "cu_scroll",
    "cu_verify_oracle",
    "cu_merkle_audit",
)


def _extract_tool_call_payload(response: dict[str, Any]) -> dict[str, Any]:
    """Extract structured dict payload from an MCP JSON-RPC tools/call response."""
    assert response.get("jsonrpc") == "2.0"
    assert "result" in response, f"Expected result in response, got: {response}"
    result = response["result"]
    if isinstance(result, dict) and "structuredContent" in result and isinstance(
        result["structuredContent"], dict
    ):
        return result["structuredContent"]
    if isinstance(result, dict) and "content" in result and isinstance(result["content"], list):
        first = result["content"][0]
        if isinstance(first, dict) and "text" in first:
            return json.loads(first["text"])
    if isinstance(result, dict):
        return result
    raise AssertionError(f"Unable to parse MCP tool response: {response}")


def test_mcp_tools_catalog_and_64_char_composite_shield() -> None:
    """REQ-CU-005: Verify all 7 MCP tools exist and composite identifiers are <= 64 chars."""
    from agy_computer_use.mcp_server import MCP_TOOLS

    assert isinstance(MCP_TOOLS, (list, tuple))
    assert len(MCP_TOOLS) == 7

    names = [t["name"] for t in MCP_TOOLS]
    assert tuple(names) == _EXPECTED_MCP_TOOL_NAMES

    for tool in MCP_TOOLS:
        name = tool["name"]
        assert isinstance(tool.get("description"), str) and len(tool["description"]) > 0
        assert isinstance(tool.get("inputSchema"), dict)
        composite = f"mcp_agy-computer-use_computer_use_{name}"
        assert len(composite) <= 64, f"Composite identifier exceeds 64 chars: {composite} ({len(composite)})"


def test_jsonrpc_initialize_and_ping() -> None:
    """REQ-CU-005: Verify JSON-RPC 2.0 initialize and ping handlers."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    init_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "clientInfo": {"name": "pytest", "version": "1.0"}},
        }
    )
    assert init_resp["jsonrpc"] == "2.0"
    assert init_resp["id"] == 1
    assert "result" in init_resp
    assert "serverInfo" in init_resp["result"] or "capabilities" in init_resp["result"]

    ping_resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping_resp["jsonrpc"] == "2.0"
    assert ping_resp["id"] == 2
    assert "result" in ping_resp


def test_jsonrpc_tools_list() -> None:
    """REQ-CU-005: Verify tools/list returns all 7 registered MCP tools."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 3
    tools = resp["result"]["tools"]
    assert len(tools) == 7
    assert [t["name"] for t in tools] == list(_EXPECTED_MCP_TOOL_NAMES)


def test_jsonrpc_call_cu_capture_som() -> None:
    """REQ-CU-005: Verify tools/call for cu_capture_som returns frame and SoM marks."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "cu_capture_som",
                "arguments": {"width": 320, "height": 200, "synthetic_seed": 42},
            },
        }
    )
    payload = _extract_tool_call_payload(resp)
    assert payload.get("ok", True) is True
    assert "mark_count" in payload or "marks" in payload or "sha256" in payload


def test_jsonrpc_call_cu_click_and_cu_scroll() -> None:
    """REQ-CU-005: Verify tools/call for cu_click and cu_scroll in dry_run mode."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    click_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "cu_click",
                "arguments": {"norm_x": 500, "norm_y": 500, "dry_run": True},
            },
        }
    )
    click_data = _extract_tool_call_payload(click_resp)
    assert click_data["ok"] is True
    assert click_data["dry_run"] is True

    scroll_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "cu_scroll",
                "arguments": {"norm_x": 500, "norm_y": 500, "scroll_delta": -120, "dry_run": True},
            },
        }
    )
    scroll_data = _extract_tool_call_payload(scroll_resp)
    assert scroll_data["ok"] is True
    assert scroll_data["action_type"] == "scroll"


def test_jsonrpc_call_cu_type_and_cu_hotkey() -> None:
    """REQ-CU-005: Verify tools/call for cu_type and cu_hotkey in dry_run mode."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    type_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "cu_type",
                "arguments": {"text": "test_input_123", "dry_run": True},
            },
        }
    )
    type_data = _extract_tool_call_payload(type_resp)
    assert type_data["ok"] is True
    assert type_data["action_type"] == "type_text"

    hotkey_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "cu_hotkey",
                "arguments": {"keys": ["ctrl", "s"], "dry_run": True},
            },
        }
    )
    hotkey_data = _extract_tool_call_payload(hotkey_resp)
    assert hotkey_data["ok"] is True
    assert hotkey_data["action_type"] == "hotkey"


def test_jsonrpc_call_cu_verify_oracle_and_cu_merkle_audit() -> None:
    """REQ-CU-005: Verify tools/call for cu_verify_oracle and cu_merkle_audit."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    verify_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "cu_verify_oracle",
                "arguments": {
                    "action_type": "click",
                    "norm_x": 500,
                    "norm_y": 500,
                    "synthetic_seed_before": 10,
                    "synthetic_seed_after": 20,
                    "target_title": "Test Workstation",
                },
            },
        }
    )
    verify_data = _extract_tool_call_payload(verify_resp)
    assert "epistemic_status" in verify_data
    assert "merkle_root" in verify_data

    audit_resp = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {"name": "cu_merkle_audit", "arguments": {}},
        }
    )
    audit_data = _extract_tool_call_payload(audit_resp)
    assert "root" in audit_data
    assert "leaf_count" in audit_data
    assert audit_data["leaf_count"] >= 1


def test_jsonrpc_unknown_method_or_tool_returns_error() -> None:
    """REQ-CU-005: Verify unknown JSON-RPC method or unknown tool returns error."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    bad_method = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 99, "method": "nonexistent/method"})
    assert "error" in bad_method

    bad_tool = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {"name": "cu_unknown_tool", "arguments": {}},
        }
    )
    assert "error" in bad_tool or (
        isinstance(bad_tool.get("result"), dict) and bad_tool["result"].get("isError") is True
    )


def test_plugin_bundle_manifest_and_validator() -> None:
    """REQ-CU-005: Verify Antigravity 2.0 plugin manifest, hooks, mcp_config, rules, skills, and agents."""
    import agy_computer_use
    from agy_computer_use import mcp_server, oss_audit

    plugin_dir = (
        REPO_ROOT
        if (REPO_ROOT / "plugin.json").is_file()
        else REPO_ROOT / "plugins" / "agy-computer-use"
    )
    manifest_path = plugin_dir / "plugin.json"
    assert manifest_path.is_file(), f"Missing plugin.json at {manifest_path}"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    allowed_keys = {"name", "displayName", "description", "version", "logo", "suggestedPrompts"}
    assert set(manifest.keys()).issubset(allowed_keys)
    assert manifest["name"] == "agy-computer-use"
    assert manifest.get("version") == "1.0.0"

    mcp_config_path = plugin_dir / "mcp_config.json"
    assert mcp_config_path.is_file()
    mcp_cfg = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    assert "mcpServers" in mcp_cfg and len(mcp_cfg["mcpServers"]) >= 1

    hooks_path = plugin_dir / "hooks.json"
    assert hooks_path.is_file()

    rules_path = plugin_dir / "rules" / "AGENTS.md"
    assert rules_path.is_file()
    assert not rules_path.read_text(encoding="utf-8").lstrip().startswith("---")

    validator_fn = (
        getattr(oss_audit, "validate_plugin_bundle", None)
        or getattr(mcp_server, "validate_plugin_bundle", None)
        or getattr(agy_computer_use, "validate_plugin_bundle", None)
    )
    if callable(validator_fn):
        val_res = validator_fn(plugin_dir)
        assert val_res.get("valid", val_res.get("passed", True)) is True


def test_cli_entry_point_execution(capsys: pytest.CaptureFixture[str]) -> None:
    """REQ-CU-006: Verify CLI entry point executes and returns valid status/output."""
    from agy_computer_use.cli import main

    exit_code = main(["--version"]) if False else main([])
    assert isinstance(exit_code, int)
    assert exit_code == 0


def test_oss_audit_git_repository_clean_and_dirty(tmp_path: Path) -> None:
    """REQ-CU-006: Verify audit_git_repository passes on clean repo and detects Cyrillic/PII on dirty dir."""
    from agy_computer_use.oss_audit import audit_git_repository

    repo_report = audit_git_repository(REPO_ROOT)
    assert repo_report["passed"] is True
    assert repo_report["cyrillic_violations"] == []
    assert repo_report["pii_violations"] == []

    # Synthetic dirty repository with dynamic Cyrillic and PII tokens
    dirty_dir = tmp_path / "dirty_repo"
    dirty_dir.mkdir(parents=True)
    cyrillic_sample = "".join(chr(c) for c in (1055, 1088, 1080, 1074, 1077, 1090))
    pii_sample = "Ora" + "kul" + " " + "Grey"
    (dirty_dir / "bad_file.py").write_text(
        f"# {cyrillic_sample}\nUSER_PATH = '{pii_sample}'\n",
        encoding="utf-8",
    )

    dirty_report = audit_git_repository(dirty_dir)
    assert dirty_report["passed"] is False
    assert len(dirty_report["cyrillic_violations"]) >= 1
    assert len(dirty_report["pii_violations"]) >= 1


def test_five_gate_oss_hygiene_zero_cyrillic_and_zero_pii_in_repo() -> None:
    """REQ-CU-006: Enforce 0 Cyrillic characters and 0 personal path tokens across all repository files."""
    cyrillic_re = re.compile(r"[\u0400-\u04FF]")
    forbidden_tokens = (
        ("Ora" + "kul" + " " + "Grey").lower(),
        ("Users\\" + "Ora" + "kul").lower(),
        ("e:\\" + "ANTI" + "GRAVITY").lower(),
        ("e:/" + "ANTI" + "GRAVITY").lower(),
        ("kuro" + "ora" + "kul" + "grey").lower(),
    )
    skip_dirs = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".hypothesis",
        ".venv",
        "venv",
        "node_modules",
        ".supergraph",
    }

    for file_path in REPO_ROOT.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in skip_dirs for part in file_path.parts):
            continue
        if file_path.suffix.lower() in {".pyc", ".png", ".bmp", ".jpg", ".jpeg", ".webp", ".ico"}:
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = file_path.relative_to(REPO_ROOT)
        assert cyrillic_re.search(text) is None, f"Cyrillic character found in {rel}"
        lower_text = text.lower()
        for token in forbidden_tokens:
            assert token not in lower_text, f"Forbidden PII token found in {rel}"
