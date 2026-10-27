"""5-Gate Open-Source Release Auditor and Antigravity 2.0 Plugin Bundle Validator.

Implements REQ-CU-006:
- Repository-wide Cyrillic character scanner ([\u0400-\u04FF])
- Personal workstation path and identifier hygiene scanner
- Native Antigravity 2.0 plugin bundle structural & <64-char MCP validator
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

_FORBIDDEN_PII_TOKENS: tuple[str, ...] = (
    ("ora" + "kul" + " " + "grey"),
    ("users\\" + "ora" + "kul"),
    ("users/" + "ora" + "kul"),
    ("e:\\" + "anti" + "gravity"),
    ("e:/" + "anti" + "gravity"),
    ("kuro" + "ora" + "kul" + "grey"),
)

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".hypothesis",
        ".venv",
        "venv",
        "node_modules",
        ".supergraph",
        "build",
        "dist",
    }
)

_BINARY_SUFFIXES: frozenset[str] = frozenset(
    {".pyc", ".pyo", ".png", ".bmp", ".jpg", ".jpeg", ".webp", ".ico", ".whl", ".tar", ".gz"}
)

_ALLOWED_MANIFEST_KEYS: frozenset[str] = frozenset(
    {"name", "displayName", "description", "version", "logo", "suggestedPrompts", "disabled"}
)


def audit_git_repository(repo_root: Path | str) -> dict[str, Any]:
    """REQ-CU-006: Scan all text files under repo_root for Cyrillic characters and PII tokens."""
    root = Path(repo_root).resolve()
    cyrillic_violations: list[str] = []
    pii_violations: list[str] = []
    files_scanned = 0

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_parts = file_path.relative_to(root).parts
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in rel_parts):
            continue
        if file_path.suffix.lower() in _BINARY_SUFFIXES:
            continue

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        files_scanned += 1
        rel_str = str(file_path.relative_to(root))

        if _CYRILLIC_RE.search(text):
            cyrillic_violations.append(rel_str)

        lower_text = text.lower()
        for token in _FORBIDDEN_PII_TOKENS:
            if token in lower_text:
                pii_violations.append(f"{rel_str}: {token}")
                break

    return {
        "repo_root": str(root),
        "files_scanned": files_scanned,
        "cyrillic_violations": cyrillic_violations,
        "pii_violations": pii_violations,
        "passed": len(cyrillic_violations) == 0 and len(pii_violations) == 0,
    }


def validate_plugin_bundle(plugin_dir: Path | str) -> dict[str, Any]:
    """REQ-CU-006: Validate an Antigravity 2.0 native plugin directory structure and MCP constraints."""
    pdir = Path(plugin_dir).resolve()
    errors: list[str] = []

    manifest_path = pdir / "plugin.json"
    if not manifest_path.is_file():
        errors.append(f"Missing plugin.json at {manifest_path}")
        return {"valid": False, "passed": False, "errors": errors}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    extra_keys = set(manifest.keys()) - _ALLOWED_MANIFEST_KEYS
    if extra_keys:
        errors.append(f"Disallowed plugin.json keys: {sorted(extra_keys)}")

    plugin_name = str(manifest.get("name", ""))
    if not plugin_name:
        errors.append("Missing 'name' in plugin.json")

    logo_rel = manifest.get("logo")
    if logo_rel and not (pdir / str(logo_rel)).is_file():
        errors.append(f"Missing logo asset: {logo_rel}")

    if not (pdir / "hooks.json").is_file():
        errors.append("Missing root hooks.json")

    rules_file = pdir / "rules" / "AGENTS.md"
    if not rules_file.is_file():
        errors.append("Missing rules/AGENTS.md")
    elif rules_file.read_text(encoding="utf-8").lstrip().startswith("---"):
        errors.append("rules/AGENTS.md must not start with YAML frontmatter '---'")

    mcp_file = pdir / "mcp_config.json"
    if mcp_file.is_file():
        mcp_cfg = json.loads(mcp_file.read_text(encoding="utf-8"))
        servers = mcp_cfg.get("mcpServers", {})
        for srv_name, srv_spec in servers.items():
            if plugin_name and not str(srv_name).startswith(plugin_name):
                errors.append(f"Server '{srv_name}' must be prefixed with '{plugin_name}'")
            for tool_name in srv_spec.get("tools", []):
                comp = f"mcp_{srv_name}_{tool_name}"
                if len(comp) > 64:
                    errors.append(f"Composite tool identifier '{comp}' exceeds 64 chars")

    is_valid = len(errors) == 0
    return {
        "valid": is_valid,
        "passed": is_valid,
        "plugin_name": plugin_name,
        "errors": errors,
    }
