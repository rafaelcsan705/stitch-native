import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import stitch_native as sn  # noqa: E402
import stitch_native_mcp as mcp  # noqa: E402

FIXTURE = ROOT / "fixtures" / "match-stats.html"


class ConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.th, cls.ir, cls.warn = sn.parse(FIXTURE.read_text(encoding="utf-8"))

    def test_tokens_parsed(self):
        self.assertIn("primary", self.th.colors)
        self.assertIn("headline-md", self.th.font_size)

    def test_ir_root_is_body(self):
        self.assertEqual(self.ir["tag"], "body")

    def test_swiftui_keeps_family_weight_with_size(self):
        code = sn.SwiftEmitter(self.th, {}).screen(self.ir, "V")
        self.assertIn('Text("Estatísticas do Jogo")\n', code)
        line = code.split('Text("Estatísticas do Jogo")')[1].splitlines()[1]
        self.assertIn("weight: .semibold", line)

    def test_no_mixed_frame(self):
        code = sn.SwiftEmitter(self.th, {}).screen(self.ir, "V")
        self.assertNotIn("height: 8, maxWidth", code)

    def test_single_child_wrapper(self):
        swift = sn.SwiftEmitter(self.th, {}).screen(self.ir, "V")
        kt = sn.ComposeEmitter(self.th, {}).screen(self.ir, "S")
        self.assertIn("ZStack {", swift)
        self.assertIn("contentAlignment = Alignment.Center", kt)

    def test_token_map_replaces_colours(self):
        em = sn.SwiftEmitter(self.th, {"colors": {"#12241c": "DS.card"}})
        self.assertIn("DS.card", em.screen(self.ir, "V"))
        self.assertNotIn("#12241c", em.literals)

    def test_examples_up_to_date(self):
        swift = sn.SwiftEmitter(self.th, {}).screen(self.ir, "MatchStatsView")
        self.assertEqual(swift.strip(), (ROOT / "examples" / "MatchStatsView.swift").read_text().strip())

    def test_compose_example_up_to_date(self):
        kt = sn.ComposeEmitter(self.th, {}).screen(self.ir, "MatchStatsScreen")
        self.assertEqual(kt.strip(), (ROOT / "examples" / "MatchStatsScreen.kt").read_text().strip())
        # One-sided pills use the percent overload; `topStart = 50` (an Int) does not compile.
        self.assertIn("RoundedCornerShape(topStartPercent = 50, topEndPercent = 0, "
                      "bottomEndPercent = 0, bottomStartPercent = 50)", kt)
        self.assertNotRegex(kt, r"topStart = \d+[,)]")



