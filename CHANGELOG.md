# Changelog

## 0.2.0 — 2026-11-25
- Packaged for PyPI / `uvx` (`stitch-native`, `stitch-native-mcp` commands).
- MCP: `stitch_to_native` tool (both platforms in one call), `url` source, `convert_screen` prompt, token-map and IR resources.
- Fixes: font family weight kept when a size class is present; single-child flex rows become `ZStack`/`Box`; fixed and flexible frames no longer mixed in one `.frame()`.
- Tests (unittest) and CI: Python 3.10/3.13, `swiftc -typecheck`, Compose compile.

## 0.1.0
- First release: SwiftUI and Compose emitters, token export, IR, MCP server.
