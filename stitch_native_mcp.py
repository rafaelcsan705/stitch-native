#!/usr/bin/env python3
"""MCP server (stdio, JSON-RPC 2.0) for stitch-native. Standard library only.

Register in Claude Code:
    claude mcp add stitch-native -- python3 /path/to/stitch_native_mcp.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stitch_native as sn  # noqa: E402

PROTOCOL = "2025-06-18"

SRC = {
    "html": {"type": "string", "description": "Stitch screen HTML (the export, including the tailwind-config script)."},
    "path": {"type": "string", "description": "Path to a Stitch HTML file. Used when html is not given."},
}
MAP = {"map": {"type": "object", "description": 'Token map: {"colors": {token|#hex: expr}, "fonts": {token: expr}}.'}}
NAME = {"name": {"type": "string", "description": "Generated view/composable name.", "default": "StitchScreen"}}

TOOLS = [
    {"name": "extract_tokens", "description": "Extract Stitch design tokens (colours, spacing) as a SwiftUI or Compose theme file.",
     "inputSchema": {"type": "object", "properties": {**SRC, "platform": {"type": "string", "enum": ["swiftui", "compose"], "default": "swiftui"}}}},
    {"name": "stitch_to_ir", "description": "Parse a Stitch screen into the platform-neutral layout IR (JSON).",
     "inputSchema": {"type": "object", "properties": SRC}},
    {"name": "stitch_to_swiftui", "description": "Convert a Stitch screen to a SwiftUI view. Reports off-token colours and warnings.",
     "inputSchema": {"type": "object", "properties": {**SRC, **NAME, **MAP}}},
    {"name": "stitch_to_compose", "description": "Convert a Stitch screen to a Jetpack Compose (Material 3) composable. Reports off-token colours and warnings.",
     "inputSchema": {"type": "object", "properties": {**SRC, **NAME, **MAP}}},
]


def load_html(a: dict) -> str:
    if a.get("html"):
        return a["html"]
    if a.get("path"):
        return Path(a["path"]).expanduser().read_text(encoding="utf-8")
    raise ValueError("Provide 'html' or 'path'.")


def call_tool(name: str, a: dict) -> str:
    th, ir, warn = sn.parse(load_html(a))
    if name == "extract_tokens":
        return sn.theme_kotlin(th) if a.get("platform") == "compose" else sn.theme_swift(th)
    if name == "stitch_to_ir":
        return json.dumps(ir, indent=1, ensure_ascii=False)
    if name in ("stitch_to_swiftui", "stitch_to_compose"):
        cls = sn.SwiftEmitter if name == "stitch_to_swiftui" else sn.ComposeEmitter
        em = cls(th, a.get("map") or {})
        code = em.screen(ir, a.get("name") or "StitchScreen")
        notes = [f"off-token literals: {sorted(set(em.literals))}"] + [f"warning: {w}" for w in sorted(set(warn))]
        return code + "\n\n/* stitch-native report\n" + "\n".join(notes) + "\n*/\n"
    raise ValueError(f"Unknown tool: {name}")


def handle(msg: dict):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notification
    if method == "initialize":
        res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
               "capabilities": {"tools": {}}, "serverInfo": {"name": "stitch-native", "version": "0.1.0"}}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            res = {"content": [{"type": "text", "text": call_tool(p.get("name"), p.get("arguments") or {})}]}
        except Exception as e:  # tool errors are returned, not raised
            res = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    elif method == "ping":
        res = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            out = handle(json.loads(line))
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
