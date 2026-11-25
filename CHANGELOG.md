# Changelog

## 0.7.1 — 2026-11-25

Fixes found by CI on the 0.7.0 tag. 0.7.0 was never published to PyPI.

- **Python 3.10 and 3.11.** `stitch_native.py` failed to import (`SyntaxError: f-string: unmatched '['`): the HTML emitter nested same-type quotes inside an f-string, which only Python 3.12+ accepts. The package declares `requires-python >= 3.10`.
- **Compose: one-sided pill corners.** `rounded-l-full` / `rounded-r-full` emitted `RoundedCornerShape(topStart = 50, ...)`, which does not compile (the named `topStart` overloads take `Dp` or `Float`). They now emit the percent overload: `RoundedCornerShape(topStartPercent = 50, topEndPercent = 0, bottomEndPercent = 0, bottomStartPercent = 50)`.
- **CI compose job.** The desktop compile check has no Android `@Preview`; a compile-only stub of `androidx.compose.ui.tooling.preview.Preview` lives in `ci/compose/src`. Generated code is unchanged.
- Tests: `examples/MatchStatsScreen.kt` is now a checked golden, with an assertion on the percent overload.

## 0.7.0 — 2026-11-25

A project can declare its ecosystem, and there is an HTML target.

- **`targets`.** New config key (and MCP `targets` argument on `stitch_to_native` / `init_config`, CLI `init --targets swiftui,html`): any of `swiftui`, `compose`, `html`. The argument wins over the config; with neither, behaviour is unchanged (`swiftui` + `compose`). Unknown names are an error listing the valid ones.
- **Target registry.** One `TARGETS` table in `stitch_native.py` (emitter, theme function, fence language, owned config keys, output key, supported modes) replaces the hard-coded pairs in `stitch_to_native`, `init_config` and the CLI. A new ecosystem is one entry plus its emitter.
- `stitch_to_native` emits only the requested targets and their themes. `init_config` writes and reports only their keys (an iOS-only project gets no `iconsCompose` and no `output.compose`); existing entries are never deleted, and an explicit `targets` is stored in the config.
- **MCP config discovery.** Without `config`, `map` or `config_path`, a `path` argument makes the server use the nearest `stitch-native.json` next to the file or in a parent directory. Before, the MCP server never read a config file by itself.
- **`html` target.** `HtmlEmitter` + `theme_css`; CLI `html` and `tokens-css`; MCP `stitch_to_html`; `extract_tokens` with `platform: "html"`. One self-contained page: a single `<style>` (tokens as CSS custom properties, generated classes), semantic tags, system font stack, no Tailwind, no `<script>`, no external URLs. Material icons become `<span class="icon" data-icon>` filled from `iconsHtml` (unmapped ones are listed); `colorsHtml` maps colours to CSS values, and `colors` entries are used only when they already look like CSS. Layout mode only (`mode: state` is an error; `stitch_to_native` skips html in state mode with a warning).
- Golden examples `examples/MatchStats.html` and `examples/OrdersList.html`.
- Tool descriptions, the `convert_screen` prompt (`platform` may be a comma list; default = the config's `targets`), the token-map resource, CLI help and README updated.
- Version bump in `pyproject.toml` and `stitch_native_mcp.py`; `server.json` jumps from 0.3.0 to 0.7.0 (it had been left behind).

## 0.6.0 — 2026-11-25

State mode no longer copies mockup words into generated code, and it can plug into the app's own types.

- **Semantic names.** Field names keep the shape-based `number`, `price`, `date`, row `title`/`detail`; every other text becomes `field1`, `field2`… (numbered per scope). New config `state.fields` renames them (key: source text, auto name, or `Item.name` for row fields).
- **No mockup leakage.** L10n key slugs are `text1`, `text2`…, enum cases are `case1`… (config `state.enums.<n>.caseNames` names them) and accessibility-label keys follow the same rule. Free-text samples are neutral (`Store 1`, `Title 2`, `Item A`, `Text 3`); typed values (prices, `#1042`, quantities) are kept. New `state.samples` overrides a sample by field name. The sample comment no longer says "copied from the export".
- **Money type from config.** `state.money` (`type`, `swiftSample`, `swiftFormat`, `kotlinType`, `kotlinSample`, `kotlinFormat`, with `{cents}` / `{v}` placeholders) works for Swift and Kotlin. With a configured type or format there is no `// cents` comment and no private `money()` helper. `types.currency` still works as a fallback.
- **Existing domain enum.** `state.enums.<n>.existing: true` with `type`, `kotlinType`, `caseMap` (and optional `kotlinCaseMap`) maps the status texts to an enum the app already has: it is not declared, samples use the mapped case, the tracker iterates an explicit ordered steps list built from `caseMap`, and a private helper maps case → L10n key (a `default` branch covers domain cases without a label). Unmapped cases produce a warning. A row struct that would shadow the domain type (e.g. `Order` vs `Order.Status`) is renamed `<Item>Row` automatically.
- **Active order split.** When a tracker or lines block sits next to a row group, the fields bound inside it move into a detail struct (`activeOrder: ActiveOrder?` by default) and the subtree is wrapped in `if let active = state.activeOrder` / `state.activeOrder?.let { active -> … }`. Configure with `state.detail` (`{field, type}`) or turn off with `false`.
- `state.detail.fields` moves extra root fields into the detail struct; texts of those fields rendered outside the block are wrapped in their own `if let active` / `?.let { active -> }`.
- `state.enums.<n>.domainCases` makes the existing-enum title helper exhaustive (one key per domain case, no `default`). Texts mapped to the same domain case share one key and appear once in the tracker steps.
- State warnings (shadowed types, unmapped cases, fields bound inside and outside the detail block) are now printed on stderr.

## 0.5.2 — 2026-11-25

- SwiftUI: `grid-cols-N` with `col-span-*` children now emits a private `SpanColumns` Layout, so 3/1/3 spans keep their 3:1:3 widths instead of equal columns.
- SwiftUI: percentage split bars subtract gap and padding before applying the percentage, so they no longer overflow their track.
- MCP serverInfo version now matches pyproject.

## 0.5.1 — 2026-11-25

- "Brand — Store" texts bind to a generic `storeName` field (override with `storeField` in the config), never a place name.
- Status trackers render as `ForEach` over the enum cases (`OrderStatus.allCases` / `.entries`), colouring done/current/pending from `state.status`; the enum gets `rank`. Step icons and connectors are simplified away.
- Order lines render one row per line (`ForEach(state.lines)` / `forEach`); `Line` is `Identifiable`.

## 0.5.0 — 2026-11-25
- Dynamic Type: font sizes map to text styles (`.system(.body, weight:)`, `.custom(…, relativeTo:)` for custom families); px sizes are parsed.
- State mode: order lines (`N× name`) become `lines: [Line]` with a `Line` struct / data class.
- State mode: `state.enums` turns status trackers and chips into an enum (`OrderStatus`) with localized titles.
- State mode: `state.brand` binds brand texts to `brandName`; a "Brand — Store" text is named after the store. Brand-like shell text gives a warning.
- State mode: `state.key_over` overrides localization keys by source text or auto key.
- Swift wraps repeated rows in `LazyVStack`; Compose marks where to move to `LazyColumn`.
- Fix: the money locale comes from the page's `<html lang>`, not from the target name.

## 0.4.0 — 2026-11-25
- `--mode state` (CLI and MCP `mode` argument): a stateless screen fed by a generated State struct/data class with a `.sample` copied from the export.
  - Repeated rows become `ForEach` / `forEach { key(id) }` over Identifiable items; tabs become a segmented `Picker` / `SingleChoiceSegmentedButtonRow`.
  - Visible text goes through localization keys (`LocalizedStringKey` / `stringResource`); money is stored as Int/Long cents and formatted with the configured locale.
  - Actions go out through callbacks (`onRepeat(order)`), Compose state is hoisted with `rememberSaveable`; no ViewModel or UseCase is generated.
  - Previews: light, dark and large text (`accessibility3` / `fontScale = 2f`).
- Golden examples `OrdersListView.swift` / `OrdersListScreen.kt` from the `fornada-encomendas` fixture.

## 0.3.0 — 2026-11-25
- Overlays: sheets, toasts, top and bottom bars (`safeAreaInset`/`.sheet`/`.overlay`; Compose `Scaffold`/`Dialog`).
- `<button>` becomes `Button`, inline `<svg>` becomes a vector node, `<script>` text is dropped.
- Built-in colours (`white`, `black`, `transparent`) map to platform colours, not theme tokens.
- `stitch-native.json` project config (auto-loaded) and `init` command; icon overrides; ~60 more Material→SF mappings.
- MCP: `init_config` tool, `config`/`config_path` arguments (`map` still accepted).

## 0.2.0 — 2026-11-25
- Packaged for PyPI / `uvx` (`stitch-native`, `stitch-native-mcp` commands).
- MCP: `stitch_to_native` tool (both platforms in one call), `url` source, `convert_screen` prompt, token-map and IR resources.
- Fixes: font family weight kept when a size class is present; single-child flex rows become `ZStack`/`Box`; fixed and flexible frames no longer mixed in one `.frame()`.
- Tests (unittest) and CI: Python 3.10/3.13, `swiftc -typecheck`, Compose compile.

## 0.1.0
- First release: SwiftUI and Compose emitters, token export, IR, MCP server.
