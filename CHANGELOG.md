# Changelog

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