class StateModeTests(unittest.TestCase):
    def gen(self, target, name, config="fornada.stitch-native.json", cfg_dict=None):
        args = ["--config", str(ROOT / "fixtures" / config)] if config else []
        if cfg_dict is not None:
            import tempfile
            tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            json.dump(cfg_dict, tmp)
            tmp.close()
            args = ["--config", tmp.name]
        return subprocess.run([sys.executable, str(ROOT / "stitch_native.py"), target,
                               str(ROOT / "fixtures" / "fornada-encomendas.html"), "--name", name, "--mode", "state"] + args,
                              capture_output=True, text=True, timeout=60, check=True).stdout

    def test_swift_state_golden_and_rules(self):
        out = self.gen("swiftui", "OrdersListView")
        self.assertEqual(out.strip(), (ROOT / "examples" / "OrdersListView.swift").read_text().strip())
        for must in ("struct OrdersListViewState", "Identifiable", "Picker(", "onRepeat", "#Preview(\"Dark\")",
                     "var brandName: String", "let lines: [Line]", "let status: Order.Status", "LazyVStack(",
                     ".font(.system(.body", "ordersList.selectedItems", "var activeOrder: ActiveOrder?",
                     "if let active = state.activeOrder {", "ForEach(statusSteps, id: \\.self)", "ForEach(active.lines)",
                     "struct Line: Identifiable", "price: Money", "active.price.formatted()", "Money(cents: 1240)",
                     "let storeName: String", "statusRank(step) < statusRank(active.status)",
                     "private var statusSteps: [Order.Status] { [.placed, .preparing, .ready] }",
                     'case .cancelled: "ordersList.status.cancelled"', 'case .outForDelivery: "ordersList.status.outForDelivery"',
                     "let pickupCode: String", "Text(active.pickupTitle)", "Text(active.estimatedTime)"):
            self.assertIn(must, out)
        self.assertNotIn("ViewModel", out)
        self.assertNotIn("UseCase", out)
        self.assertNotIn("lojaAlcobaca", out)
        self.assertNotIn("default:", out)
        self.assertEqual(out.count("if let active = state.activeOrder {"), 4)
        for never in ("enum OrderStatus", "// cents", "private func money", "Status.allCases", "Sample data copied"):
            self.assertNotIn(never, out)

    def test_compose_state_golden_and_rules(self):
        out = self.gen("compose", "OrdersListScreen")
        self.assertEqual(out.strip(), (ROOT / "examples" / "OrdersListScreen.kt").read_text().strip())
        for must in ("data class OrdersListScreenState", "SegmentedButton(", "onRepeat: (", "rememberSaveable",
                     "stringResource(R.string.", "UI_MODE_NIGHT_YES",
                     "List<Line>", "state.activeOrder?.let { active ->", "statusSteps.forEach { step ->", "active.lines.forEach",
                     "val storeName: String", "val price: Money", "Money(1240L)", "active.price.formatted()",
                     "private fun statusTitle(value: OrderStatus): Int",
                     "OrderStatus.Cancelled -> R.string.orders_list_status_cancelled", "text = active.pickupCode",
                     "private val statusSteps = listOf(OrderStatus.Placed, OrderStatus.Preparing, OrderStatus.Ready)"):
            self.assertIn(must, out)
        self.assertNotIn("else ->", out.split("private fun statusTitle")[1].split("\n}")[0])
        for never in ("joinToString", "lojaAlcobaca", "enum class OrderStatus", "private fun money", "// cents"):
            self.assertNotIn(never, out)
        for must in ():
            self.assertIn(must, out)
        self.assertNotIn("ViewModel", out)

    LEAKS = ("lérias", "lerias", "alcoba", "turquel", "padaria", "pao", "alentejano")

    def test_no_mockup_words_without_config(self):
        for target, name in (("swiftui", "OrdersListView"), ("compose", "OrdersListScreen")):
            out = self.gen(target, name, config=None).lower()
            for word in self.LEAKS:
                self.assertNotIn(word, out, f"{target}: '{word}' leaked from the mockup")
            self.assertIn("ordersList.text1" if target == "swiftui" else "orders_list_text1", out.replace("orderslist.text1", "ordersList.text1"))
            self.assertIn("field1", out)

    def test_config_names_and_samples(self):
        cfg = {"state": {"fields": {"Order.field1": "summary", "Tempo estimado: 18 min": "eta"},
                         "samples": {"eta": "5 min", "Order.title": ["A", "B"]},
                         "enums": {"status": {"cases": ["Recebida", "A preparar", "No forno", "Pronta"],
                                              "caseNames": ["received", "preparing", "baking", "ready"]}}}}
        out = self.gen("swiftui", "OrdersListView", cfg_dict=cfg)
        for must in ("let summary: String", "var eta: String", 'eta: "5 min"', 'title: "A"', 'title: "B"', 'title: "A"',
                     "case received", "case baking", "enum OrderStatus"):
            self.assertIn(must, out.replace("enum Status", "enum OrderStatus"))
        self.assertIn("// cents", out)          # no money config: the default Int cents path
        self.assertIn("private func money", out)

    def test_existing_enum_clash_renames_row_struct(self):
        cfg = {"state": {"enums": {"status": {"existing": True, "type": "Order.Status", "kotlinType": "OrderStatus",
                                              "cases": ["Recebida", "A preparar"], "caseMap": {"Recebida": "placed", "A preparar": "preparing"}}}}}
        out = self.gen("swiftui", "OrdersListView", cfg_dict=cfg)
        self.assertIn("struct OrderRow:", out)
        self.assertIn("var orders: [OrderRow]", out)
        self.assertNotIn("enum Status", out)

    def test_two_texts_one_domain_case_dedupe_steps(self):
        out = self.gen("swiftui", "OrdersListView")  # fixture: "A preparar" and "No forno" are both .preparing
        self.assertIn("{ [.placed, .preparing, .ready] }", out)
        self.assertEqual(out.count("case .preparing:"), 1)
        self.assertNotIn("preparing2", out)

    def test_without_domain_cases_keeps_a_flagged_default(self):
        cfg = {"state": {"enums": {"status": {"existing": True, "type": "Order.Status", "kotlinType": "OrderStatus",
                                              "cases": ["Recebida", "A preparar"], "caseMap": {"Recebida": "placed", "A preparar": "preparing"}}}}}
        out = self.gen("swiftui", "OrdersListView", cfg_dict=cfg)
        self.assertIn("default:", out)
        self.assertIn("domainCases", out)

    def test_detail_fields_moves_root_fields_and_guards_outside_use(self):
        cfg = {"state": {"fields": {"Tempo estimado: 18 min": "eta"}, "detail": {"fields": ["eta", "nope"]}}}
        sw = self.gen("swiftui", "OrdersListView", cfg_dict=cfg)
        self.assertIn("let eta: String", sw)
        self.assertNotIn("var eta: String", sw)
        self.assertIn("Text(active.eta)", sw)
        kt = self.gen("compose", "OrdersListScreen", cfg_dict=cfg)
        self.assertIn("text = active.eta", kt)
        self.assertEqual(kt.count("state.activeOrder?.let { active ->"), 2)

    def test_detail_can_be_disabled_and_renamed(self):
        off = self.gen("swiftui", "OrdersListView", cfg_dict={"state": {"detail": False}})
        self.assertNotIn("ActiveOrder", off)
        self.assertIn("var lines: [Line]", off)
        named = self.gen("compose", "OrdersListScreen", cfg_dict={"state": {"detail": {"field": "current", "type": "CurrentOrder"}}})
        self.assertIn("val current: CurrentOrder?", named)
        self.assertIn("state.current?.let { active ->", named)


