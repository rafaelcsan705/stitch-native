# Changelog

## 0.6.0 — 2026-11-25

State mode no longer copies mockup words into generated code, and it can plug into the app's own types.

- **Semantic names.** Field names keep the shape-based `number`, `price`, `date`, row `title`/`detail`; every other text becomes `field1`, `field2`… (numbered per scope). New config `state.fields` renames them (key: source text, auto name, or `Item.name` for row fields).
- **No mockup leakage.** L10n key slugs are `text1`, `text2`…, enum cases are `case1`… (config `state.enums.<n>.caseNames` names them) and accessibility-label keys follow the same rule. Free-text samples are neutral (`Store 1`, `Title 2`, `Item A`, `Text 3`); typed values (prices, `#1042`, quantities) are kept. New `state.samples` overrides a sample by field name. The sample comment no longer says "copied from the export".
- **Money type from config.** `state.money` (`type`, `swiftSample`, `swiftFormat`, `kotlinType`, `kotlinSample`, `kotlinFormat`, with `{cents}` / `{v}` placeholders) works for Swift and Kotlin. With a configured type or format there is no `// cents` comment and no private `money()` helper. `types.currency` still works as a fallback.
- **Existing domain enum.** `state.enums.<n>.existing: true` with `type`, `kotlinType`, `caseMap` (and optional `kotlinCaseMap`) maps the status texts to an enum the app already has: it is not declared, samples use the mapped case, the tracker iterates an explicit ordered steps list built from `caseMap`, and a private helper maps case → L10n key (a `default` branch covers domain cases without a label). Unmapped cases produce a warning. A row struct that would shadow the domain type (e.g. `Order` vs `Order.Status`) is renamed `<Item>Row` automatically.
- **Active order split.** When a tracker or lines block sits next to a row group, the fields bound inside it move into a detail struct (`activeOrder: ActiveOrder?` by default) and the subtree is wrapped in `if let active = state.activeOrder` / `state.activeOrder?.let { active -> … }`. Configure with `state.detail` (`{field, type}`) or turn off with `false`.
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
