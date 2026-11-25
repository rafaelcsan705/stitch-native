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

## Example

`fixtures/match-stats.html` → [`examples/MatchStatsView.swift`](examples/MatchStatsView.swift) and [`examples/MatchStatsScreen.kt`](examples/MatchStatsScreen.kt).

## Status

Prototype. Known gaps:

- Output not yet compile-checked in CI.
- SwiftUI drops the font weight when a family token and a `text-*` size class share an element.
- Absolute positioning, animations and `hover:` states are ignored.

Roadmap: MCP server (`extract_tokens`, `stitch_to_ir`, `ir_to_swiftui`, `ir_to_compose`, `visual_diff`) and a Claude skill.

## License

MIT
