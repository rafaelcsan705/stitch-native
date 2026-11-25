# stitch-native

Convert [Google Stitch](https://stitch.withgoogle.com) screen exports (HTML + Tailwind) into native UI code:

- **SwiftUI** (iOS 17+)
- **Jetpack Compose** (Material 3)

No dependencies: a single Python 3.10+ file, standard library only.

## How it works

```
Stitch HTML + tailwind.config  →  DOM  →  IR (JSON: box / text / icon / image + styles)  →  emitter
```

1. Reads the Tailwind theme Stitch embeds (`colors`, `spacing`, `borderRadius`, `fontFamily`, `fontSize`).
2. Resolves each element's classes into a small layout IR (row / column / grid, padding, gap, radius, borders, text styles).
3. Emits SwiftUI or Compose. Colours that are not theme tokens are reported as off-token literals.

## Usage

```bash
python3 stitch_native.py swiftui  screen.html --name MatchStatsView    > MatchStatsView.swift
python3 stitch_native.py compose  screen.html --name MatchStatsScreen  > MatchStatsScreen.kt
python3 stitch_native.py tokens        screen.html > StitchTheme.swift
python3 stitch_native.py tokens-kotlin screen.html > StitchTheme.kt
python3 stitch_native.py ir            screen.html > screen.ir.json
```

### Map tokens to your design system

```json
{ "colors": { "primary": "DS.Color.accent", "#12241c": "DS.Color.card" },
  "fonts":  { "headline-md": "DS.Font.title" } }
```

```bash
python3 stitch_native.py swiftui screen.html --map ds-map.json
```

## MCP server

`stitch_native_mcp.py` exposes the converter to any MCP client (stdio, no dependencies).

```bash
claude mcp add stitch-native -- python3 /path/to/stitch_native_mcp.py
```

| Tool | Does |
|---|---|
| `extract_tokens` | Theme file for `swiftui` or `compose` |
| `stitch_to_ir` | Layout IR as JSON |
| `stitch_to_swiftui` | SwiftUI view + off-token report |
| `stitch_to_compose` | Compose composable + off-token report |

Each tool takes `html` (the export) or `path`; the code tools also take `name` and `map`.
Pairs well with the official Stitch MCP: fetch the screen HTML there, convert here.

## Example

`fixtures/match-stats.html` → [`examples/MatchStatsView.swift`](examples/MatchStatsView.swift) and [`examples/MatchStatsScreen.kt`](examples/MatchStatsScreen.kt).

## Status

Prototype. Known gaps:

- Output not yet compile-checked in CI.
- SwiftUI drops the font weight when a family token and a `text-*` size class share an element.
- Absolute positioning, animations and `hover:` states are ignored.

Roadmap: `visual_diff` tool (render vs Stitch screenshot) and a Claude skill.

## License

MIT
