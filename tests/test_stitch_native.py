import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import stitch_native as sn  # noqa: E402

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



class StateModeTests(unittest.TestCase):
    def gen(self, target, name):
        return subprocess.run([sys.executable, str(ROOT / "stitch_native.py"), target,
                               str(ROOT / "fixtures" / "fornada-encomendas.html"), "--name", name, "--mode", "state",
                               "--config", str(ROOT / "fixtures" / "fornada.stitch-native.json")],
                              capture_output=True, text=True, timeout=60, check=True).stdout

    def test_swift_state_golden_and_rules(self):
        out = self.gen("swiftui", "OrdersListView")
        self.assertEqual(out.strip(), (ROOT / "examples" / "OrdersListView.swift").read_text().strip())
        for must in ("struct OrdersListViewState", "Identifiable", "Picker(", "onRepeat", "#Preview(\"Dark\")",
                     "var brandName: String", "var lines: [Line]", "var status: OrderStatus", "LazyVStack(",
                     ".font(.system(.body", "ordersList.selectedItems", 'Locale(identifier: "pt")', "var storeName: String",
                     "ForEach(OrdersListViewState.OrderStatus.allCases", "ForEach(state.lines)", "struct Line: Identifiable"):
            self.assertIn(must, out)
        self.assertNotIn("ViewModel", out)
        self.assertNotIn("UseCase", out)
        self.assertNotIn("lojaAlcobaca", out)

    def test_compose_state_golden_and_rules(self):
        out = self.gen("compose", "OrdersListScreen")
        self.assertEqual(out.strip(), (ROOT / "examples" / "OrdersListScreen.kt").read_text().strip())
        for must in ("data class OrdersListScreenState", "SegmentedButton(", "onRepeat: (", "rememberSaveable",
                     "stringResource(R.string.", "UI_MODE_NIGHT_YES",
                     "List<Line>", "enum class OrderStatus", "OrderStatus.entries.forEach", "state.lines.forEach",
                     "val storeName: String"):
            self.assertIn(must, out)
        for never in ("joinToString", "lojaAlcobaca"):
            self.assertNotIn(never, out)
        for must in ():
            self.assertIn(must, out)
        self.assertNotIn("ViewModel", out)

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


if __name__ == "__main__":
    unittest.main()
