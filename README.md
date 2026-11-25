<!-- mcp-name: io.github.rafaelcsan705/stitch-native -->
<p align="center"><img src="assets/logo.svg" width="96" alt="stitch-native logo"></p>
<h1 align="center">stitch-native</h1>
<p align="center">Google Stitch screens → native <b>SwiftUI</b>, <b>Jetpack Compose</b> and plain <b>HTML</b>. CLI + MCP server.</p>
<p align="center">
<a href="https://github.com/rafaelcsan705/stitch-native/actions/workflows/ci.yml"><img src="https://github.com/rafaelcsan705/stitch-native/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
<img src="https://img.shields.io/badge/MCP-stdio-8a63d2" alt="MCP">
<img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</p>

![From Stitch HTML to SwiftUI and Compose](assets/hero.svg)

## Quick start

```bash
uvx --from git+https://github.com/rafaelcsan705/stitch-native stitch-native swiftui screen.html > Screen.swift
```

## Add to your agent

| Client | Config |
|---|---|
| Claude Code | `claude mcp add stitch-native -- uvx --from git+https://github.com/rafaelcsan705/stitch-native stitch-native-mcp` |
| Claude Desktop / Cursor / VS Code | see JSON below |

```json
{ "mcpServers": { "stitch-native": {
  "command": "uvx",
  "args": ["--from", "git+https://github.com/rafaelcsan705/stitch-native", "stitch-native-mcp"] } } }
```

Tools: `stitch_to_native`, `stitch_to_swiftui`, `stitch_to_compose`, `stitch_to_html`, `extract_tokens`, `stitch_to_ir`, `init_config` (source: `html`, `path` or `url`). Prompt: `convert_screen`. Resources: token-map and IR docs.

## How it works

```
Stitch HTML + tailwind.config  →  DOM  →  IR (JSON: box / text / icon / image + styles)  →  emitter
```

1. Reads the Tailwind theme Stitch embeds (`colors`, `spacing`, `borderRadius`, `fontFamily`, `fontSize`).
2. Resolves each element's classes into a small layout IR (row / column / grid, padding, gap, radius, borders, text styles).
3. Emits SwiftUI, Compose or HTML. Colours that are not theme tokens are reported as off-token literals.

## Usage

```bash
python3 stitch_native.py swiftui  screen.html --name MatchStatsView    > MatchStatsView.swift
python3 stitch_native.py compose  screen.html --name MatchStatsScreen  > MatchStatsScreen.kt
python3 stitch_native.py tokens        screen.html > StitchTheme.swift
python3 stitch_native.py tokens-kotlin screen.html > StitchTheme.kt
python3 stitch_native.py html     screen.html --name MatchStats       > MatchStats.html
python3 stitch_native.py tokens-css    screen.html > tokens.css
python3 stitch_native.py ir            screen.html > screen.ir.json

# State mode: stateless screen + State struct/sample, keys, callbacks (no ViewModel)
python3 stitch_native.py swiftui fixtures/fornada-encomendas.html --name OrdersListView   --mode state
python3 stitch_native.py compose fixtures/fornada-encomendas.html --name OrdersListScreen --mode state
```

`--mode state` reads `locale`, `timeZone`, `currency` and key prefixes from `stitch-native.json`. Plug the screen into your own ViewModel/Coordinator: it only takes `state` and callbacks.

#### `state.*` config (all optional)

| Key | What it does |
|---|---|
| `brand` | Texts bound to `state.brandName` instead of being baked in |
| `storeField` | Field name for "Brand — Store" texts (default `storeName`) |
| `prefix`, `keys`, `locale`, `rename` | Key prefix; source text or auto key → final L10n key; locale; rename a row struct or field (`{"Order": "OrderRow", "orderRows": "orders"}`) |
| `fields` | Semantic names. Key = source text, auto name (`field2`) or `Item.name` (`Order.field1`) → name |
| `samples` | Sample value by final field name (`Item.name` for row fields; a list gives one value per row; prices take cents). Without it samples are neutral (`Text 1`, `Store 1`) |
| `money` | `{type, swiftSample, swiftFormat, kotlinType, kotlinSample, kotlinFormat}`; `{cents}` is the sample amount, `{v}` the value expression. The Swift type must be `Equatable` (the state struct is). Without it: `Int`/`Long` cents plus a private `money()` helper |
| `enums.<name>` | `cases` (source texts), `type`, `current`, `caseNames` (list, or text → name; default `case1`…) |
| `enums.<name>.existing` | `true` = use the app's own enum: needs `type` (Swift), `kotlinType`, `caseMap` (source text → domain case), optional `kotlinCaseMap` (domain case → Kotlin name). Not declared; the tracker shows only the `caseMap` steps in `cases` order; the generated private helpers `<name>Steps`, `<name>Rank`, `<name>Title` map cases to L10n keys. Two source texts mapped to one domain case are de-duplicated in the steps (first occurrence wins) and share a key |
| `enums.<name>.domainCases` | Every case of the app's enum, in order. `<name>Title` then gets one L10n key per case and an exhaustive `switch` / `when` (no `default`), so a missing case fails to compile. Cases not in `caseMap` get a key whose text is derived from the case name. Without it the helper keeps a flagged `default` (first step's label). A case that is not a tracker step shows its own label in the status chip; in the tracker every step is pending and none is highlighted |
| `detail` | `{field, type, fields}` for the active/detail struct (default `active<Item>` / `Active<Item>`), or `false` to keep everything on the root. `fields` lists extra root fields (final names) to move into it, e.g. data bound outside the tracker/lines block; texts rendered outside that block are wrapped in their own `if let active` / `?.let { active -> }` |