class McpTests(unittest.TestCase):
    def rpc(self, *msgs):
        inp = "\n".join(json.dumps(m) for m in msgs) + "\n"
        out = subprocess.run([sys.executable, str(ROOT / "stitch_native_mcp.py")], input=inp,
                             capture_output=True, text=True, timeout=60).stdout
        return [json.loads(line) for line in out.splitlines()]

    def test_handshake_and_lists(self):
        r = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                     {"jsonrpc": "2.0", "method": "notifications/initialized"},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                     {"jsonrpc": "2.0", "id": 3, "method": "prompts/list"},
                     {"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
        self.assertEqual(len(r), 4)
        import re
        ver = re.search(r'version = "([^"]+)"', (ROOT / "pyproject.toml").read_text()).group(1)
        self.assertEqual(r[0]["result"]["serverInfo"]["version"], ver)
        names = {t["name"] for t in r[1]["result"]["tools"]}
        self.assertIn("stitch_to_native", names)
        self.assertEqual(r[2]["result"]["prompts"][0]["name"], "convert_screen")
        self.assertTrue(r[3]["result"]["resources"])

    def test_convert_and_errors(self):
        r = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "stitch_to_native", "arguments": {"path": str(FIXTURE)}}},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "stitch_to_swiftui", "arguments": {"url": "http://insecure"}}})
        self.assertIn("struct StitchScreen", r[0]["result"]["content"][0]["text"])
        self.assertTrue(r[1]["result"]["isError"])


ENC = ROOT / "fixtures" / "fornada-encomendas.html"
ENC_FIXTURE = ENC


class TestOverlaysAndConfig(unittest.TestCase):
    def setUp(self):
        self.th, self.ir, _ = sn.parse(ENC.read_text())

    def test_swift_overlays_buttons_builtins(self):
        out = sn.SwiftEmitter(self.th, {}).screen(self.ir, "Enc")
        for s in ("safeAreaInset", "Button", "Color.clear"):
            self.assertIn(s, out)
        self.assertNotIn("tailwind.config", out)
        self.assertNotIn("StitchTheme.transparent", out)
        self.assertNotIn("StitchTheme.white", out)

    def test_config_icons_and_null_values(self):
        cfg = {"icons": {"receipt": "doc.text"}, "colors": {"primary": None}}
        out = sn.SwiftEmitter(self.th, cfg).screen(self.ir, "Enc")
        self.assertIn('"doc.text"', out)
        self.assertIn("StitchTheme.primary", out)

    def test_init_reports_unmapped_and_keeps_existing(self):
        cfg, unmapped = sn.init_config([self.ir], {"colors": {"primary": "DS.accent"}})
        self.assertEqual(cfg["colors"]["primary"], "DS.accent")
        self.assertNotIn("primary", unmapped["colors"])
        self.assertIn("receipt", unmapped["icons"])
        self.assertEqual(cfg["icons"]["close"] if "close" in cfg["icons"] else "xmark", "xmark")
        self.assertIn("output", cfg)


