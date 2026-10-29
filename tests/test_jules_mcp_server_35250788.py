"""ISO 9001:2015 Agile V Verification Suite for MCP JSON-RPC 2.0 Dispatcher.

Covers REQ-CU-005: JSON-RPC 2.0 dispatch (initialize, ping, tools/list, tools/call)
with stateful VisualActionOracle session tracking across tool calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_initialize_returns_protocol_version() -> None:
    """REQ-CU-005: initialize handshake advertises MCP protocol 2024-11-05."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "agy-computer-use"


def test_ping_returns_ok_true() -> None:
    """REQ-CU-005: ping liveness probe returns {'ok': True}."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert resp["id"] == 7
    assert resp["result"] == {"ok": True}


def test_tools_list_exposes_all_mcp_tools() -> None:
    """REQ-CU-005: tools/list returns the full ALL_MCP_TOOLS registry."""
    from agy_computer_use.mcp_server import ALL_MCP_TOOLS, handle_jsonrpc_request

    resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = resp["result"]["tools"]
    assert isinstance(tools, list)
    assert len(tools) == len(ALL_MCP_TOOLS)
    names = {t["name"] for t in tools}
    assert "cu_type" in names
    assert "cu_capture_som" in names


def test_tools_call_cu_type_dry_run_returns_structured_content() -> None:
    """REQ-CU-005: tools/call dispatches cu_type and wraps payload as MCP content."""
    from agy_computer_use.mcp_server import handle_jsonrpc_request

    req = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {"name": "cu_type", "arguments": {"text": "hello", "dry_run": True}},
    }
    resp = handle_jsonrpc_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 42
    result = resp["result"]
    assert isinstance(result["content"], list) and result["content"]
    assert result["content"][0]["type"] == "text"
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["action_type"] == "type_text"
    assert payload["dry_run"] is True
    assert result["structuredContent"] == payload
    assert result["isError"] is False
