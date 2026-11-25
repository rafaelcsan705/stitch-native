#!/usr/bin/env python3
"""MCP server (stdio, JSON-RPC 2.0) for stitch-native. Standard library only.

Register in Claude Code:
    claude mcp add stitch-native -- uvx stitch-native-mcp
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stitch_native as sn  # noqa: E402

PROTOCOL = "2025-06-18"
VERSION = "0.7.0"

SRC = {
    "html": {"type": "string", "description": "Stitch screen HTML (the export, including the tailwind-config script)."},
    "path": {"type": "string", "description": "Path to a Stitch HTML file. Used when html is not given."},
    "url": {"type": "string", "description": "HTTPS download URL of the screen HTML (a public https URL; Stitch downloadUrls need OAuth, so pass that HTML via html instead)."},
}
MODE = {"mode": {"type": "string", "enum": ["layout", "state"], "default": "layout", "description": "state: stateless screen with a State struct + sample, Identifiable rows, a tab Picker, localized keys and callbacks (no ViewModel)."}}
MAP = {"config": {"type": "object", "description": 'stitch-native.json contents: {"targets": ["swiftui","compose","html"], "colors": {token|#hex: expr}, "colorsHtml": {token|#hex: cssValue}, "fonts": {token: expr}, "icons": {material: sfSymbol}, "iconsCompose": {material: "Icons.X.Y"}, "iconsHtml": {material: text or inline svg}, "preview": {"colorScheme": "dark|light"}}. Alias: map. Without config, config_path or map, the server looks for stitch-native.json next to `path` and in its parent directories (first one found).'},
       "config_path": {"type": "string", "description": "Path to a stitch-native.json. Used when config is not given."}}
TARGETS_ARG = {"targets": {"type": "array", "items": {"type": "string", "enum": list(sn.TARGETS)}, "description": "Ecosystems to emit, out of swiftui, compose, html. Overrides the config's `targets`; without either: swiftui + compose. A comma-separated string is also accepted."}}
NAME = {"name": {"type": "string", "description": "Generated view/composable name.", "default": "StitchScreen"}}

TOOLS = [
    {"name": "extract_tokens", "description": "Extract Stitch design tokens (colours, spacing) as a SwiftUI theme, a Compose theme or CSS custom properties (:root).",
     "inputSchema": {"type": "object", "properties": {**SRC, "platform": {"type": "string", "enum": list(sn.TARGETS), "default": "swiftui"}}}},
    {"name": "stitch_to_ir", "description": "Parse a Stitch screen into the platform-neutral layout IR (JSON).",
     "inputSchema": {"type": "object", "properties": SRC}},
    {"name": "stitch_to_swiftui", "description": "Convert a Stitch screen to a SwiftUI view. Reports off-token colours and warnings.",
     "inputSchema": {"type": "object", "properties": {**SRC, **NAME, **MAP, **MODE}}},
    {"name": "stitch_to_compose", "description": "Convert a Stitch screen to a Jetpack Compose (Material 3) composable. Reports off-token colours and warnings.",
     "inputSchema": {"type": "object", "properties": {**SRC, **NAME, **MAP, **MODE}}},
]


TOOLS.append({"name": "stitch_to_html",
              "description": "Convert a Stitch screen to one self-contained HTML page (a single <style> block with tokens as CSS custom properties, semantic tags, no script, no external URLs). Layout mode only. Material icons become <span class=\"icon\" data-icon> filled from the config's iconsHtml; unmapped icons are listed.",
              "inputSchema": {"type": "object", "properties": {**SRC, **NAME, **MAP, **MODE}}})

TOOLS.append({"name": "stitch_to_native",
              "description": "Convert one Stitch screen to the project's targets in one call (swiftui, compose, html; default = the config's `targets`, else swiftui + compose), plus the theme file of each. In state mode html is skipped with a warning.",
              "inputSchema": {"type": "object", "properties": {**SRC, **NAME, **MAP, **MODE, **TARGETS_ARG}}})

TOOLS.append({"name": "init_config",
              "description": "Build a stitch-native.json skeleton from the colours, fonts and icons a screen uses, merged over an existing config (existing entries win and are never deleted). Only the keys of the requested targets are written (iOS-only: no iconsCompose, no output.compose); an explicit `targets` is stored in the config. Returns the JSON and the unmapped entries to fill in.",
              "inputSchema": {"type": "object", "properties": {**SRC, "existing": {"type": "object", "description": "Current config to merge into. Without it the config is discovered like for the other tools."},
                                                                "config_path": MAP["config_path"], **TARGETS_ARG}}})

MAX_BYTES = 5_000_000


def find_config(path: str) -> Path | None:
    """stitch-native.json next to the screen file or in the nearest parent directory (up to the filesystem root)."""
    start = Path(path).expanduser().resolve().parent
    for d in (start, *start.parents):
        f = d / sn.CONFIG_FILE
        if f.is_file():
            return f
    return None


def load_cfg(a: dict) -> dict:
    """Config precedence: `config` / `map` argument, `config_path`, then discovery from `path`, else {}."""
    for k in ("config", "map"):
        if a.get(k) is not None:
            return a[k]
    if a.get("config_path"):
        return sn.load_config(str(Path(a["config_path"]).expanduser()))
    if a.get("path"):
        found = find_config(a["path"])
        if found:
            return sn.load_config(str(found))
    return {}


def fetch(url: str) -> str:
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.netloc:
        raise ValueError("Only https:// URLs are allowed.")
    req = urllib.request.Request(url, headers={"User-Agent": f"stitch-native/{VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Screen HTML is larger than 5 MB.")
    return data.decode("utf-8", errors="replace")


def load_html(a: dict) -> str:
    if a.get("html"):
        return a["html"]
    if a.get("path"):
        return Path(a["path"]).expanduser().read_text(encoding="utf-8")
    if a.get("url"):
        return fetch(a["url"])
    raise ValueError("Provide 'html', 'path' or 'url'.")


TOKEN_MAP_DOC = json.dumps({
    "colors": {"surface": "DS.Colors.background", "#12241c": "DS.Colors.card"},
    "fonts": {"headline-md": ".title3.weight(.semibold)"},
    "targets": ["swiftui", "compose", "html"],
    "icons": {"bakery_dining": "birthday.cake"},
    "iconsCompose": {"bakery_dining": "Icons.Outlined.Cake"},
    "iconsHtml": {"bakery_dining": "<svg viewBox=\"0 0 24 24\"><path d=\"...\"/></svg>"},
    "colorsHtml": {"surface": "var(--brand-surface)", "#12241c": "#101c16"},
    "preview": {"colorScheme": "light"},
    "output": {"swiftui": "App/Screens", "compose": "app/src/main/java/ui", "html": "docs/screens"},
}, indent=2)
IR_DOC = """stitch-native IR: a tree of nodes.
box   {kind, tag, style, children}  style: layout row|column|grid, gap, pad{t,b,l,r}, bg, border, radius, width, height, align, justify, cols
text  {kind, text, style, box}       style: fontToken, familyToken, fontSize, weight, color, uppercase, textAlign
icon  {kind, material}               Material Symbols name, mapped to SF Symbols / Icons.*
image {kind, src, style}
Colours are {hex, token, alpha}. Use stitch_to_ir to see a real tree."""
RESOURCES = {
    "stitch-native://docs/token-map": ("Config (stitch-native.json) example", "application/json", TOKEN_MAP_DOC),
    "stitch-native://docs/ir": ("IR format", "text/plain", IR_DOC),
}
PROMPTS = {
    "convert_screen": {
        "description": "Convert a Stitch screen into native code that uses your own design system.",
        "arguments": [
            {"name": "screen", "description": "Stitch screen: file path, download URL, or 'project/screen' id", "required": True},
            {"name": "platform", "description": "swiftui, compose, html or a comma list. Default: the `targets` of the project's stitch-native.json (else swiftui + compose)", "required": False},
        ],
        "text": ("Convert the Stitch screen {screen} to {platform}.\n"
                 "1. If it is a Stitch project/screen id, call the Stitch MCP get_screen, then download_file on htmlCode, and pass the HTML text as html.\n"
                 "2. Call init_config (with the project's stitch-native.json as existing, if any, and targets set to the requested targets), then fill every unmapped entry from this project's design system and save it as stitch-native.json.\n"
                 "3. Call stitch_to_native (or stitch_to_swiftui / stitch_to_compose / stitch_to_html) with targets set to the requested targets and config set to that file's contents. With a `path` and a stitch-native.json next to it the config is found automatically. The html target only works in layout mode.\n"
                 "4. Replace every off-token literal in the report with the closest design-system token, wire real data, and put strings in localisation."),
    },
}


def call_tool(name: str, a: dict) -> str:
    th, ir, warn = sn.parse(load_html(a))
    if name == "init_config":
        cfg, unmapped = sn.init_config([ir], a.get("existing") or load_cfg(a), a.get("targets"))
        return (json.dumps(cfg, indent=2, ensure_ascii=False) + "\n\n"
                + "\n".join(f"unmapped {k} ({len(v)}): {', '.join(v) or '-'}" for k, v in unmapped.items()))
    if name == "extract_tokens":
        plat = a.get("platform") or "swiftui"
        if plat not in sn.TARGETS:
            raise ValueError(f"Unknown platform {plat!r}. Valid platforms: {', '.join(sn.TARGETS)}.")
        return sn.TARGETS[plat]["theme"](th)
    if name == "stitch_to_native":
        cfg = load_cfg(a)
        targets = list(sn.resolve_targets(a.get("targets"), cfg))
        notes = [f"warning: {w}" for w in sorted(set(warn))]
        if a.get("mode") == "state" and "html" in targets:
            targets.remove("html")
            notes.append("warning: html target skipped: it supports layout mode only")
        out, themes = [], []
        for t in targets:
            reg = sn.TARGETS[t]
            em = reg["emitter"](th, cfg)
            code = em.screen(prep(ir, a, reg["fence"]), a.get("name") or "StitchScreen")
            out.append(f"```{reg['fence']}\n{code}\n```\noff-token literals: {sorted(set(em.literals))}"
                       + (f"\nunmapped icons: {sorted(set(em.unmapped_icons))}" if getattr(em, "unmapped_icons", None) else ""))
            themes.append(f"```{reg['theme_fence']}\n{reg['theme'](th)}\n```")
        return "\n\n".join(out + themes + notes)
    if name == "stitch_to_ir":
        return json.dumps(ir, indent=1, ensure_ascii=False)
    if name in ("stitch_to_swiftui", "stitch_to_compose", "stitch_to_html"):
        target = name.removeprefix("stitch_to_")
        reg = sn.TARGETS[target]
        if a.get("mode") == "state" and "state" not in reg["modes"]:
            raise ValueError(f"The {target} target supports layout mode only (mode: state is not available).")
        em = reg["emitter"](th, load_cfg(a))
        code = em.screen(prep(ir, a, reg["fence"]), a.get("name") or "StitchScreen")
        notes = [f"off-token literals: {sorted(set(em.literals))}"]
        if getattr(em, "unmapped_icons", None):
            notes.append(f"unmapped icons: {sorted(set(em.unmapped_icons))}")
        notes += [f"warning: {w}" for w in sorted(set(warn))]
        if target == "html":
            return code + "\n<!-- stitch-native report\n" + "\n".join(notes).replace("--", "- -") + "\n-->\n"
        return code + "\n\n/* stitch-native report\n" + "\n".join(notes) + "\n*/\n"
    raise ValueError(f"Unknown tool: {name}")


def prep(ir: dict, a: dict, lang: str) -> dict:
    """Return the IR to emit; in state mode, a fresh copy with the state model attached."""
    if a.get("mode") != "state" or lang not in ("swift", "kotlin"):
        return ir
    import copy
    ir = copy.deepcopy(ir)
    sn.extract_state(ir, load_cfg(a), a.get("name") or "StitchScreen", lang)
    return ir


def handle(msg: dict):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notification
    if method == "initialize":
        res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
               "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
               "serverInfo": {"name": "stitch-native", "version": VERSION}}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            res = {"content": [{"type": "text", "text": call_tool(p.get("name"), p.get("arguments") or {})}]}
        except Exception as e:  # tool errors are returned, not raised
            res = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    elif method == "prompts/list":
        res = {"prompts": [{"name": k, "description": v["description"], "arguments": v["arguments"]} for k, v in PROMPTS.items()]}
    elif method == "prompts/get":
        p = msg.get("params", {})
        pr = PROMPTS.get(p.get("name"))
        if not pr:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown prompt"}}
        args = {"platform": "the targets in the project's stitch-native.json (`targets`; swiftui + compose when it declares none)", **(p.get("arguments") or {})}
        text = pr["text"].replace("{screen}", args.get("screen", "?")).replace("{platform}", args["platform"])
        res = {"description": pr["description"], "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    elif method == "resources/list":
        res = {"resources": [{"uri": u, "name": n, "mimeType": m} for u, (n, m, _) in RESOURCES.items()]}
    elif method == "resources/read":
        uri = msg.get("params", {}).get("uri")
        if uri not in RESOURCES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "Resource not found"}}
        _, m, text = RESOURCES[uri]
        res = {"contents": [{"uri": uri, "mimeType": m, "text": text}]}
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