class TargetsTests(unittest.TestCase):
    ARGS = {"path": str(FIXTURE)}

    def test_default_is_swiftui_and_compose(self):
        out = mcp.call_tool("stitch_to_native", dict(self.ARGS))
        self.assertIn("```swift", out)
        self.assertIn("```kotlin", out)
        self.assertNotIn("```html", out)
        self.assertEqual(sn.resolve_targets(None, {}), ("swiftui", "compose"))

    def test_swiftui_only_has_no_kotlin_and_no_compose_theme(self):
        out = mcp.call_tool("stitch_to_native", {**self.ARGS, "targets": ["swiftui"]})
        self.assertIn("```swift", out)
        for never in ("```kotlin", "@Composable", "androidx.compose", "Color(0xFF"):
            self.assertNotIn(never, out)

    def test_init_config_swiftui_only_has_no_compose_keys(self):
        cfg, unmapped = sn.init_config([self.ir()], {}, ["swiftui"])
        self.assertNotIn("iconsCompose", cfg)
        self.assertNotIn("compose", cfg["output"])
        self.assertEqual(cfg["targets"], ["swiftui"])
        self.assertIn("icons", unmapped)
        text = mcp.call_tool("init_config", {**self.ARGS, "targets": ["swiftui"]})
        self.assertNotIn("iconsCompose", text)

    def test_init_config_default_keeps_both_and_never_deletes(self):
        cfg, _ = sn.init_config([self.ir()], {})
        self.assertIn("iconsCompose", cfg)
        self.assertEqual(list(cfg["output"]), ["swiftui", "compose"])
        self.assertNotIn("targets", cfg)
        kept, _ = sn.init_config([self.ir()], {"iconsCompose": {"x": "Icons.X"}, "output": {"compose": "app"}}, "swiftui,html")
        self.assertEqual(kept["iconsCompose"], {"x": "Icons.X"})
        self.assertEqual(kept["output"]["compose"], "app")
        self.assertIn("iconsHtml", kept)
        self.assertIn("html", kept["output"])

    def test_unknown_target_lists_valid_ones(self):
        with self.assertRaises(ValueError) as cm:
            sn.resolve_targets(["swiftui", "flutter"], {})
        self.assertIn("flutter", str(cm.exception))
        for t in ("swiftui", "compose", "html"):
            self.assertIn(t, str(cm.exception))
        with self.assertRaises(ValueError):
            mcp.call_tool("stitch_to_native", {**self.ARGS, "targets": ["nope"]})

    def test_argument_overrides_config(self):
        cfg = {"targets": ["swiftui"]}
        only_cfg = mcp.call_tool("stitch_to_native", {**self.ARGS, "config": cfg})
        self.assertNotIn("```kotlin", only_cfg)
        both = mcp.call_tool("stitch_to_native", {**self.ARGS, "config": cfg, "targets": ["compose", "html"]})
        self.assertIn("```kotlin", both)
        self.assertIn("```html", both)
        self.assertNotIn("```swift", both)

    def test_config_discovery_walks_up_and_stops_at_first(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            deep = root / "a" / "b"
            deep.mkdir(parents=True)
            screen = deep / "screen.html"
            screen.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            (root / sn.CONFIG_FILE).write_text(json.dumps({"targets": ["swiftui"], "colors": {"#12241c": "DS.far"}}))
            self.assertEqual(mcp.load_cfg({"path": str(screen)})["colors"], {"#12241c": "DS.far"})
            out = mcp.call_tool("stitch_to_native", {"path": str(screen)})
            self.assertIn("DS.far", out)
            self.assertNotIn("```kotlin", out)
            (root / "a" / sn.CONFIG_FILE).write_text(json.dumps({"colors": {"#12241c": "DS.near"}}))
            self.assertEqual(mcp.load_cfg({"path": str(screen)})["colors"], {"#12241c": "DS.near"})
            self.assertEqual(mcp.load_cfg({"path": str(screen), "config": {"x": 1}}), {"x": 1})
            self.assertEqual(mcp.load_cfg({"html": "<p>"}), {})

    def ir(self):
        return sn.parse(FIXTURE.read_text(encoding="utf-8"))[1]


class HtmlTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.th, cls.ir, _ = sn.parse(FIXTURE.read_text(encoding="utf-8"))
        cls.out = sn.HtmlEmitter(cls.th, {}).screen(cls.ir, "MatchStats")

    def test_golden_match_stats(self):
        self.assertEqual(self.out.strip(), (ROOT / "examples" / "MatchStats.html").read_text(encoding="utf-8").strip())

    def test_golden_orders_list(self):
        th, ir, _ = sn.parse(ENC_FIXTURE.read_text(encoding="utf-8"))
        out = sn.HtmlEmitter(th, {}).screen(ir, "OrdersList")
        self.assertEqual(out.strip(), (ROOT / "examples" / "OrdersList.html").read_text(encoding="utf-8").strip())

    def test_self_contained(self):
        low = self.out.lower()
        for never in ("<script", "cdn", "tailwind", "fonts.googleapis", "@import", "<link"):
            self.assertNotIn(never, low)
        self.assertEqual(low.count("<style>"), 1)
        self.assertIn("--color-primary: #53f493", self.out)
        self.assertIn("<h2", self.out)

    def test_icons_and_color_mapping(self):
        th, ir, _ = sn.parse(ENC_FIXTURE.read_text(encoding="utf-8"))
        em = sn.HtmlEmitter(th, {"iconsHtml": {"person": "<svg viewBox=\"0 0 1 1\"></svg>", "receipt": "R"},
                                 "colors": {"primary": "DS.Color.accent", "surface": "var(--brand-surface)"}})
        out = em.screen(ir, "X")
        self.assertIn('data-icon="person" aria-hidden="true"><svg', out)
        self.assertIn(">R</span>", out)
        self.assertNotIn("receipt", em.unmapped_icons)
        self.assertIn("bakery_dining", em.unmapped_icons)
        self.assertIn("var(--brand-surface)", out)
        self.assertNotIn("DS.Color.accent", out)

    def test_state_mode_errors(self):
        with self.assertRaises(ValueError):
            mcp.call_tool("stitch_to_html", {"path": str(ENC_FIXTURE), "mode": "state"})
        r = subprocess.run([sys.executable, str(ROOT / "stitch_native.py"), "html", str(ENC_FIXTURE), "--mode", "state"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("layout mode only", r.stderr)
        out = mcp.call_tool("stitch_to_native", {"path": str(ENC_FIXTURE), "mode": "state", "targets": ["swiftui", "html"]})
        self.assertIn("```swift", out)
        self.assertNotIn("```html", out)
        self.assertIn("warning: html target skipped", out)

    def test_mcp_html_tool_and_tokens(self):
        page = mcp.call_tool("stitch_to_html", {"path": str(FIXTURE)})
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn(":root {", mcp.call_tool("extract_tokens", {"path": str(FIXTURE), "platform": "html"}))
        self.assertIn("```css", mcp.call_tool("stitch_to_native", {"path": str(FIXTURE), "targets": "html"}))


class ReleaseTests(unittest.TestCase):
    def test_versions_agree(self):
        import re
        ver = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        server = json.loads((ROOT / "server.json").read_text())
        self.assertEqual(server["version"], ver)
        self.assertEqual([p["version"] for p in server["packages"]], [ver] * len(server["packages"]))
        self.assertEqual(mcp.VERSION, ver)

    def test_readme_carries_mcp_name(self):
        server = json.loads((ROOT / "server.json").read_text())
        self.assertIn(f"mcp-name: {server['name']} -->", (ROOT / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()


GLASS_FIXTURE = ROOT / "fixtures" / "fornada-glass-header.html"
GLASS_FIXTURE_B = ROOT / "fixtures" / "fornada-glass-ios-b.html"
GLASS_CFG = {"glass": "native"}


def glass_nodes(ir):
    """Every IR node (box or text) that carries a `glass` style."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            for key in ("style", "box"):
                if isinstance(x.get(key), dict) and x[key].get("glass"):
                    found.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(ir)
    return found


def gs(node):
    """The style dict holding the glass (text nodes keep their box style apart)."""
    return node["box"] if node.get("kind") == "text" else node["style"]


def snippet(body: str) -> str:
    return f"<html><body class=\"flex flex-col\">{body}</body></html>"


def glass_ir(body: str):
    return sn.parse(snippet(body), True)


class GlassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = GLASS_FIXTURE.read_text(encoding="utf-8")
        cls.th, cls.ir, cls.warn = sn.parse(cls.html, True)

    def render(self, target, ir=None, th=None, name="GlassHeader"):
        return sn.TARGETS[target]["emitter"](th or self.th, GLASS_CFG).screen(ir or self.ir, name)

    # flag off
    def test_flag_off_is_unchanged(self):
        th, ir, _ = sn.parse(self.html)
        self.assertNotIn("glass", json.dumps(ir))
        self.assertNotIn("_blur", json.dumps(ir))
        for target in ("swiftui", "compose", "html"):
            out = sn.TARGETS[target]["emitter"](th, {}).screen(ir, "X")
            self.assertNotIn("stitchGlass", out)
            self.assertNotIn("backdrop-filter", out)
            self.assertNotIn("surfaceContainer", out)
        self.assertEqual(sn.glass_enabled({"glass": "off"}), False)
        self.assertEqual(sn.glass_enabled(None), False)
        self.assertEqual(sn.glass_enabled(GLASS_CFG), True)

    # detection
    def test_header_and_badges_are_glass(self):
        nodes = glass_nodes(self.ir)
        self.assertEqual(len(nodes), 3)  # header bar, "Fornos" badge, hero "Massa mae" badge
        header = next(n for n in nodes if n.get("tag") == "header")
        g = header["style"]["glass"]
        self.assertEqual(g["blur"], 40)  # backdrop-blur-2xl
        self.assertIsNone(g["tint"])  # a near-white fill is no tint
        self.assertNotIn("bg", header["style"])  # the fake fill is gone

    def test_inner_header_layer_is_flattened(self):
        header = next(n for n in glass_nodes(self.ir) if n.get("tag") == "header")
        inner = header["children"][0]
        self.assertNotIn("glass", inner["style"])  # glass over glass: not a second glass
        self.assertNotIn("bg", inner["style"])  # its fake fill is dropped
        self.assertEqual(inner["style"].get("divider"), "b")  # a non-white divider stays

    def test_blur_less_chips_and_opaque_cta_are_not_glass(self):
        swift = self.render("swiftui")
        self.assertEqual(swift.count(".stitchGlass("), 3)
        self.assertIn("Color.white.opacity(0.9), in: Capsule())", swift)  # chips keep their literal fill

    def test_light_border_is_dropped_and_tint_kept(self):
        _, ir = glass_ir('<div class="rounded-xl bg-black/30 backdrop-blur-md border border-white/20"><span class="text-sm">x</span></div>')[:2]
        (node,) = glass_nodes(ir)
        st = gs(node)
        g = st["glass"]
        self.assertEqual((g["blur"], g["tint"]["hex"], g["tint"]["alpha"]), (12, "000000", 0.3))
        self.assertNotIn("border", st)
        self.assertNotIn("bg", st)
        self.assertEqual(st["radius"], 12)  # the shape stays

    def test_border_only_glass(self):
        ir = glass_ir('<div class="rounded-full backdrop-blur-sm border border-white/30 p-2"><span class="text-sm">x</span></div>')[1]
        (node,) = glass_nodes(ir)
        self.assertIsNone(gs(node)["glass"]["fill"])
        self.assertEqual(gs(node)["glass"]["border"]["alpha"], 0.3)

    def test_blur_only_overlay_is_not_glass(self):
        ir = glass_ir('<div class="p-4 backdrop-blur-md"><span class="text-sm">x</span></div>'
                      '<div class="absolute inset-0 backdrop-blur-sm"></div>')[1]
        self.assertEqual(glass_nodes(ir), [])
        self.assertNotIn("_blur", json.dumps(ir))
        # opaque or non-light borders do not make glass either
        ir = glass_ir('<div class="p-4 backdrop-blur-md bg-white border border-[#5B8DC9]/20"><span class="text-sm">x</span></div>')[1]
        self.assertEqual(glass_nodes(ir), [])

    def test_translucent_fill_without_blur_is_not_glass(self):
        ir = glass_ir('<div class="p-4 bg-white/70 border border-white/20"><span class="text-sm">x</span></div>')[1]
        self.assertEqual(glass_nodes(ir), [])

    # decoration layers
    def test_decoration_layer_removed_next_to_glass(self):
        # the hero scrim (absolute inset-0 gradient) is an empty sibling of the glass badge
        def empty_divs(ir):
            n = 0
            stack = [ir]
            while stack:
                x = stack.pop()
                if isinstance(x, dict):
                    n += x.get("kind") == "box" and not x.get("children") and x.get("tag") == "div"
                    stack += list(x.values())
                elif isinstance(x, list):
                    stack += x
            return n
        _, off, _ = sn.parse(self.html)
        self.assertEqual(empty_divs(off) - empty_divs(self.ir), 1)
        self.assertNotIn('"deco"', json.dumps(self.ir))

    def test_decoration_layer_inside_glass_and_beside_it(self):
        ir = glass_ir('<div class="relative rounded-2xl bg-white/60 backdrop-blur-xl border border-white/30">'
                      '<div class="absolute inset-0 bg-gradient-to-b from-white/40 to-transparent"></div>'
                      '<div class="absolute inset-0 backdrop-blur-md bg-white/10"></div>'
                      '<span class="text-sm">x</span></div>')[1]
        (node,) = glass_nodes(ir)
        self.assertEqual(node["kind"], "text")  # only the text is left, so the box collapsed into it
        self.assertNotIn("gradient", json.dumps(ir))
        self.assertEqual(json.dumps(ir).count('"children": []'), 0)
        # a decoration layer with no glass around it is left alone
        ir = glass_ir('<div class="relative p-4"><div class="absolute inset-0 bg-gradient-to-t from-black/50"></div><span class="text-sm">x</span></div>')[1]
        self.assertEqual(len(ir["children"][0]["children"]), 2)

    def test_layer_with_content_is_not_decoration(self):
        ir = glass_ir('<div class="rounded-xl bg-white/60 backdrop-blur-md"><div class="absolute inset-0 bg-black/20"><span class="text-sm">keep</span></div></div>')[1]
        self.assertIn("keep", json.dumps(ir))

    def test_opaque_inset_layer_is_not_decoration(self):
        ir = glass_ir('<div class="rounded-xl bg-white/60 backdrop-blur-md"><div class="absolute inset-0 bg-surface"></div><span class="text-sm">x</span></div>')[1]
        self.assertEqual(len(glass_nodes(ir)), 1)
        self.assertEqual(len(glass_nodes(ir)[0]["children"]), 2)

    # emitters
    def test_swiftui_glass_and_availability_wrapper(self):
        out = self.render("swiftui")
        self.assertIn(".stitchGlass(in: Capsule())", out)
        self.assertEqual(out.count("private struct StitchGlass<S: Shape>: ViewModifier"), 1)
        self.assertIn("if #available(iOS 26, *)", out)
        self.assertIn("content.glassEffect(.regular, in: shape)", out)
        self.assertIn(".regular.tint(tint)", out)
        self.assertIn("shape.fill(.ultraThinMaterial)", out)
        self.assertNotIn("StitchGlassContainer", out)

    def test_swiftui_tint_and_container(self):
        th, ir, _ = glass_ir('<div class="flex gap-2"><div class="rounded-full bg-white/70 backdrop-blur-md border border-white/20"><span class="text-sm">A</span></div>'
                             '<div class="rounded-full bg-black/30 backdrop-blur-md"><span class="text-sm">B</span></div></div>')
        out = sn.SwiftEmitter(th, GLASS_CFG).screen(ir, "V")
        self.assertIn(".stitchGlass(in: Capsule(), tint: Color.black.opacity(0.3))", out)
        self.assertEqual(out.count("StitchGlassContainer {"), 1)
        self.assertIn("GlassEffectContainer { content }", out)
        one = sn.SwiftEmitter(th, GLASS_CFG).screen(glass_ir('<div class="rounded-full bg-white/70 backdrop-blur-md"><span class="text-sm">A</span></div>')[1], "V")
        self.assertNotIn("StitchGlassContainer", one)

    def test_swiftui_modifier_only_in_files_that_use_glass(self):
        em = sn.SwiftEmitter(self.th, GLASS_CFG)
        self.assertIn("StitchGlass", em.screen(self.ir, "A"))
        plain = em.screen(glass_ir('<p class="text-sm">no glass</p>')[1], "B")  # same emitter, next screen
        self.assertNotIn("StitchGlass", plain)

    def test_compose_translucent_surface_and_hairline(self):
        out = self.render("compose", name="GlassHeaderScreen")
        self.assertIn("MaterialTheme.colorScheme.surfaceContainer.copy(alpha = 0.75f)", out)
        self.assertIn("border(1.dp, Color.White.copy(alpha = 0.2f), RectangleShape)", out)
        self.assertIn("CircleShape).background(MaterialTheme.colorScheme.surfaceContainer.copy(alpha = 0.9f), CircleShape)", out)
        self.assertNotIn("blur", out.lower())
        th, ir, _ = glass_ir('<div class="rounded-xl bg-black/30 backdrop-blur-md"><span class="text-sm">B</span></div>')
        tinted = sn.ComposeEmitter(th, GLASS_CFG).screen(ir, "S")
        self.assertIn("Color.Black.copy(alpha = 0.3f), RoundedCornerShape(12.dp))", tinted)

    def test_html_keeps_backdrop_filter(self):
        out = self.render("html")
        self.assertIn("backdrop-filter: blur(40px)", out)
        self.assertIn("-webkit-backdrop-filter: blur(12px)", out)
        self.assertIn("background-color: rgba(255, 255, 255, 0.9); border: 1px solid rgba(255, 255, 255, 0.6)", out)

    def test_ios_variant_b_glass(self):
        th, ir, _ = sn.parse(GLASS_FIXTURE_B.read_text(encoding="utf-8"), True)
        nodes = glass_nodes(ir)
        self.assertEqual(len(nodes), 4)  # price badge, two grid price pills, floating tab bar
        self.assertTrue(any(gs(n).get("radius") >= 999 for n in nodes if n.get("tag") == "nav"))
        swift = sn.SwiftEmitter(th, GLASS_CFG).screen(ir, "V")
        self.assertIn(".stitchGlass(in: Capsule())", swift)
        self.assertEqual(swift.count("#available(iOS 26, *)"), 1)

    # goldens
    def test_goldens(self):
        for target, name, golden in (("swiftui", "GlassHeaderView", "GlassHeaderView.swift"),
                                     ("compose", "GlassHeaderScreen", "GlassHeaderScreen.kt"),
                                     ("html", "GlassHeader", "GlassHeader.html")):
            out = sn.TARGETS[target]["emitter"](self.th, GLASS_CFG).screen(self.ir, name)
            self.assertEqual(out.strip(), (ROOT / "examples" / golden).read_text(encoding="utf-8").strip(), golden)

    def test_cli_and_mcp_read_the_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            cfg.write_text(json.dumps(GLASS_CFG))
            run = lambda *extra: subprocess.run([sys.executable, str(ROOT / "stitch_native.py"), "swiftui", str(GLASS_FIXTURE), *extra],
                                                capture_output=True, text=True, check=True).stdout
            self.assertIn(".stitchGlass(", run("--config", str(cfg)))
            self.assertNotIn(".stitchGlass(", run())
        on = mcp.call_tool("stitch_to_swiftui", {"html": self.html, "config": GLASS_CFG})
        off = mcp.call_tool("stitch_to_swiftui", {"html": self.html})
        self.assertIn(".stitchGlass(", on)
        self.assertNotIn(".stitchGlass(", off)
        self.assertIn("backdrop-filter", mcp.call_tool("stitch_to_html", {"html": self.html, "config": GLASS_CFG}))
        self.assertIn('"glass"', mcp.call_tool("stitch_to_ir", {"html": self.html, "config": GLASS_CFG}))

    # real exports: parser robustness found while fetching the fixtures
    def test_tailwind_config_trailing_semicolon_and_single_quotes(self):
        cfg = sn.parse_tailwind_config("<script id='x'>tailwind.config = { theme: { extend: { colors: { 'on-x': '#112233' }, "
                                       "fontFamily: { sans: ['\"Inter\"', 'sans-serif'] } } } };</script>")
        self.assertEqual(cfg["colors"]["on-x"], "#112233")
        self.assertEqual(cfg["fontFamily"]["sans"][0], '"Inter"')