An existing enum must be a plain case enum (`Hashable`, no payloads). The Swift generated code uses `Order.Status`-style names verbatim, so the row struct must not be called `Order` (it is renamed automatically).

### Targets

A project declares its ecosystem with `targets` in `stitch-native.json`: any of `swiftui`, `compose`, `html`. Without it (and without a `targets` argument) the tools emit `swiftui` + `compose`, as before. Unknown names are an error that lists the valid ones.

```bash
python3 stitch_native.py init screen.html --targets swiftui,html   # writes only swiftui + html keys, stores targets
```

- MCP `stitch_to_native` and `init_config` take a `targets` argument (it wins over the config). `stitch_to_native` emits only those targets and their theme files; `init_config` writes only their keys (an iOS-only project gets no `iconsCompose` and no `output.compose`) and never deletes existing entries.
- Internally one registry (`TARGETS` in `stitch_native.py`: emitter, theme function, fence language, owned config keys) drives the CLI, MCP and `init`, so a new ecosystem is one registry entry plus its emitter.
- **Config discovery (MCP):** when no `config`, `map` or `config_path` is passed but `path` is, the server reads the nearest `stitch-native.json` next to that file or in a parent directory (up to the filesystem root); otherwise it uses no config. The CLI keeps reading `./stitch-native.json`.

### HTML target

`html` writes one self-contained page: a single `<style>` block (tokens as `--color-*`, `--space-*`, `--font-*` custom properties on `:root`, plus generated `.s1`, `.s2`… classes), semantic tags where the export has them (`header`, `nav`, `main`, `section`, `h1`…, `ul`, `table`…), and no Tailwind, no `<script>`, no external URLs. Fonts use the system stack (a token's own font name is tried first). Images keep their `src`; inline `<svg>` becomes an empty `<span>` with a TODO comment.

- Material icons become `<span class="icon" data-icon="name">`. Fill them with `iconsHtml` (`{"home": "⌂"}` text or inline `<svg>` markup, used verbatim); unmapped names are listed (`unmapped iconsHtml` in `init`, `unmapped icons` in the report).
- Colours: `colorsHtml` (token or `#hex` → CSS value) wins; `colors` entries are used only when they already look like a CSS value (`#hex`, `var(...)`, `rgb(...)`…), so a Swift expression shared with the iOS target never lands in the CSS. Off-token literals are reported like for the other targets.
- Toasts and sheets are emitted `hidden`; top and bottom bars are `position: sticky`.
- Layout mode only: `--mode state` / `mode: "state"` is an error for `html`; `stitch_to_native` in state mode skips it with a warning.
- Examples: [`examples/MatchStats.html`](examples/MatchStats.html), [`examples/OrdersList.html`](examples/OrdersList.html).

### Map tokens to your design system

```json
{ "colors": { "primary": "DS.Color.accent", "#12241c": "DS.Color.card" },
  "fonts":  { "headline-md": "DS.Font.title" } }
```

```bash
python3 stitch_native.py init screen.html      # writes stitch-native.json, lists unmapped tokens/icons
python3 stitch_native.py swiftui screen.html   # auto-loads ./stitch-native.json (or --config path)
```

`stitch-native.json` also takes `targets`, `icons` (Material → SF Symbol), `iconsCompose`
(Material → `Icons.X.Y`), `iconsHtml`, `colorsHtml`, `preview.colorScheme` and `output` folders. `null` entries fall back to the theme.

## MCP server

`stitch_native_mcp.py` exposes the converter to any MCP client (stdio, no dependencies).

```bash
claude mcp add stitch-native -- python3 /path/to/stitch_native_mcp.py
```

| Tool | Does |
|---|---|
| `extract_tokens` | Theme file for `swiftui`, `compose` or `html` (CSS custom properties) |
| `stitch_to_ir` | Layout IR as JSON |
| `stitch_to_swiftui` | SwiftUI view + off-token report |
| `stitch_to_compose` | Compose composable + off-token report |
| `stitch_to_html` | Self-contained HTML page + off-token and unmapped-icon report (layout mode) |
| `stitch_to_native` | The configured targets (default swiftui + compose) in one call, with their theme files |
| `init_config` | `stitch-native.json` skeleton + unmapped list |

Each tool takes `html` (the export) or `path`; the code tools also take `name` and `config` (object) or `config_path` (else the nearest `stitch-native.json` next to `path`).
Pairs well with the official Stitch MCP: fetch the screen HTML there, convert here.

## Example

`fixtures/match-stats.html` → [`examples/MatchStatsView.swift`](examples/MatchStatsView.swift), [`examples/MatchStatsScreen.kt`](examples/MatchStatsScreen.kt) and [`examples/MatchStats.html`](examples/MatchStats.html).

## Status

Prototype. Known gaps:

- Output not yet compile-checked in CI.
- SwiftUI drops the font weight when a family token and a `text-*` size class share an element.
- Absolute positioning, animations and `hover:` states are ignored.

Roadmap: `visual_diff` tool (render vs Stitch screenshot) and a Claude skill.

## Releasing

Pushing a tag `vX.Y.Z` runs `.github/workflows/publish.yml`: tests, build, upload to PyPI (trusted publishing), then publish `server.json` to the MCP registry (GitHub OIDC). No secrets are stored. `pyproject.toml`, both versions in `server.json` and `VERSION` in `stitch_native_mcp.py` must agree (a unit test checks it); the tag must match too.

One-time manual step on pypi.org (Account → Publishing → "Add a new pending publisher"), before the first tag:

| Field | Value |
|---|---|
| PyPI project name | `stitch-native` |
| Owner | `rafaelcsan705` |
| Repository name | `stitch-native` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Optionally create a GitHub environment named `pypi` (Settings → Environments) with required reviewers as a manual gate.

## License

MIT
