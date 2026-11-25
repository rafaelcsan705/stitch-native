#!/usr/bin/env python3
"""stitch-native: Stitch HTML (Tailwind) -> IR (JSON) -> SwiftUI / Jetpack Compose.

Usage:
  python3 stitch_native.py ir      <screen.html>              # print the IR
  python3 stitch_native.py swiftui <screen.html> [--map m.json] [--name ScreenView]
  python3 stitch_native.py compose <screen.html> [--map m.json] [--name Screen]
  python3 stitch_native.py tokens  <screen.html>              # Theme.swift from tailwind.config
  python3 stitch_native.py tokens-kotlin <screen.html>        # Theme.kt from tailwind.config
  python3 stitch_native.py init    <screen.html>...           # write/merge stitch-native.json, list unmapped

Config: --config c.json (alias --map), else ./stitch-native.json if present. Keys: colors, fonts,
icons (SF Symbols), iconsCompose, preview.colorScheme, output. null = unmapped.

Standard library only. Prototype: covers the Tailwind subset Stitch emits on mobile screens.
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser

# ---------------------------------------------------------------- config

TW_SIZES = {  # Tailwind default text sizes (px)
    "xs": 12, "sm": 14, "base": 16, "lg": 18, "xl": 20, "2xl": 24, "3xl": 30,
}
TW_WEIGHTS = {
    "thin": 100, "light": 300, "normal": 400, "medium": 500,
    "semibold": 600, "bold": 700, "extrabold": 800, "black": 900,
}
TW_RADIUS = {"": 4, "sm": 2, "md": 6, "lg": 8, "xl": 12, "2xl": 16, "3xl": 24, "full": 9999}


def parse_tailwind_config(html: str) -> dict:
    m = re.search(r"tailwind\.config\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        return {}
    js = m.group(1)
    js = re.sub(r"//.*", "", js)
    js = re.sub(r"([{,]\s*)([A-Za-z_][\w-]*)\s*:", r'\1"\2":', js)  # quote bare keys
    js = re.sub(r",(\s*[}\]])", r"\1", js)  # trailing commas
    try:
        cfg = json.loads(js)
    except json.JSONDecodeError as e:
        raise SystemExit(f"cannot parse tailwind.config: {e}")
    return cfg.get("theme", {}).get("extend", {})


def to_px(v: str) -> float:
    v = v.strip()
    if v.endswith("rem"):
        return float(v[:-3]) * 16
    if v.endswith("px"):
        return float(v[:-2])
    return float(v)


class Theme:
    def __init__(self, ext: dict):
        self.colors = {k: v.lower() for k, v in ext.get("colors", {}).items()}
        self.spacing = {k: to_px(v) for k, v in ext.get("spacing", {}).items()}
        self.radius = dict(TW_RADIUS)
        for k, v in ext.get("borderRadius", {}).items():
            self.radius["" if k == "DEFAULT" else k] = to_px(v)
        self.font_family = {k: v[0] for k, v in ext.get("fontFamily", {}).items()}
        self.font_size = {}
        for k, v in ext.get("fontSize", {}).items():
            size, opts = (v[0], v[1]) if isinstance(v, list) else (v, {})
            self.font_size[k] = {"size": to_px(size), "weight": int(opts.get("fontWeight", 400)),
                                 "lineHeight": opts.get("lineHeight")}

    def space(self, token: str) -> float | None:
        if token.startswith("[") and token.endswith("]"):
            return to_px(token[1:-1])
        if token in self.spacing:
            return self.spacing[token]
        try:
            return float(token) * 4
        except ValueError:
            return None

    def color(self, token: str) -> dict | None:
        alpha = None
        if "/" in token:
            token, a = token.rsplit("/", 1)
            alpha = int(a) / 100
        if token.startswith("[#") and token.endswith("]"):
            return {"hex": token[2:-1].lower(), "alpha": alpha, "token": None}
        if token in self.colors:
            return {"hex": self.colors[token], "alpha": alpha, "token": token}
        if token in ("white", "black", "transparent"):
            return {"hex": {"white": "ffffff", "black": "000000", "transparent": "000000"}[token],
                    "alpha": 0 if token == "transparent" else alpha, "token": None, "builtin": token}
        return None


# ---------------------------------------------------------------- HTML -> DOM

VOID = {"img", "br", "hr", "meta", "link", "input"}
SKIP = {"script", "style", "head", "title"}


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children: list = []  # Node | str


class DomBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", [])
        self.cur = self.root
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip -= 1
            return
        if self.skip or tag in VOID:
            return
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.cur.children.append(" ".join(data.split()))


# ---------------------------------------------------------------- DOM -> IR

def resolve_classes(classes: list[str], style: str, th: Theme, warn: list) -> dict:
    s: dict = {"pad": {}, "margin": {}}
    for c in classes:
        if ":" in c:  # hover:, dark:, active: -> not a static design property
            continue
        if c in ("flex", "inline-flex"):
            s.setdefault("layout", "row")
        elif c == "flex-col":
            s["layout"] = "column"
        elif c == "grid":
            s["layout"] = "grid"
        elif m := re.fullmatch(r"grid-cols-(\d+)", c):
            s["cols"] = int(m.group(1))
        elif m := re.fullmatch(r"col-span-(\d+)", c):
            s["span"] = int(m.group(1))
        elif m := re.fullmatch(r"gap-(.+)", c):
            s["gap"] = th.space(m.group(1))
        elif m := re.fullmatch(r"justify-(between|center|start|end|around)", c):
            s["justify"] = m.group(1)
        elif m := re.fullmatch(r"items-(center|start|end|baseline)", c):
            s["align"] = m.group(1)
        elif m := re.fullmatch(r"(p|px|py|pt|pb|pl|pr)-(.+)", c):
            v = th.space(m.group(2))
            if v is None:  # e.g. pb-safe: the native safe area handles it
                continue
            sides = {"p": "tblr", "px": "lr", "py": "tb", "pt": "t", "pb": "b", "pl": "l", "pr": "r"}[m.group(1)]
            for side in sides:
                s["pad"][side] = v
        elif m := re.fullmatch(r"(m|mx|my|mt|mb|ml|mr)-(.+)", c):
            if m.group(2) == "auto":
                continue
            v = th.space(m.group(2))
            sides = {"m": "tblr", "mx": "lr", "my": "tb", "mt": "t", "mb": "b", "ml": "l", "mr": "r"}[m.group(1)]
            for side in sides:
                s["margin"][side] = v
        elif m := re.fullmatch(r"([wh])-(.+)", c):
            key = "width" if m.group(1) == "w" else "height"
            s[key] = "fill" if m.group(2) == "full" else th.space(m.group(2))
        elif m := re.fullmatch(r"max-w-\[(.+)\]", c):
            s["maxWidth"] = to_px(m.group(1))
        elif m := re.fullmatch(r"rounded(?:-([lrtb]))?(?:-(.+))?", c):
            key = m.group(2) or ""
            if key.startswith("["):
                r = to_px(key[1:-1])
            elif key in th.radius:
                r = th.radius[key]
            else:
                try:
                    r = float(key)  # Stitch writes rounded-10 (not real Tailwind)
                    warn.append(f"non-Tailwind radius class '{c}' read as {r}pt")
                except ValueError:
                    warn.append(f"unknown radius '{c}'")
                    continue
            if m.group(1):
                s.setdefault("corners", {})[m.group(1)] = r
            else:
                s["radius"] = r
        elif m := re.fullmatch(r"bg-(.+)", c):
            col = th.color(m.group(1))
            if col:
                s["bg"] = col
            elif not m.group(1).startswith("gradient"):
                warn.append(f"unknown bg '{c}'")
        elif c == "border":
            s.setdefault("border", {"width": 1})
        elif m := re.fullmatch(r"border-([btlr])", c):
            s["divider"] = m.group(1)
        elif m := re.fullmatch(r"border-(.+)", c):
            col = th.color(m.group(1))
            if col:
                s.setdefault("border", {"width": 1})["color"] = col
                s["borderColor"] = col
        elif m := re.fullmatch(r"text-(.+)", c):
            v = m.group(1)
            if v in ("center", "left", "right"):
                s["textAlign"] = v
            elif v in th.font_size:
                s["fontToken"] = v
            elif v in TW_SIZES:
                s["fontSize"] = TW_SIZES[v]
            elif px := re.fullmatch(r"\[(\d+(?:\.\d+)?)px\]", v):
                s["fontSize"] = float(px.group(1))
            elif col := th.color(v):
                s["color"] = col
            else:
                warn.append(f"unknown text class '{c}'")
        elif m := re.fullmatch(r"font-(.+)", c):
            v = m.group(1)
            if v in TW_WEIGHTS:
                s["weight"] = TW_WEIGHTS[v]
            elif v in th.font_family:
                s["family"] = th.font_family[v]
                s.setdefault("familyToken", v)
        elif c == "uppercase":
            s["uppercase"] = True
        elif c == "truncate":
            s["lineLimit"] = 1
        elif m := re.fullmatch(r"divide-\[#(\w+)\](?:/(\d+))?|divide-y", c):
            s["dividers"] = True
    if m := re.search(r"width:\s*([\d.]+)%", style or ""):
        s["widthPct"] = float(m.group(1)) / 100
    return s


def _has_nav(node) -> bool:
    return any(isinstance(c, Node) and (c.tag == "nav" or _has_nav(c)) for c in node.children)


def overlay_role(node, classes: list[str]) -> str | None:
    """Role of a `fixed` element: topBar, bottomBar, sheet or toast. None = part of the scroll content."""
    if "fixed" not in classes:
        return None
    bottom = any(re.fullmatch(r"bottom-.+", c) for c in classes)
    if node.tag == "dialog" or node.attrs.get("role") == "dialog":
        return "sheet"
    if node.tag == "nav" or _has_nav(node):
        return "bottomBar" if bottom else "topBar"
    if node.tag in ("aside",) or node.attrs.get("role") in ("status", "alert"):
        return "toast"
    if "top-0" in classes or node.tag == "header":
        return "topBar"
    if "bottom-0" in classes:
        return "bottomBar"
    return "toast"


def build_ir(node, th: Theme, warn: list, inherited: dict | None = None, overlays: list | None = None):
    inherited = inherited or {}
    if isinstance(node, str):
        return {"kind": "text", "text": node, "style": dict(inherited)}
    classes = node.attrs.get("class", "").split()
    if overlays is not None and (role := overlay_role(node, classes)):
        bare = Node(node.tag, {**node.attrs, "class": " ".join(c for c in classes if c != "fixed")}, node.parent)
        bare.children = node.children
        inner = build_ir(bare, th, warn, inherited, overlays)
        if inner:
            overlays.append({"role": role, "id": node.attrs.get("id") or f"{role}{len(overlays) + 1}", "node": inner})
        return None
    if node.tag == "svg":
        return {"kind": "vector", "style": resolve_classes(classes, node.attrs.get("style", ""), th, warn),
                "label": node.attrs.get("aria-label")}
    if node.tag in ("button", "a"):
        a = node.attrs
        bare = Node("div", a, node.parent)
        bare.children = node.children
        content = build_ir(bare, th, warn, inherited, overlays)
        if not content:
            return None
        if content["kind"] == "box":
            content["tag"] = node.tag
        return {"kind": "button", "tag": node.tag, "content": content, "style": content.get("style", {}),
                "action": a.get("onclick") or a.get("href"), "label": a.get("aria-label"),
                "current": a.get("aria-current") is not None}
    if "material-symbols-outlined" in classes:
        name = "".join(ch for ch in node.children if isinstance(ch, str))
        return {"kind": "icon", "material": name, "style": resolve_classes(classes, "", th, warn)}
    style = resolve_classes(classes, node.attrs.get("style", ""), th, warn)
    text_keys = ("color", "fontToken", "fontSize", "weight", "family", "familyToken", "textAlign", "uppercase", "lineLimit")
    inh = dict(inherited)
    for k in text_keys:
        if k in style:
            inh[k] = style[k]
    if node.tag == "img":
        return {"kind": "image", "src": node.attrs.get("src"), "alt": node.attrs.get("data-alt") or node.attrs.get("alt"), "style": style}
    kids = [build_ir(ch, th, warn, inh, overlays) for ch in node.children]
    kids = [k for k in kids if k]
    # an element whose only content is text becomes a text node carrying the box style
    if len(kids) == 1 and kids[0]["kind"] == "text" and "layout" not in style:
        t = kids[0]
        box = {k: v for k, v in style.items() if k not in text_keys}
        return {"kind": "text", "text": t["text"], "style": t["style"], "box": box, "tag": node.tag}
    out = {"kind": "box", "tag": node.tag, "style": style, "children": kids}
    if node.attrs.get("id"):
        out["id"] = node.attrs["id"]
    return out


def parse(html: str):
    th = Theme(parse_tailwind_config(html))
    b = DomBuilder()
    b.feed(html)
    body = next((c for c in b.root.children if isinstance(c, Node) and c.tag == "html"), b.root)
    body = next((c for c in body.children if isinstance(c, Node) and c.tag == "body"), body)
    warn: list = []
    overlays: list = []
    ir = build_ir(body, th, warn, None, overlays)
    if overlays:
        ir["overlays"] = overlays
    m = re.search(r"<html[^>]*class=\"([^\"]*)\"", html, re.I)
    th.scheme = "dark" if m and "dark" in m.group(1).split() else "light"
    return th, ir, warn


# ---------------------------------------------------------------- IR -> SwiftUI

def camel(token: str) -> str:
    parts = re.split(r"[-_]", token)
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


# ---------------------------------------------------------------- state mode (IR annotations)

PRICE_RE = re.compile(r"^(\d+)[,.](\d{2})\s?([€$£])$")
CURRENCY = {"€": "EUR", "$": "USD", "£": "GBP"}
CALL_RE = re.compile(r"^\s*(\w+)\(\s*'([^']*)'\s*\)\s*;?\s*$")
NOARG_RE = re.compile(r"^\s*(\w+)\(\s*\)\s*;?\s*$")
DATE_RE = re.compile(r"(?i)\d{1,2}[:h]\d{2}|\b(ontem|hoje|amanhã|yesterday|today|tomorrow|janeiro|fevereiro|março|"
                     r"abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|jan|feb|mar|apr|may|jun|"
                     r"jul|aug|sep|oct|nov|dec)\b")


def _ascii(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _words(s: str) -> list[str]:
    stop = {"de", "da", "do", "das", "dos", "e", "a", "o", "the", "of", "and", "em", "para", "com"}
    return [w.lower() for w in re.findall(r"[A-Za-z]+", _ascii(s)) if w.lower() not in stop]


def _lower_camel(words: list[str]) -> str:
    return (words[0] + "".join(w.capitalize() for w in words[1:])) if words else ""


def _split_camel(s: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", s)]


def _sig(n: dict) -> str:
    k = n["kind"]
    if k == "text":
        return "T"
    if k in ("icon", "vector", "image"):
        return k[0].upper()
    if k == "button":
        return "B(" + _sig(n["content"]) + ")"
    return f"{n.get('tag')}:{n['style'].get('layout')}[" + ",".join(_sig(c) for c in n["children"]) + "]"


def _style_sig(n: dict) -> str:
    parts = [json.dumps(n.get("style", {}), sort_keys=True, default=str), json.dumps(n.get("box", {}), sort_keys=True, default=str)]
    sub = [n["content"]] if n["kind"] == "button" else n.get("children", [])
    return "|".join(parts + [_style_sig(c) for c in sub])


def _leaves(n: dict) -> list[dict]:
    """Texts, icons and buttons in document order (the positions a row template can vary)."""
    if n["kind"] in ("text", "icon"):
        return [n]
    if n["kind"] == "button":
        return [n] + _leaves(n["content"])
    return [x for c in n.get("children", []) for x in _leaves(c)]


TEXT_STYLES = [(34, "largeTitle"), (28, "title"), (22, "title2"), (20, "title3"), (17, "body"),
               (16, "callout"), (15, "subheadline"), (13, "footnote"), (12, "caption"), (11, "caption2")]


def text_style_for(size: float) -> str:
    """Nearest Dynamic Type text style, so fonts scale with the user's setting."""
    return min(TEXT_STYLES, key=lambda t: (abs(t[0] - size), -t[0]))[1]


class StateModel:
    """What `extract_state` found: fields, repeated groups, keys, callbacks, tabs. Emitters read it."""

    def __init__(self, name: str, cfg: dict, lang: str | None):
        sc = cfg.get("state", {}) or {}
        self.name = name
        self.type = name + "State"
        base = re.sub(r"(View|Screen)$", "", name) or name
        self.prefix = sc.get("prefix") or (base[:1].lower() + base[1:])
        self.rename = sc.get("rename", {}) or {}
        self.locale = sc.get("locale") or (lang or "en-US").replace("-", "_")
        self.timezone = sc.get("timezone")
        self.types = sc.get("types", {}) or {}
        self.key_over = sc.get("keys", {}) or {}      # source text or auto key -> final key
        self.store_field = sc.get("storeField") or "storeName"   # field for "Brand — Store" texts
        self.brand = set(sc.get("brand", []) or [])   # brand texts: bound to state.brandName, never baked in
        self.enums = sc.get("enums", {}) or {}        # name -> {cases: [source texts], type?, current?}
        self.fields: list[dict] = []        # top-level: {name, type, value, cents?, code?}
        self.groups: list[dict] = []        # {item, collection, fields: [...], rows: [[values]], handler}
        self.keys: dict[str, str] = {}      # key -> source text
        self._key_by_text: dict[str, str] = {}
        self.callbacks: dict[str, dict] = {}  # name -> {"item": Item | None, "fn": js fn}
        self.flags: set[str] = set()
        self.tabs: dict | None = None
        self.warnings: list[str] = []

    def unique(self, base: str, taken: set) -> str:
        base = self.rename.get(base, base) or "value"
        n, i = base, 2
        while n in taken:
            n, i = f"{base}{i}", i + 1
        taken.add(n)
        return n

    def key(self, text: str, hint: str | None = None) -> str:
        if text in self._key_by_text and not hint:
            return self._key_by_text[text]
        if text in self.key_over:
            k = self.key_over[text]
            self.keys[k] = text
            self._key_by_text.setdefault(text, k)
            return k
        slug = hint or _lower_camel(_words(text)[:3]) or "text"
        if (auto := f"{self.prefix}.{slug}") in self.key_over:
            k = self.key_over[auto]
            self.keys[k] = text
            self._key_by_text.setdefault(text, k)
            return k
        k, i = f"{self.prefix}.{slug}", 2
        while k in self.keys and self.keys[k] != text:
            k, i = f"{self.prefix}.{slug}{i}", i + 1
        self.keys[k] = text
        self._key_by_text.setdefault(text, k)
        return k


def _field_base(text: str) -> str:
    t = text.strip()
    if re.fullmatch(r"#\d+", t):
        return "number"
    if PRICE_RE.match(t):
        return "price"
    if DATE_RE.search(t):
        return "date"
    return _lower_camel(_words(t)[:2]) or "value"


def _value(text: str) -> dict:
    t = text.strip()
    if m := PRICE_RE.match(t):
        return {"type": "currency", "value": t, "cents": int(m.group(1)) * 100 + int(m.group(2)), "code": CURRENCY[m.group(3)]}
    return {"type": "string", "value": t}


def _find_overlay(fn: str, ovs: list) -> str | None:
    stem = re.sub(r"^(open|close|show|hide|toggle)", "", fn)
    stem = stem[:1].lower() + stem[1:]
    for o in ovs:
        if camel(re.sub(r"[^A-Za-z0-9_-]", "-", o["id"])).lower() == stem.lower():
            return o["id"]
    return None


def extract_state(ir: dict, cfg: dict, name: str, lang: str | None = None) -> StateModel:
    """Annotate the IR in place for state mode and return the model. Without this call nothing changes."""
    st = StateModel(name, cfg, lang)
    ovs = ir.get("overlays", [])
    taken: set = set()
    parent: dict = {}

    def link(n: dict, p: dict | None):
        parent[id(n)] = p
        for c in n.get("children", []) + ([n["content"]] if n.get("content") else []):
            link(c, n)

    link(ir, None)
    for o in ovs:
        link(o["node"], None)
    case_of = {t: (en, i) for en, e in st.enums.items() for i, t in enumerate(e.get("cases", []))}
    enum_cases = {en: [_lower_camel(_words(t)) or f"case{i + 1}" for i, t in enumerate(e.get("cases", []))]
                  for en, e in st.enums.items()}

    def enum_role(n: dict) -> str:
        # nearest ancestor holding 2+ case texts: all distinct = tracker labels; a repeat = the status chip
        p = parent.get(id(n))
        while p is not None:
            cs = [x["text"].strip() for x in _leaves(p) if x["kind"] == "text" and x["text"].strip() in case_of]
            if len(cs) >= 2:
                return "label" if len(cs) == len(set(cs)) else "chip"
            p = parent.get(id(p))
        return "chip"

    def mark_text(n: dict, scope: str, ftaken: set, fields: list, in_shell: bool):
        t = n["text"].strip()
        if not re.search(r"[A-Za-z0-9À-ÿ]", t):
            n["verbatim"] = True
            return
        if t in st.brand:
            if not any(f["name"] == "brandName" for f in st.fields):
                taken.add("brandName")
                st.fields.append({"name": "brandName", "type": "string", "value": t})
            n["bind"] = {"scope": "state", "field": "brandName", "type": "string"}
            return
        if t in case_of and scope == "state":
            en, i = case_of[t]
            case = enum_cases[en][i]
            if enum_role(n) == "label":
                n["key"] = st.key(t, f"{en}.{case}")
                return
            if not any(f["name"] == en for f in st.fields):
                taken.add(en)
                e = st.enums[en]
                cur = e.get("current") or t
                st.fields.append({"name": en, "type": "enum", "enum": en, "value": enum_cases[en][e["cases"].index(cur)]
                                  if cur in e["cases"] else case})
            for j, ct in enumerate(st.enums[en]["cases"]):
                st.key(ct, f"{en}.{enum_cases[en][j]}")
            n["bind"] = {"scope": "state", "field": en, "type": "enum"}
            return
        if in_shell and len(w := t.split()) >= 2 and all(x[:1].isupper() for x in w) and not re.search(r"\d", t):
            st.warnings.append(f"state: '{t}' in the top/bottom bar looks like a brand; list it in state.brand to bind it")
        if not in_shell and re.search(r"\d", t):
            v = _value(t)
            base = None
            for b in sorted(st.brand, key=len, reverse=True):   # "Brand — Store": a generic field, never a place name
                if t.startswith(b) and t[len(b):].strip(" —-·|,"):
                    base = st.store_field
                    break
            fname = st.unique(base or _field_base(t), ftaken)
            fields.append({"name": fname, **v})
            n["bind"] = {"scope": scope, "field": fname, "type": v["type"]}
        else:
            n["key"] = st.key(t)

    def handle_button(b: dict, in_row: str | None):
        act = (b.get("action") or "").strip()
        if m := CALL_RE.match(act):
            fn = m.group(1)
            word = _split_camel(fn)[0]
            cb = "on" + word.capitalize()
            if in_row:
                st.callbacks[cb] = {"item": in_row, "fn": fn}
                b["handler"] = {"callback": cb, "item": True}
                return cb
            st.callbacks.setdefault(cb, {"item": None, "fn": fn, "arg": "String"})
            b["handler"] = {"callback": cb, "arg": m.group(2)}
        elif m := NOARG_RE.match(act):
            fn = m.group(1)
            if (oid := _find_overlay(fn, ovs)) is not None:
                st.flags.add(oid)
                b["flag"] = {"overlay": oid, "value": not fn.startswith(("close", "hide"))}
            else:
                cb = "on" + fn[:1].upper() + fn[1:]
                st.callbacks.setdefault(cb, {"item": None, "fn": fn})
                b["handler"] = {"callback": cb}
        return None

    def detect_tabs(n: dict) -> bool:
        kids = n.get("children", [])
        calls = [CALL_RE.match((k.get("action") or "")) if k["kind"] == "button" else None for k in kids]
        if len(kids) < 2 or not all(calls) or len({c.group(1) for c in calls}) != 1 or st.tabs:
            return False
        cases = []
        for k, c in zip(kids, calls):
            first = next((x for x in _leaves(k["content"]) if x["kind"] == "text" and re.search(r"[A-Za-z]", x["text"])), None)
            label = first["text"].strip() if first else c.group(2)
            case = _lower_camel(_words(c.group(2))) or f"tab{len(cases) + 1}"
            cases.append({"case": case, "arg": c.group(2), "key": st.key(label, f"tab.{case}")})
        st.tabs = {"fn": calls[0].group(1), "cases": cases, "default": cases[0]["case"]}
        n["picker"] = True
        return True

    def row_group(n: dict) -> bool:
        kids = n.get("children", [])
        if len(kids) < 2 or any(k["kind"] != "box" for k in kids) or len({_sig(k) for k in kids}) != 1:
            return False
        rows = [_leaves(k) for k in kids]
        tmpl = rows[0]
        if not any(x["kind"] == "text" for x in tmpl):
            return False
        varying = [i for i in range(len(tmpl)) if tmpl[i]["kind"] in ("text", "icon")
                   and len({(r[i].get("text") or r[i].get("material") or "").strip() for r in rows}) > 1]
        if not varying:
            return False
        # item / collection names: from the row button's handler (repeatOrder -> Order / orders)
        handler = next((CALL_RE.match(x.get("action") or "") for x in tmpl if x["kind"] == "button"
                        and CALL_RE.match(x.get("action") or "")), None)
        noun = "".join(w.capitalize() for w in _split_camel(handler.group(1))[1:]) if handler else ""
        idx = len(st.groups) + 1
        item = st.rename.get(noun or f"Item{idx}", noun or f"Item{idx}")
        coll = st.unique((item[:1].lower() + item[1:]) + "s", taken)
        g = {"item": item, "collection": coll, "fields": [], "rows": [[] for _ in rows], "handlerArg": bool(handler)}
        ftaken: set = {"id"}
        for i in range(len(tmpl)):
            x = tmpl[i]
            if i in varying and x["kind"] == "text":
                vals = [_value(r[i]["text"]) for r in rows]
                typ = "currency" if all(v["type"] == "currency" for v in vals) else "string"
                base = _field_base(rows[0][i]["text"])
                if not re.search(r"\d", rows[0][i]["text"]):
                    base = "title" if "title" not in ftaken else "detail"
                fname = st.unique(base, ftaken)
                g["fields"].append({"name": fname, "type": typ, "code": vals[0].get("code")})
                for r, v in zip(g["rows"], vals):
                    r.append(v if typ == "currency" else {"type": "string", "value": v["value"]})
                x["bind"] = {"scope": "item", "field": fname, "type": typ}
            elif i in varying:
                fname = st.unique("icon", ftaken)
                g["fields"].append({"name": fname, "type": "icon"})
                for r, rr in zip(g["rows"], rows):
                    r.append({"type": "icon", "value": rr[i]["material"]})
                x["bind"] = {"scope": "item", "field": fname, "type": "icon"}
            elif x["kind"] == "text":
                if not re.search(r"[A-Za-z0-9À-ÿ]", x["text"]):
                    x["verbatim"] = True
                elif any(b["kind"] == "button" and x in _leaves(b["content"]) for b in tmpl if b["kind"] == "button"):
                    owner = next(b for b in tmpl if b["kind"] == "button" and x in _leaves(b["content"]))
                    m = CALL_RE.match(owner.get("action") or "")
                    hint = (_split_camel(m.group(1))[0] + ".button") if m else None
                    x["key"] = st.key(x["text"].strip(), hint)
                else:
                    x["key"] = st.key(x["text"].strip())
            elif x["kind"] == "button":
                handle_button(x, item)
        n["repeat"] = {"collection": coll, "item": item, "template": kids[0],
                       "styleDiffers": len({_style_sig(k) for k in kids}) > 1}
        if n["repeat"]["styleDiffers"]:
            st.warnings.append(f"state: rows of {coll} differ in style; the template uses the first row")
        st.groups.append(g)
        return True

    def order_lines(n: dict) -> bool:
        kids = n.get("children", [])
        if len(kids) < 4 or len(kids) % 2 or any(k["kind"] != "text" for k in kids):
            return False
        if not all(re.fullmatch(r"\d+\s*[×x]", kids[i]["text"].strip()) for i in range(0, len(kids), 2)):
            return False
        vals = [{"quantity": int(re.match(r"\d+", kids[i]["text"].strip()).group()),
                 "name": kids[i + 1]["text"].strip().rstrip(",;").strip()} for i in range(0, len(kids), 2)]
        fname = st.unique("lines", taken)
        st.fields.append({"name": fname, "type": "lines", "value": vals})
        tpl = dict(kids[1])
        n.clear()
        n.update(tpl)
        n["text"] = ", ".join(f"{v['quantity']}× {v['name']}" for v in vals)
        n["bind"] = {"scope": "state", "field": fname, "type": "lines"}
        return True

    def tracker(n: dict):
        # nearest box holding 2+ distinct case labels of one enum = a status tracker: ForEach over the cases
        labs = [x for x in _leaves(n) if x["kind"] == "text" and x["text"].strip() in case_of]
        if len(labs) < 2 or len({x["text"].strip() for x in labs}) != len(labs) or len({case_of[x["text"].strip()][0] for x in labs}) != 1:
            return
        if any(c["kind"] == "box" and len([x for x in _leaves(c) if x["kind"] == "text" and x["text"].strip() in case_of]) == len(labs)
               for c in n.get("children", [])):
            return
        en = case_of[labs[0]["text"].strip()][0]
        e = st.enums[en]
        sig = [_style_sig(x) for x in labs]
        cur = next((i for i, x in enumerate(labs) if x["text"].strip() == e.get("current")), None)
        if cur is None:
            cur = next((i for i in range(1, len(sig)) if sig[i] != sig[0]), 0)
        if not any(f["name"] == en for f in st.fields):
            taken.add(en)
            st.fields.append({"name": en, "type": "enum", "enum": en, "value": enum_cases[en][case_of[labs[cur]["text"].strip()][1]]})
        for j, ct in enumerate(e["cases"]):
            st.key(ct, f"{en}.{enum_cases[en][j]}")
        n["tracker"] = {"enum": en, "field": en, "done": labs[0], "current": labs[cur], "pending": labs[-1]}

    def walk(n: dict, in_shell: bool = False):
        k = n["kind"]
        if k == "text":
            mark_text(n, "state", taken, st.fields, in_shell)
        elif k == "button":
            handle_button(n, None)
            walk(n["content"], in_shell)
        elif k == "box":
            if not in_shell and (order_lines(n) or detect_tabs(n) or row_group(n)):
                return
            if not in_shell:
                tracker(n)
            if n.get("id") and st.tabs:
                for c in st.tabs["cases"]:
                    if re.search(rf"\b{re.escape(c['arg'])}\b", n["id"].replace("-", " ")):
                        n["tabCase"] = c["case"]
            for c in n["children"]:
                walk(c, in_shell)

    walk(ir)
    for o in ovs:
        walk(o["node"], o["role"] in ("topBar", "bottomBar"))
    # tab sections may precede detection in document order only if the picker comes later; re-scan ids
    if st.tabs:
        def ids(n):
            if n["kind"] == "box":
                if n.get("id") and "tabCase" not in n:
                    for c in st.tabs["cases"]:
                        if re.search(rf"\b{re.escape(c['arg'])}\b", n["id"].replace("-", " ")):
                            n["tabCase"] = c["case"]
                for c in n["children"]:
                    ids(c)
        ids(ir)
    for f in st.fields:
        f.setdefault("code", None)
    ir["state"] = st
    return st


def _swift_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _kt_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def strings_catalog(st: StateModel, fmt: str = "xcstrings") -> str:
    src = st.locale.split("_")[0]
    if fmt == "android":
        out = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
        for k, v in st.keys.items():
            esc = v.replace("&", "&amp;").replace("<", "&lt;").replace("'", "\\'").replace('"', '\\"')
            out.append(f'    <string name="{android_res(k)}">{esc}</string>')
        return "\n".join(out + ["</resources>", ""])
    cat = {"sourceLanguage": src, "version": "1.0", "strings": {
        k: {"extractionState": "manual", "localizations": {src: {"stringUnit": {"state": "translated", "value": v}}}}
        for k, v in st.keys.items()}}
    return json.dumps(cat, indent=2, ensure_ascii=False) + "\n"


def android_res(key: str) -> str:
    return "_".join("_".join(_split_camel(p)) for p in key.split("."))


class SwiftEmitter:
    """Native fonts (SF, size+weight kept), exact colours/spacing/radius, Material icons -> SF Symbols."""

    ICONS = {"arrow_back": "chevron.left", "share": "square.and.arrow.up", "sports_hockey": "hockey.puck",
             "leaderboard": "chart.bar", "notifications": "bell", "person": "person",
             "arrow_forward": "chevron.right", "chevron_left": "chevron.left", "chevron_right": "chevron.right",
             "expand_more": "chevron.down", "expand_less": "chevron.up", "close": "xmark", "menu": "line.3.horizontal",
             "more_vert": "ellipsis", "more_horiz": "ellipsis", "search": "magnifyingglass", "add": "plus",
             "remove": "minus", "check": "checkmark", "check_circle": "checkmark.circle.fill", "home": "house",
             "settings": "gearshape", "favorite": "heart", "star": "star", "edit": "pencil", "delete": "trash",
             "info": "info.circle", "help": "questionmark.circle", "error": "exclamationmark.circle",
             "warning": "exclamationmark.triangle", "calendar_today": "calendar", "event": "calendar",
             "schedule": "clock", "location_on": "mappin.and.ellipse", "place": "mappin", "map": "map",
             "shopping_cart": "cart", "shopping_bag": "bag", "receipt_long": "doc.text", "storefront": "storefront",
             "qr_code": "qrcode", "qr_code_scanner": "qrcode.viewfinder", "filter_list": "line.3.horizontal.decrease",
             "refresh": "arrow.clockwise", "repeat": "repeat", "logout": "rectangle.portrait.and.arrow.right",
             "mail": "envelope", "phone": "phone", "chat": "bubble.left", "visibility": "eye",
             "visibility_off": "eye.slash", "lock": "lock", "bookmark": "bookmark", "play_arrow": "play.fill",
             "pause": "pause.fill", "local_shipping": "shippingbox", "payments": "creditcard", "bakery_dining": "birthday.cake"}

    def __init__(self, th: Theme, mapping: dict):
        self.th = th
        mapping = {k: ({kk: vv for kk, vv in v.items() if vv} if isinstance(v, dict) and k != "preview" else v)
                   for k, v in (mapping or {}).items()}  # null/"" entries = unmapped (skeleton from `init`)
        self.map = mapping  # {"colors": {"surface": "DS.Colors.surface", "#12241c": "DS.Colors.card"}, ...}
        self.literals: list[str] = []

    def color(self, c: dict) -> str:
        cmap = self.map.get("colors", {})
        key = c["token"] or ("#" + c["hex"])
        if key in cmap:
            expr = cmap[key]
        elif ("#" + c["hex"]) in cmap:
            expr = cmap["#" + c["hex"]]
        elif c.get("builtin"):
            expr = {"white": "Color.white", "black": "Color.black", "transparent": "Color.clear"}[c["builtin"]]
            if c["builtin"] == "transparent":
                return expr
        elif c["token"]:
            expr = f"StitchTheme.{camel(c['token'])}"
        else:
            expr = f"Color(hex: 0x{c['hex'].upper()})"
            self.literals.append(f"#{c['hex']}")
        if c.get("alpha") is not None:
            expr += f".opacity({c['alpha']:g})"
        return expr

    def font(self, s: dict) -> str | None:
        size, weight = s.get("fontSize"), s.get("weight")
        if tok := s.get("fontToken"):
            ft = self.th.font_size[tok]
            size = size or ft["size"]
            weight = weight or ft["weight"]
        elif (ftok := s.get("familyToken")) and ftok in self.th.font_size:
            ft = self.th.font_size[ftok]
            size, weight = size or ft["size"], weight or ft["weight"]
        if size is None and weight is None:
            return None
        fmap = self.map.get("fonts", {})
        if s.get("fontToken") in fmap:
            return fmap[s["fontToken"]]
        w = {100: ".thin", 300: ".light", 400: ".regular", 500: ".medium", 600: ".semibold", 700: ".bold",
             800: ".heavy", 900: ".black"}.get(weight or 400, ".regular")
        size = size or 17
        style = text_style_for(size)
        fam = s.get("family")
        fam = fam[0] if isinstance(fam, list) and fam else fam
        custom = self.map.get("fontFamilies", {}).get(fam) if fam else None
        if custom:
            return f'.custom("{custom}", size: {size:g}, relativeTo: .{style}).weight({w})'
        return f".system(.{style}, weight: {w})"

    def num(self, v) -> str:
        return f"{v:g}"

    def modifiers(self, s: dict, ind: str) -> list[str]:
        out = []
        pad = s.get("pad", {})
        if pad:
            vals = set(pad.values())
            if len(pad) == 4 and len(vals) == 1:
                out.append(f".padding({self.num(vals.pop())})")
            else:
                h, v = pad.get("l"), pad.get("t")
                if pad.get("l") == pad.get("r") and pad.get("t") == pad.get("b") and h is not None and v is not None:
                    out += [f".padding(.horizontal, {self.num(h)})", f".padding(.vertical, {self.num(v)})"]
                else:
                    for side, name in (("t", ".top"), ("b", ".bottom"), ("l", ".leading"), ("r", ".trailing")):
                        if side in pad:
                            out.append(f".padding({name}, {self.num(pad[side])})")
        w, h = s.get("width"), s.get("height")
        fixed, flex = [], []  # SwiftUI cannot mix fixed and flexible params in one .frame()
        if isinstance(w, float):
            fixed.append(f"width: {self.num(w)}")
        if isinstance(h, float):
            fixed.append(f"height: {self.num(h)}")
        if w == "fill" and not isinstance(w, float):
            flex.append("maxWidth: .infinity")
        elif s.get("maxWidth"):
            flex.append(f"maxWidth: {self.num(s['maxWidth'])}")
        for frame in (flex, fixed):
            if frame:
                out.append(f".frame({', '.join(frame)})")
        r = s.get("radius")
        shape = None
        if r is not None:
            shape = "Capsule()" if r >= 999 else f"RoundedRectangle(cornerRadius: {self.num(r)}, style: .continuous)"
        elif s.get("corners"):
            cs = s["corners"]
            def rr(side):
                v = cs.get(side, 0)
                return "999" if v >= 999 else self.num(v)
            shape = (f"UnevenRoundedRectangle(topLeadingRadius: {rr('l')}, bottomLeadingRadius: {rr('l')}, "
                     f"bottomTrailingRadius: {rr('r')}, topTrailingRadius: {rr('r')})")
        if "bg" in s:
            fill = self.color(s["bg"])
            out.append(f".background({fill}, in: {shape})" if shape else f".background({fill})")
        if "border" in s and "divider" not in s:
            col = self.color(s["border"].get("color") or {"hex": "3c4a3e", "token": "outline-variant", "alpha": None})
            sh = shape or "Rectangle()"
            out.append(f".overlay({sh}.strokeBorder({col}, lineWidth: 1))")
        if s.get("divider"):
            col = self.color(s.get("borderColor") or {"hex": "3c4a3e", "token": "outline-variant", "alpha": None})
            edge = {"b": "bottom", "t": "top", "l": "leading", "r": "trailing"}[s["divider"]]
            align = {"bottom": ".bottom", "top": ".top", "leading": ".leading", "trailing": ".trailing"}[edge]
            out.append(f".overlay(alignment: {align}) {{ {col}.frame({'height' if edge in ('top','bottom') else 'width'}: 1) }}")
        if shape and not "bg" in s and not "border" in s:
            out.append(f".clipShape({shape})")
        mg = s.get("margin", {})
        for side, name in (("t", ".top"), ("b", ".bottom"), ("l", ".leading"), ("r", ".trailing")):
            if mg.get(side):
                out.append(f".padding({name}, {self.num(mg[side])})  // margin")
        return out

    # ------------------------------------------------------------ state mode (Swift)
    st = None
    item_var = None

    def emit(self, n: dict, ind: str = "") -> list[str]:
        st = self.st
        if not st:
            return self.emit_plain(n, ind)
        k = n["kind"]
        if k == "box" and n.get("tabCase") and not n.get("_inTab"):
            n["_inTab"] = True
            out = [f"{ind}if tab == .{n['tabCase']} {{"] + self.emit(n, ind + "    ") + [f"{ind}}}"]
            del n["_inTab"]
            return out
        if k == "box" and n.get("picker"):
            return [f"{ind}Picker(selection: $tab) {{",
                    f"{ind}    ForEach(Tab.allCases) {{ Text($0.title).tag($0) }}",
                    f"{ind}}} label: {{",
                    f"{ind}    EmptyView()",
                    f"{ind}}}",
                    f"{ind}.pickerStyle(.segmented)"]
        if k == "box" and n.get("repeat"):
            r = n["repeat"]
            var = r["item"][:1].lower() + r["item"][1:]
            prev, self.item_var = self.item_var, var
            body = self.emit(r["template"], ind + "    ")
            self.item_var = prev
            note = [f"{ind}// TODO rows differ in style in the export; this uses the first row"] if r["styleDiffers"] else []
            gap = n["style"].get("gap")
            sp = f"spacing: {self.num(gap)}" if gap is not None else "spacing: 0"
            if (n["style"].get("layout") or "col") != "row":
                return note + [f"{ind}LazyVStack({sp}) {{", f"{ind}    ForEach(state.{r['collection']}) {{ {var} in"] + [
                    "    " + l for l in body] + [f"{ind}    }}", f"{ind}}}"]
            return note + [f"{ind}ForEach(state.{r['collection']}) {{ {var} in"] + body + [f"{ind}}}"]
        if tr := n.get("tracker"):
            T = f"{self.st.name}State.{self.enum_type(tr['enum'])}"
            col = {}
            for w in ("done", "current", "pending"):
                out = self.emit(tr[w], ind + "        ")
                col[w] = next((re.search(r"\.foregroundStyle\((.+)\)", l).group(1) for l in out if ".foregroundStyle(" in l), ".primary")
            tpl = [l for l in self.emit(tr["current"], ind + "        ")[1:] if ".foregroundStyle(" not in l and ".padding(" not in l]
            f = tr["field"]
            return [f"{ind}HStack(alignment: .top, spacing: 0) {{",
                    f"{ind}    ForEach({T}.allCases, id: \\.self) {{ step in",
                    f"{ind}        Text(step.title)"] + tpl + [
                    f"{ind}            .foregroundStyle(step == state.{f} ? {col['current']} : step.rank < state.{f}.rank ? {col['done']} : {col['pending']})",
                    f"{ind}            .frame(maxWidth: .infinity)",
                    f"{ind}    }}", f"{ind}}}"]
        lines = self.emit_plain(n, ind)
        if k == "text" and (b := n.get("bind")) and b["type"] == "lines":
            return [f"{ind}ForEach(state.{b['field']}) {{ line in",
                    f'{ind}    Text(verbatim: "\\(line.quantity)× \\(line.name)")'] + ["    " + l for l in lines[1:]] + [f"{ind}}}"]
        if k == "text":
            if b := n.get("bind"):
                src = f"{self.item_var}.{b['field']}" if b["scope"] == "item" and self.item_var else f"state.{b['field']}"
                if b["type"] == "lines":
                    src = f'{src}.map {{ "\\($0.quantity)× \\($0.name)" }}.joined(separator: ", ")'
                elif b["type"] == "enum":
                    src += ".title"
                lines[0] = f"{ind}Text({self.money_expr(src) if b['type'] == 'currency' else src})"
            elif n.get("key"):
                lines[0] = f'{ind}Text("{n["key"]}")'
            elif n.get("verbatim"):
                lines[0] = f"{ind}Text(verbatim: {_swift_str(n['text'])})"
            if n["style"].get("uppercase") and not n.get("verbatim"):
                lines.insert(1, f"{ind}    .textCase(.uppercase)")
        elif k == "icon" and (b := n.get("bind")):
            lines[0] = f"{ind}Image(systemName: {self.item_var}.{b['field']})"
        elif k == "button":
            act = None
            if h := n.get("handler"):
                if h.get("item"):
                    act = f"{h['callback']}({self.item_var})"
                elif "arg" in h:
                    act = f"{h['callback']}({_swift_str(h['arg'])})"
                else:
                    act = f"{h['callback']}()"
            elif f := n.get("flag"):
                ov = next(o for o in self.ir_overlays if o["id"] == f["overlay"])
                act = f"{self.state_name(ov)} = {'true' if f['value'] else 'false'}"
            if act:
                lines[0] = f"{ind}Button {{ {act} }} label: {{"
            if n.get("label"):
                for i, l in enumerate(lines):
                    if l.startswith(f"{ind}.accessibilityLabel("):
                        lines[i] = f'{ind}.accessibilityLabel("{st.key(n["label"], _lower_camel(_words(n["label"])[:3]))}")'
        return lines

    def money_expr(self, src: str) -> str:
        fmt = (self.st.types.get("currency") or {}).get("swiftFormat")
        return fmt.replace("{v}", src) if fmt else f"money({src})"

    def swift_type(self, f: dict) -> str:
        if f["type"] == "currency":
            return (self.st.types.get("currency") or {}).get("swiftType", "Int")
        if f["type"] == "lines":
            return "[Line]"
        if f["type"] == "enum":
            return self.enum_type(f["enum"])
        return "String"

    def swift_value(self, f: dict, v: dict) -> str:
        if f["type"] == "currency":
            t = (self.st.types.get("currency") or {}).get("swiftSample")
            return t.replace("{cents}", str(v["cents"])) if t else str(v["cents"])
        if f["type"] == "lines":
            return "[" + ", ".join(f".init(quantity: {x['quantity']}, name: {_swift_str(x['name'])})" for x in v["value"]) + "]"
        if f["type"] == "enum":
            return "." + v["value"]
        if f["type"] == "icon":
            return _swift_str(self.map.get("icons", {}).get(v["value"]) or self.ICONS.get(v["value"], "questionmark.square.dashed"))
        return _swift_str(v["value"])

    def enum_type(self, en: str) -> str:
        e = self.st.enums.get(en, {})
        return e.get("type") or (en[:1].upper() + en[1:])

    def enum_cases(self, en: str) -> list:
        cs = self.st.enums.get(en, {}).get("cases", [])
        return [(_lower_camel(_words(t)) or f"case{i + 1}", self.st.key(t, f"{en}.{_lower_camel(_words(t)) or f'case{i + 1}'}"))
                for i, t in enumerate(cs)]

    def screen_state(self, ir: dict, name: str) -> str:
        st = self.st
        self.ir_overlays = ir.get("overlays", [])
        body = self.emit(ir, "        ")
        ovs = self.ir_overlays
        for o in ovs:
            i = "        "
            if o["role"] in ("topBar", "bottomBar"):
                edge = "top" if o["role"] == "topBar" else "bottom"
                if o["role"] == "bottomBar":
                    body.append(f"{i}// bottom nav: in the app this is the TabView's tab bar")
                body.append(f"{i}.safeAreaInset(edge: .{edge}, spacing: 0) {{")
                body += self.emit(o["node"], i + "    ")
                body.append(f"{i}}}")
            elif o["role"] == "toast":
                body += [f"{i}.overlay(alignment: .bottom) {{", f"{i}    if {self.state_name(o)} {{"]
                body += self.emit(o["node"], i + "        ")
                body += [f"{i}    }}", f"{i}}}"]
            else:
                body.append(f"{i}.sheet(isPresented: ${self.state_name(o)}) {{")
                body += self.emit(o["node"], i + "    ")
                body.append(f"{i}}}")
        T = st.type
        uses_money = any("money(" in l for l in body)
        out = ["import SwiftUI", "",
               "// Generated by stitch-native (state mode) from a Stitch export. Do not hand-edit; regenerate.",
               "// Stateless view: all data comes in through `state`, all actions go out through callbacks.", "",
               f"struct {T}: Equatable {{"]
        if any(f["type"] == "lines" for f in st.fields):
            out += ["    struct Line: Identifiable, Equatable {", "        var id = UUID()", "        let quantity: Int", "        let name: String", "    }", ""]
        for f in st.fields:
            if f["type"] == "enum":
                out += [f"    enum {self.enum_type(f['enum'])}: String, CaseIterable {{"]
                out += [f"        case {c}" for c, _ in self.enum_cases(f["enum"])]
                out += ["", "        var rank: Int { Self.allCases.firstIndex(of: self) ?? 0 }"]
                out += ["", "        var title: LocalizedStringKey {", "            switch self {"]
                out += [f'            case .{c}: "{k}"' for c, k in self.enum_cases(f["enum"])]
                out += ["            }", "        }", "    }", ""]
        for g in st.groups:
            out.append(f"    struct {g['item']}: Identifiable, Equatable {{")
            out.append("        let id: UUID")
            out += [f"        let {f['name']}: {self.swift_type(f)}" + ("  // cents" if f["type"] == "currency" and self.swift_type(f) == "Int" else "") for f in g["fields"]]
            out.append("    }")
            out.append("")
        for g in st.groups:
            out.append(f"    var {g['collection']}: [{g['item']}]")
        out += [f"    var {f['name']}: {self.swift_type(f)}" + ("  // cents" if f["type"] == "currency" and self.swift_type(f) == "Int" else "") for f in st.fields]
        out += ["}", "", f"extension {T} {{", "    /// Sample data copied from the export; use it in previews and tests.",
                f"    static let sample = {T}("]
        args = []
        for g in st.groups:
            rows = []
            for r in g["rows"]:
                vals = ", ".join(f"{f['name']}: {self.swift_value(f, v)}" for f, v in zip(g["fields"], r))
                rows.append(f"            .init(id: UUID(), {vals})")
            args.append(f"        {g['collection']}: [\n" + ",\n".join(rows) + "\n        ]")
        args += [f"        {f['name']}: {self.swift_value(f, f)}" for f in st.fields]
        out += [",\n".join(args), "    )", "}", ""]
        out.append(f"struct {name}: View {{")
        out.append(f"    let state: {T}")
        cbs = []
        for cb, c in st.callbacks.items():
            sig = f"({T}.{c['item']}) -> Void" if c.get("item") else ("(String) -> Void" if c.get("arg") else "() -> Void")
            dflt = "{ _ in }" if c.get("item") or c.get("arg") else "{}"
            cbs.append((cb, sig, dflt))
            out.append(f"    var {cb}: {sig} = {dflt}")
        if st.tabs:
            out.append(f"    @State private var tab: Tab = .{st.tabs['default']}")
        for o in ovs:
            if o["role"] in ("sheet", "toast"):
                out.append(f"    @State private var {self.state_name(o)} = false")
        out += ["", "    init(", f"        state: {T}" + ("," if cbs else "")]
        out += [f"        {cb}: @escaping {sig} = {d}" + ("," if j < len(cbs) - 1 else "") for j, (cb, sig, d) in enumerate(cbs)]
        out += ["    ) {", "        self.state = state"] + [f"        self.{cb} = {cb}" for cb, _, _ in cbs] + ["    }", ""]
        out += ["    var body: some View {"] + body + ["    }"]
        if uses_money:
            loc = st.locale
            code = next((f["code"] for f in st.fields if f.get("code")), None) or next((f["code"] for g in st.groups for f in g["fields"] if f.get("code")), "EUR")
            out += ["", "    private func money(_ cents: Int) -> String {",
                    f'        (Decimal(cents) / 100).formatted(.currency(code: "{code}").locale(Locale(identifier: "{loc}")))', "    }"]
        out.append("}")
        if st.tabs:
            out += ["", f"private extension {name} {{", "    enum Tab: String, CaseIterable, Identifiable {",
                    "        " + "case " + ", ".join(c["case"] for c in st.tabs["cases"]), "", "        var id: Self { self }", "",
                    "        var title: LocalizedStringKey {", "            switch self {"]
            out += [f'            case .{c["case"]}: "{c["key"]}"' for c in st.tabs["cases"]]
            out += ["            }", "        }", "    }", "}"]
        out += ["", '#Preview("Light") {', f"    {name}(state: .sample)", "        .preferredColorScheme(.light)", "}", "",
                '#Preview("Dark") {', f"    {name}(state: .sample)", "        .preferredColorScheme(.dark)", "}", "",
                '#Preview("Large type") {', f"    {name}(state: .sample)", "        .environment(\\.dynamicTypeSize, .accessibility3)", "}", ""]
        return "\n".join(out)

    def emit_plain(self, n: dict, ind: str = "") -> list[str]:
        k = n["kind"]
        if k == "text":
            s = n["style"]
            text = n["text"].upper() if s.get("uppercase") else n["text"]
            lines = [f'{ind}Text("{text}")']
            if f := self.font(s):
                lines.append(f"{ind}    .font({f})")
            if "color" in s:
                lines.append(f"{ind}    .foregroundStyle({self.color(s['color'])})")
            if s.get("textAlign") == "center":
                lines.append(f"{ind}    .multilineTextAlignment(.center)")
            if s.get("lineLimit"):
                lines.append(f"{ind}    .lineLimit(1)")
            lines += [f"{ind}    {m}" for m in self.modifiers(n.get("box", {}), ind)]
            return lines
        if k == "icon":
            sf = self.map.get("icons", {}).get(n["material"]) or self.ICONS.get(n["material"], "questionmark.square.dashed")
            return [f'{ind}Image(systemName: "{sf}")  // material: {n["material"]}']
        if k == "vector":
            lines = [f'{ind}Image(systemName: "photo")  // TODO svg' + (f': {n["label"]}' if n.get("label") else "")]
            return lines + [f"{ind}    {m}" for m in self.modifiers(n["style"], ind)]
        if k == "button":
            act = (n.get("action") or "").replace("*/", "* /")
            lines = [f"{ind}Button {{ /* {act} */ }} label: {{"] if act else [f"{ind}Button {{}} label: {{"]
            lines += self.emit(n["content"], ind + "    ")
            lines.append(f"{ind}}}")
            lines.append(f"{ind}.buttonStyle(.plain)")
            if n.get("label"):
                lines.append(f'{ind}.accessibilityLabel("{n["label"]}")')
            if n.get("current"):
                lines.append(f"{ind}.accessibilityAddTraits(.isSelected)")
            return lines
        if k == "image":
            src = n.get("src") or ""
            lines = [f'{ind}AsyncImage(url: URL(string: "{src}")) {{ $0.resizable().scaledToFit() }} placeholder: {{ Color.clear }}']
            lines += [f"{ind}    {m}" for m in self.modifiers(n["style"], ind)]
            return lines
        # box
        s, kids = n["style"], n["children"]
        layout = s.get("layout")
        gap = s.get("gap")
        spacing = f"spacing: {self.num(gap)}" if gap is not None else "spacing: 0"
        if n.get("tag") == "body":
            lines = [f"{ind}ScrollView {{"]
            for ch in kids:
                lines += self.emit(ch, ind + "    ")
            lines.append(f"{ind}}}")
            lines += [f"{ind}{m}" for m in self.modifiers(s, ind)]
            return lines
        single = layout == "row" and len(kids) == 1 and s.get("justify") != "between"
        if single:  # flex wrapper around one child (e.g. a centred logo) -> ZStack, no extra HStack
            head = "ZStack" if s.get("align") in (None, "center") else "ZStack(alignment: .leading)"
        elif layout == "row":
            al = {"center": ".center", "start": ".top", "end": ".bottom", "baseline": ".firstTextBaseline"}.get(s.get("align"), ".center")
            head = f"HStack(alignment: {al}, {spacing})"
        elif layout == "grid" and s.get("cols") and any("span" in c.get("style", {}) for c in kids) \
                and not any("widthPct" in c.get("style", {}) for c in kids):
            spans = ", ".join(str(c.get("style", {}).get("span", 1)) for c in kids)
            head = f"SpanColumns(spans: [{spans}], {spacing})"
            self.need_span = True
        elif layout == "grid":
            head = f"HStack({spacing})"
        else:
            al = ".center" if s.get("align") == "center" else ".leading"
            head = f"VStack(alignment: {al}, {spacing})"
        pct = layout == "grid" and any("widthPct" in c.get("style", {}) for c in kids)
        lines = []
        inner = ind
        if pct:
            lines.append(f"{ind}GeometryReader {{ geo in")
            inner = ind + "    "
        lines.append(f"{inner}{head} {{")
        for i, ch in enumerate(kids):
            if layout == "row" and s.get("justify") == "between" and i > 0:
                lines.append(f"{inner}    Spacer(minLength: 0)")
            sub = self.emit(ch, inner + "    ")
            cs = ch.get("style", {})
            if layout == "grid":
                if pct and "widthPct" in cs:
                    pad = s.get("pad", {})
                    inset = (gap or 0) * (len(kids) - 1) + (pad.get("l") or 0) + (pad.get("r") or 0)
                    w = f"(geo.size.width - {self.num(inset)})" if inset else "geo.size.width"
                    sub.append(f"{inner}        .frame(width: max(0, {w} * {cs['widthPct']:g}))")
                else:
                    sub.append(f"{inner}        .frame(maxWidth: .infinity)")
            lines += sub
        lines.append(f"{inner}}}")
        mods = self.modifiers(s, inner)
        if s.get("justify") == "between" and layout == "row":
            mods.insert(0, ".frame(maxWidth: .infinity)")
        if layout == "column" and n.get("tag") in ("section", "main") or s.get("bg"):
            mods.insert(0, ".frame(maxWidth: .infinity, alignment: .leading)")
        lines += [f"{inner}{m}" for m in mods]
        if pct:
            lines.append(f"{ind}}}")
            if isinstance(s.get("height"), float):
                lines.append(f"{ind}.frame(height: {self.num(s['height'])})")
        return lines

    @staticmethod
    def state_name(ov: dict) -> str:
        c = camel(re.sub(r"[^A-Za-z0-9_-]", "-", ov["id"]))
        return "show" + c[:1].upper() + c[1:]

    def screen(self, ir: dict, name: str) -> str:
        out = self._screen(ir, name)
        if getattr(self, "need_span", False) and type(self) is SwiftEmitter:
            out = out.rstrip("\n") + "\n" + SPAN_COLUMNS
        return out

    def _screen(self, ir: dict, name: str) -> str:
        self.need_span = False
        self.st = ir.get("state")
        if self.st:
            return self.screen_state(ir, name)
        body = self.emit(ir, "        ")
        ovs = ir.get("overlays", [])
        state = [f"    @State private var {self.state_name(o)} = false" for o in ovs if o["role"] in ("sheet", "toast")]
        for o in ovs:
            i = "        "
            if o["role"] in ("topBar", "bottomBar"):
                edge = "top" if o["role"] == "topBar" else "bottom"
                if o["role"] == "bottomBar":
                    body.append(f"{i}// bottom nav: consider a TabView for real tab navigation")
                body.append(f"{i}.safeAreaInset(edge: .{edge}, spacing: 0) {{")
                body += self.emit(o["node"], i + "    ")
                body.append(f"{i}}}")
            elif o["role"] == "toast":
                body.append(f"{i}.overlay(alignment: .bottom) {{")
                body.append(f"{i}    if {self.state_name(o)} {{")
                body += self.emit(o["node"], i + "        ")
                body.append(f"{i}    }}")
                body.append(f"{i}}}")
            else:
                body.append(f"{i}.sheet(isPresented: ${self.state_name(o)}) {{")
                body += self.emit(o["node"], i + "    ")
                body.append(f"{i}}}")
        scheme = getattr(self.th, "scheme", "dark")
        cfg_scheme = self.map.get("preview", {}).get("colorScheme")
        scheme = cfg_scheme or scheme
        head = f"struct {name}: View {{\n" + ("\n".join(state) + "\n\n" if state else "") + "    var body: some View {\n"
        return ("import SwiftUI\n\n"
                f"// Generated by stitch-native from a Stitch export. Do not hand-edit; regenerate.\n"
                + head + "\n".join(body) +
                "\n    }\n}\n\n#Preview {\n    " + name + f"()\n        .preferredColorScheme(.{scheme})\n}}\n")


SPAN_COLUMNS = """
/// CSS grid col-span: each column gets free width (after spacing) in proportion to its span.
private struct SpanColumns: Layout {
    var spans: [CGFloat]
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache _: inout ()) -> CGSize {
        let width = proposal.replacingUnspecifiedDimensions().width
        let heights = zip(subviews, widths(width)).map { $0.sizeThatFits(ProposedViewSize(width: $1, height: nil)).height }
        return CGSize(width: width, height: heights.max() ?? 0)
    }

    func placeSubviews(in bounds: CGRect, proposal _: ProposedViewSize, subviews: Subviews, cache _: inout ()) {
        var x = bounds.minX
        for (view, w) in zip(subviews, widths(bounds.width)) {
            view.place(at: CGPoint(x: x, y: bounds.midY), anchor: .leading, proposal: ProposedViewSize(width: w, height: bounds.height))
            x += w + spacing
        }
    }

    private func widths(_ total: CGFloat) -> [CGFloat] {
        let free = max(0, total - spacing * CGFloat(max(spans.count - 1, 0)))
        let sum = spans.reduce(0, +)
        return spans.map { sum > 0 ? free * $0 / sum : 0 }
    }
}
"""


class ComposeEmitter(SwiftEmitter):
    """Jetpack Compose (Material 3). Reuses the IR walk; Material icons map 1:1."""

    def color(self, c: dict) -> str:
        cmap = self.map.get("colors", {})
        key = c["token"] or ("#" + c["hex"])
        if key in cmap:
            expr = cmap[key]
        elif c.get("builtin"):
            expr = {"white": "Color.White", "black": "Color.Black", "transparent": "Color.Transparent"}[c["builtin"]]
            if c["builtin"] == "transparent":
                return expr
        elif c["token"]:
            expr = f"StitchTheme.{camel(c['token'])}"
        else:
            expr = f"Color(0xFF{c['hex'].upper()})"
            self.literals.append(f"#{c['hex']}")
        if c.get("alpha") is not None:
            expr += f".copy(alpha = {c['alpha']:g}f)"
        return expr

    def shape(self, s: dict) -> str | None:
        r = s.get("radius")
        if r is not None:
            return "CircleShape" if r >= 999 else f"RoundedCornerShape({self.num(r)}.dp)"
        if cs := s.get("corners"):
            def v(side):
                x = cs.get(side, 0)
                return "50" if x >= 999 else self.num(x)
            pct = any(x >= 999 for x in cs.values())
            u = "" if pct else ".dp"
            l, r_ = v("l"), v("r")
            return (f"RoundedCornerShape(topStart = {l}{u}, bottomStart = {l}{u}, "
                    f"topEnd = {r_}{u}, bottomEnd = {r_}{u})")
        return None

    def mod_chain(self, s: dict, extra: list[str] | None = None) -> str:
        m = list(extra or [])
        mg = s.get("margin", {})
        if mg:
            m.append("padding(" + ", ".join(f"{n} = {self.num(mg[k])}.dp" for k, n in
                     (("t", "top"), ("b", "bottom"), ("l", "start"), ("r", "end")) if mg.get(k)) + ")")
        w, h = s.get("width"), s.get("height")
        if w == "fill":
            m.append("fillMaxWidth()")
        elif isinstance(w, float):
            m.append(f"width({self.num(w)}.dp)")
        if isinstance(h, float):
            m.append(f"height({self.num(h)}.dp)")
        if s.get("maxWidth"):
            m.append(f"widthIn(max = {self.num(s['maxWidth'])}.dp)")
        sh = self.shape(s)
        if "border" in s and "divider" not in s:
            col = self.color(s["border"].get("color") or {"hex": "3c4a3e", "token": "outline-variant", "alpha": None})
            m.append(f"border(1.dp, {col}, {sh or 'RectangleShape'})")
        if "bg" in s:
            m.append(f"background({self.color(s['bg'])}, {sh})" if sh else f"background({self.color(s['bg'])})")
        elif sh:
            m.append(f"clip({sh})")
        pad = s.get("pad", {})
        if pad:
            vals = set(pad.values())
            if len(pad) == 4 and len(vals) == 1:
                m.append(f"padding({self.num(vals.pop())}.dp)")
            else:
                m.append("padding(" + ", ".join(f"{n} = {self.num(pad[k])}.dp" for k, n in
                         (("t", "top"), ("b", "bottom"), ("l", "start"), ("r", "end")) if k in pad) + ")")
        if not m:
            return ""
        return "Modifier." + ".".join(m)

    def text_style(self, s: dict) -> list[str]:
        out = []
        size, weight = s.get("fontSize"), s.get("weight")
        if tok := s.get("fontToken"):
            ft = self.th.font_size[tok]
            size, weight = size or ft["size"], weight or ft["weight"]
        elif (ft := self.th.font_size.get(s.get("familyToken"))) is not None:
            size, weight = size or ft["size"], weight or ft["weight"]
        if size:
            out.append(f"fontSize = {self.num(size)}.sp")
        if weight:
            out.append(f"fontWeight = FontWeight.W{weight}")
        if "color" in s:
            out.append(f"color = {self.color(s['color'])}")
        if s.get("textAlign") == "center":
            out.append("textAlign = TextAlign.Center")
        if s.get("lineLimit"):
            out += ["maxLines = 1", "overflow = TextOverflow.Ellipsis"]
        return out

    def call(self, ind, name, args):
        args = [a for a in args if a]
        if not args:
            return [f"{ind}{name}()"]
        return [f"{ind}{name}("] + [f"{ind}    {a}," for a in args] + [f"{ind})"]

    # ------------------------------------------------------------ state mode (Compose)
    def emit(self, n: dict, ind: str = "", extra: list[str] | None = None) -> list[str]:
        st = self.st
        if not st:
            return self.emit_plain(n, ind, extra)
        k = n["kind"]
        if k == "box" and n.get("tabCase") and not n.get("_inTab"):
            n["_inTab"] = True
            out = [f"{ind}if (tab == {st.name}Tab.{self.kt_case(n['tabCase'])}) {{"] + self.emit(n, ind + "    ", extra) + [f"{ind}}}"]
            del n["_inTab"]
            return out
        if k == "box" and n.get("picker"):
            m = len(st.tabs["cases"])
            return [f"{ind}SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {{",
                    f"{ind}    {st.name}Tab.entries.forEachIndexed {{ index, option ->",
                    f"{ind}        SegmentedButton(",
                    f"{ind}            selected = tab == option,",
                    f"{ind}            onClick = {{ tab = option }},",
                    f"{ind}            shape = SegmentedButtonDefaults.itemShape(index = index, count = {m}),",
                    f"{ind}        ) {{ Text(stringResource(option.title)) }}",
                    f"{ind}    }}",
                    f"{ind}}}"]
        if k == "box" and n.get("repeat"):
            r = n["repeat"]
            var = r["item"][:1].lower() + r["item"][1:]
            prev, self.item_var = self.item_var, var
            body = self.emit(r["template"], ind + "        ", extra)
            self.item_var = prev
            note = [f"{ind}// TODO rows differ in style in the export; this uses the first row"] if r["styleDiffers"] else []
            note.append(f"{ind}// unbounded list: inside a scrolling Column; move to LazyColumn items(state.{r['collection']}, key = {{ it.id }}) when it grows")
            return note + [f"{ind}state.{r['collection']}.forEach {{ {var} ->", f"{ind}    key({var}.id) {{"] + body + [f"{ind}    }}", f"{ind}}}"]
        if tr := n.get("tracker"):
            T = self.enum_type(tr["enum"])
            col = {}
            for w in ("done", "current", "pending"):
                out = self.emit(tr[w], ind + "        ")
                col[w] = next((l.split("color = ", 1)[1].rstrip(",") for l in out if "color = " in l), "Color.Unspecified")
            f = tr["field"]
            s = tr["current"]["style"]
            return self.call(ind, "Row", ["modifier = Modifier.fillMaxWidth()", "horizontalArrangement = Arrangement.SpaceBetween"])[:1] + [
                f"{ind}    {T}.entries.forEach {{ step ->"] + self.call(ind + "        ", "Text", [
                    "text = stringResource(step.title)", "modifier = Modifier.weight(1f)"] + [a for a in self.text_style(s) if not a.startswith("color")] + [
                    f"color = when {{ step == state.{f} -> {col['current']}; step.ordinal < state.{f}.ordinal -> {col['done']}; else -> {col['pending']} }}"]) + [
                f"{ind}    }}", f"{ind}}}"]
        if k == "text" and (b := n.get("bind")) and b["type"] == "lines":
            mod = self.mod_chain(n.get("box", {}), extra)
            return [f"{ind}state.{b['field']}.forEach {{ line ->"] + self.call(ind + "    ", "Text", [
                'text = "${line.quantity}× ${line.name}"'] + ([f"modifier = {mod}"] if mod else []) + self.text_style(n["style"])) + [f"{ind}}}"]
        if k == "text" and (n.get("bind") or n.get("key")):
            s = n["style"]
            if b := n.get("bind"):
                src = f"{self.item_var}.{b['field']}" if b["scope"] == "item" and self.item_var else f"state.{b['field']}"
                expr = f"money({src})" if b["type"] == "currency" else src
                if b["type"] == "lines":
                    expr = f'{src}.joinToString(", ") {{ "${{it.quantity}}× ${{it.name}}" }}'
                elif b["type"] == "enum":
                    expr = f"stringResource({src}.title)"
            else:
                expr = f"stringResource(R.string.{android_res(n['key'])})"
            if s.get("uppercase"):
                expr += ".uppercase()"
            mod = self.mod_chain(n.get("box", {}), extra)
            return self.call(ind, "Text", [f"text = {expr}"] + ([f"modifier = {mod}"] if mod else []) + self.text_style(s))
        if k == "button" and (n.get("handler") or n.get("flag")):
            if h := n.get("handler"):
                act = f"{h['callback']}({self.item_var})" if h.get("item") else (
                    f"{h['callback']}({_kt_str(h['arg'])})" if "arg" in h else f"{h['callback']}()")
            else:
                f = n["flag"]
                ov = next(o for o in self.ir_overlays if o["id"] == f["overlay"])
                act = f"{self.state_name(ov)} = {'true' if f['value'] else 'false'}"
            extra2 = list(extra or []) + ["clickable { " + act + " }"]
            if n.get("label"):
                key = st.key(n["label"], _lower_camel(_words(n["label"])[:3]))
                extra2.append("semantics { contentDescription = " + f"stringResource(R.string.{android_res(key)})" + " }")
            return self.emit(n["content"], ind, extra2)
        return self.emit_plain(n, ind, extra)

    @staticmethod
    def kt_case(c: str) -> str:
        return "".join(p[:1].upper() + p[1:] for p in _split_camel(c)) if c else c

    def kt_type(self, f: dict) -> str:
        if f["type"] == "lines":
            return "List<Line>"
        if f["type"] == "enum":
            return self.enum_type(f["enum"])
        return "Long" if f["type"] == "currency" else "String"

    def enum_type(self, en: str) -> str:
        e = self.st.enums.get(en, {})
        return e.get("type") or (en[:1].upper() + en[1:])

    def kt_value(self, f: dict, v: dict) -> str:
        if f["type"] == "lines":
            return "listOf(" + ", ".join(f"Line({x['quantity']}, {_kt_str(x['name'])})" for x in v["value"]) + ")"
        if f["type"] == "enum":
            return f"{self.enum_type(f['enum'])}.{self.kt_case(v['value'])}"
        if f["type"] == "currency":
            return f"{v['cents']}L"
        return _kt_str(v["value"])

    def screen_state(self, ir: dict, name: str) -> str:
        st = self.st
        self.ir_overlays = ovs = ir.get("overlays", [])
        T = st.type
        imports = ["androidx.compose.foundation.*", "androidx.compose.foundation.layout.*",
                   "androidx.compose.foundation.shape.*", "androidx.compose.material.icons.Icons",
                   "androidx.compose.material.icons.outlined.*", "androidx.compose.material3.*",
                   "androidx.compose.runtime.*", "androidx.compose.ui.Alignment",
                   "androidx.compose.ui.Modifier", "androidx.compose.ui.draw.clip",
                   "androidx.compose.ui.graphics.*", "androidx.compose.ui.layout.ContentScale",
                   "androidx.compose.ui.res.stringResource", "androidx.compose.ui.semantics.*",
                   "androidx.compose.ui.text.font.FontWeight", "androidx.compose.ui.text.style.*",
                   "androidx.compose.ui.tooling.preview.Preview", "androidx.compose.ui.unit.dp",
                   "androidx.compose.ui.unit.sp", "androidx.compose.ui.window.Dialog",
                   "android.content.res.Configuration", "androidx.annotation.StringRes",
                   "coil3.compose.AsyncImage", "java.text.NumberFormat", "java.util.Currency", "java.util.Locale"]
        imports.sort()
        bars = {o["role"]: o for o in ovs if o["role"] in ("topBar", "bottomBar")}
        pops = [o for o in ovs if o["role"] in ("sheet", "toast")]
        cbs = []
        for cb, c in st.callbacks.items():
            sig = f"({T}.{c['item']}) -> Unit" if c.get("item") else ("(String) -> Unit" if c.get("arg") else "() -> Unit")
            cbs.append((cb, sig, "{}"))
        body = []
        if st.tabs:
            body.append(f"    var tab by rememberSaveable {{ mutableStateOf({st.name}Tab.{self.kt_case(st.tabs['default'])}) }}")
        body += [f"    var {self.state_name(o)} by rememberSaveable {{ mutableStateOf(false) }}" for o in pops]
        body.append("    Scaffold(")
        body.append("        modifier = modifier,")
        for role in ("topBar", "bottomBar"):
            if role in bars:
                body.append(f"        {role} = {{")
                body += self.emit(bars[role]["node"], "            ")
                body.append("        },")
        body += ["    ) { innerPadding ->", "        Box(modifier = Modifier.padding(innerPadding)) {"]
        body += self.emit(ir, "            ")
        for o in pops:
            v = self.state_name(o)
            body.append(f"            if ({v}) {{")
            if o["role"] == "sheet":
                body.append(f"                Dialog(onDismissRequest = {{ {v} = false }}) {{")
            else:
                body.append("                Box(modifier = Modifier.align(Alignment.BottomCenter)) {")
            body += self.emit(o["node"], "                    ")
            body += ["                }", "            }"]
        body += ["        }", "    }"]
        uses_money = any("money(" in l for l in body)
        out = [f"import {i}" for i in imports] + ["",
               "// Generated by stitch-native (state mode) from a Stitch export. Do not hand-edit; regenerate.",
               "// Stateless screen: data comes in through `state`, actions go out through lambdas (state hoisting).", "",
               "@Immutable", f"data class {T}("]
        props = [f"    val {g['collection']}: List<{g['item']}>," for g in st.groups]
        props += [f"    val {f['name']}: {self.kt_type(f)}," + ("  // cents" if f["type"] == "currency" else "") for f in st.fields]
        out += props + [") {"]
        for g in st.groups:
            out += ["    @Immutable", f"    data class {g['item']}(", "        val id: String,"]
            out += [f"        val {f['name']}: {self.kt_type(f)}," + ("  // cents" if f["type"] == "currency" else "") for f in g["fields"]]
            out.append("    )")
        if any(f["type"] == "lines" for f in st.fields):
            out += ["    @Immutable", "    data class Line(val quantity: Int, val name: String)"]
        out += ["", "    companion object {", "        /** Sample data copied from the export; use it in previews and tests. */",
                f"        val sample = {T}("]
        for g in st.groups:
            out.append(f"            {g['collection']} = listOf(")
            for j, r in enumerate(g["rows"]):
                vals = ", ".join(f"{f['name']} = {self.kt_value(f, v)}" for f, v in zip(g["fields"], r))
                out.append(f'                {g["item"]}(id = "{j + 1}", {vals}),')
            out.append("            ),")
        out += [f"            {f['name']} = {self.kt_value(f, f)}," for f in st.fields]
        out += ["        )", "    }", "}", ""]
        for f in st.fields:
            if f["type"] == "enum":
                out.append(f"enum class {self.enum_type(f['enum'])}(@StringRes val title: Int) {{")
                for i, t in enumerate(st.enums[f["enum"]]["cases"]):
                    c = _lower_camel(_words(t)) or f"case{i + 1}"
                    out.append(f"    {self.kt_case(c)}(R.string.{android_res(st.key(t, f'{f[chr(101)+chr(110)+chr(117)+chr(109)]}.{c}'))}),")
                out += ["}", ""]
        if st.tabs:
            out.append(f"enum class {st.name}Tab(@StringRes val title: Int) {{")
            out += [f"    {self.kt_case(c['case'])}(R.string.{android_res(c['key'])})," for c in st.tabs["cases"]]
            out += ["}", ""]
        params = [f"    state: {T},"] + [f"    {cb}: {sig} = {d}," for cb, sig, d in cbs] + ["    modifier: Modifier = Modifier,"]
        out += ["@OptIn(ExperimentalMaterial3Api::class)", "@Composable", f"fun {name}("] + params + [") {"] + body + ["}"]
        if uses_money:
            code = next((f["code"] for f in st.fields if f.get("code")), None) or next(
                (f["code"] for g in st.groups for f in g["fields"] if f.get("code")), "EUR")
            out += ["", "private fun money(cents: Long): String =",
                    f'    NumberFormat.getCurrencyInstance(Locale.forLanguageTag("{st.locale.replace("_", "-")}"))',
                    f'        .apply {{ currency = Currency.getInstance("{code}") }}',
                    "        .format(cents / 100.0)"]
        out += ["", '@Preview(name = "Light", showBackground = true)',
                '@Preview(name = "Dark", showBackground = true, uiMode = Configuration.UI_MODE_NIGHT_YES)',
                '@Preview(name = "Large font", showBackground = true, fontScale = 2f)',
                "@Composable", f"private fun {name}Preview() {{", "    MaterialTheme {", f"        {name}(state = {T}.sample)", "    }", "}", ""]
        return "\n".join(out)

    def emit_plain(self, n: dict, ind: str = "", extra: list[str] | None = None) -> list[str]:
        k = n["kind"]
        if k == "text":
            s = n["style"]
            text = n["text"].upper() if s.get("uppercase") else n["text"]
            mod = self.mod_chain(n.get("box", {}), extra)
            return self.call(ind, "Text", [f'text = "{text}"'] + ([f"modifier = {mod}"] if mod else []) + self.text_style(s))
        if k == "icon":
            mod = self.mod_chain(n["style"], extra)
            nm = "Icons.Outlined." + "".join(p.capitalize() for p in n["material"].split("_"))
            nm = self.map.get("iconsCompose", {}).get(n["material"]) or nm
            return self.call(ind, "Icon", [f"imageVector = {nm}", "contentDescription = null",
                                          f"modifier = {mod}" if mod else ""])
        if k == "vector":
            mod = self.mod_chain(n["style"], extra) or "Modifier.size(24.dp)"
            return [f"{ind}Box(modifier = {mod})  // TODO svg"]
        if k == "button":
            extra2 = list(extra or []) + ["clickable { /* " + (n.get("action") or "").replace("*/", "* /") + " */ }"]
            if n.get("label"):
                extra2.append('semantics { contentDescription = "' + n["label"] + '" }')
            return self.emit(n["content"], ind, extra2)
        if k == "image":
            mod = self.mod_chain(n["style"], extra)
            return self.call(ind, "AsyncImage", [f'model = "{n.get("src") or ""}"', "contentDescription = null",
                                                "contentScale = ContentScale.Fit", f"modifier = {mod}" if mod else ""])
        s, kids = n["style"], n["children"]
        layout = s.get("layout")
        gap = s.get("gap")
        if n.get("tag") == "body":
            mod = self.mod_chain(s, ["fillMaxSize()"]) + ".verticalScroll(rememberScrollState())"
            lines = [f"{ind}Column(modifier = {mod}) {{"]
            for ch in kids:
                lines += self.emit(ch, ind + "    ")
            return lines + [f"{ind}}}"]
        extra = list(extra or [])
        if layout == "row" and len(kids) == 1 and s.get("justify") != "between":
            ca = "Alignment.Center" if s.get("align") in (None, "center") else "Alignment.CenterStart"
            head = f"Box(modifier = {self.mod_chain(s, extra) or 'Modifier'}, contentAlignment = {ca})"
        elif layout in ("row", "grid"):
            if layout == "row" and s.get("justify") == "between":
                arr = "Arrangement.SpaceBetween"
                extra.append("fillMaxWidth()")
            else:
                arr = f"Arrangement.spacedBy({self.num(gap)}.dp)" if gap else "Arrangement.Start"
            if layout == "grid":
                extra.append("fillMaxWidth()")
            al = {"start": "Alignment.Top", "end": "Alignment.Bottom"}.get(s.get("align"), "Alignment.CenterVertically")
            head = f"Row(modifier = {self.mod_chain(s, extra) or 'Modifier'}, horizontalArrangement = {arr}, verticalAlignment = {al})"
        else:
            arr = f"Arrangement.spacedBy({self.num(gap)}.dp)" if gap else "Arrangement.Top"
            al = "Alignment.CenterHorizontally" if s.get("align") == "center" else "Alignment.Start"
            if s.get("bg") or n.get("tag") in ("section", "main"):
                extra.append("fillMaxWidth()")
            head = f"Column(modifier = {self.mod_chain(s, extra) or 'Modifier'}, verticalArrangement = {arr}, horizontalAlignment = {al})"
        lines = [f"{ind}{head} {{"]
        for ch in kids:
            cs = ch.get("style", {})
            child_extra = []
            if layout == "grid":
                if "widthPct" in cs:
                    child_extra.append(f"weight({cs['widthPct']:g}f)")
                elif "span" in cs:
                    child_extra.append(f"weight({cs['span']}f)")
                else:
                    child_extra.append("weight(1f)")
                if "widthPct" in cs:
                    child_extra.append("fillMaxHeight()")
            lines += self.emit(ch, ind + "    ", child_extra)
        return lines + [f"{ind}}}"]

    def screen(self, ir: dict, name: str) -> str:
        out = self._screen(ir, name)
        if getattr(self, "need_span", False) and type(self) is SwiftEmitter:
            out = out.rstrip("\n") + "\n" + SPAN_COLUMNS
        return out

    def _screen(self, ir: dict, name: str) -> str:
        self.need_span = False
        self.st = ir.get("state")
        if self.st:
            return self.screen_state(ir, name)
        ovs = ir.get("overlays", [])
        imports = ["androidx.compose.foundation.*", "androidx.compose.foundation.layout.*",
                   "androidx.compose.foundation.shape.*", "androidx.compose.material.icons.Icons",
                   "androidx.compose.material.icons.outlined.*", "androidx.compose.material3.*",
                   "androidx.compose.runtime.Composable", "androidx.compose.ui.Alignment",
                   "androidx.compose.ui.Modifier", "androidx.compose.ui.draw.clip",
                   "androidx.compose.ui.graphics.*", "androidx.compose.ui.layout.ContentScale",
                   "androidx.compose.ui.text.font.FontWeight", "androidx.compose.ui.text.style.*",
                   "androidx.compose.ui.tooling.preview.Preview", "androidx.compose.ui.unit.dp",
                   "androidx.compose.ui.unit.sp", "coil3.compose.AsyncImage"]
        bg = self.th.colors.get("background") or self.th.colors.get("surface") or "#0a1611"
        preview = "0xFF" + bg.lstrip("#").upper()
        if not ovs:
            body = self.emit(ir, "    ")
        else:
            imports[imports.index("androidx.compose.runtime.Composable")] = "androidx.compose.runtime.*"
            imports += ["androidx.compose.ui.semantics.*", "androidx.compose.ui.window.Dialog"]
            imports.sort()
            bars = {o["role"]: o for o in ovs if o["role"] in ("topBar", "bottomBar")}
            pops = [o for o in ovs if o["role"] in ("sheet", "toast")]
            body = [f"    var {self.state_name(o)} by remember {{ mutableStateOf(false) }}" for o in pops]
            body.append("    Scaffold(")
            for role in ("topBar", "bottomBar"):
                if role in bars:
                    body.append(f"        {role} = {{")
                    body += self.emit(bars[role]["node"], "            ")
                    body.append("        },")
            body.append("    ) { innerPadding ->")
            body.append("        Box(modifier = Modifier.padding(innerPadding)) {")
            body += self.emit(ir, "            ")
            for o in pops:
                v = self.state_name(o)
                body.append(f"            if ({v}) {{")
                if o["role"] == "sheet":
                    body.append(f"                Dialog(onDismissRequest = {{ {v} = false }}) {{")
                    body += self.emit(o["node"], "                    ")
                    body.append("                }")
                else:
                    body.append("                Box(modifier = Modifier.align(Alignment.BottomCenter)) {")
                    body += self.emit(o["node"], "                    ")
                    body.append("                }")
                body.append("            }")
            body.append("        }")
            body.append("    }")
        return ("\n".join(f"import {i}" for i in imports) +
                "\n\n// Generated by stitch-native from a Stitch export. Do not hand-edit; regenerate.\n"
                f"@Composable\nfun {name}() {{\n" + "\n".join(body) + "\n}\n\n"
                f"@Preview(backgroundColor = {preview}, showBackground = true)\n@Composable\n"
                f"private fun {name}Preview() = {name}()\n")


def theme_kotlin(th: Theme) -> str:
    lines = ["import androidx.compose.ui.graphics.Color", "import androidx.compose.ui.unit.dp", "",
             "// Stitch design tokens (generated).", "object StitchTheme {"]
    for k, v in sorted(th.colors.items()):
        lines.append(f"    val {camel(k)} = Color(0xFF{v.lstrip('#').upper()})")
    for k, v in sorted(th.spacing.items()):
        lines.append(f"    val {camel(k)}Space = {v:g}.dp")
    return "\n".join(lines + ["}", ""])


def theme_swift(th: Theme) -> str:
    lines = ["import SwiftUI", "", "// Stitch design tokens (generated).", "enum StitchTheme {"]
    for k, v in sorted(th.colors.items()):
        lines.append(f"    static let {camel(k)} = Color(hex: 0x{v.lstrip('#').upper()})")
    lines.append("")
    for k, v in sorted(th.spacing.items()):
        lines.append(f"    static let {camel(k)}: CGFloat = {v:g}")
    lines += ["}", "", "extension Color {",
              "    init(hex: UInt32, opacity: Double = 1) {",
              "        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,",
              "                  blue: Double(hex & 0xFF) / 255, opacity: opacity)",
              "    }", "}", ""]
    return "\n".join(lines)


CONFIG_FILE = "stitch-native.json"


def load_config(path: str | None = None) -> dict:
    """Explicit --config path, else ./stitch-native.json when present, else {}."""
    import os
    if path:
        return json.load(open(path, encoding="utf-8"))
    if os.path.exists(CONFIG_FILE):
        return json.load(open(CONFIG_FILE, encoding="utf-8"))
    return {}


def used_tokens(ir: dict) -> dict:
    """Colour tokens / hex literals, font tokens and Material icons a screen uses."""
    found = {"colors": set(), "fonts": set(), "icons": set()}

    def col(c):
        if isinstance(c, dict) and "hex" in c and not c.get("builtin"):
            found["colors"].add(c["token"] or "#" + c["hex"])

    def walk(x):
        if isinstance(x, dict):
            if x.get("kind") == "icon":
                found["icons"].add(x["material"])
            if x.get("fontToken"):
                found["fonts"].add(x["fontToken"])
            col(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(ir)
    return {k: sorted(v) for k, v in found.items()}


def init_config(irs: list[dict], existing: dict | None = None) -> tuple[dict, dict]:
    """Skeleton config for the screens; existing entries win. Returns (config, unmapped)."""
    cfg = json.loads(json.dumps(existing or {}))
    used = {"colors": set(), "fonts": set(), "icons": set()}
    for ir in irs:
        for k, v in used_tokens(ir).items():
            used[k] |= set(v)
    for k in ("colors", "fonts", "icons", "iconsCompose"):
        sec = cfg.setdefault(k, {})
        for t in sorted(used["icons" if k == "iconsCompose" else k]):
            if k == "icons" and t in SwiftEmitter.ICONS:
                sec.setdefault(t, SwiftEmitter.ICONS[t])
            sec.setdefault(t, None)
    cfg.setdefault("preview", {"colorScheme": None})
    cfg.setdefault("output", {"swiftui": None, "compose": None})
    unmapped = {k: [t for t, v in cfg[k].items() if not v] for k in ("colors", "fonts", "icons")}
    return cfg, unmapped


def main(argv):
    if len(argv) >= 2 and argv[1] == "init":
        paths = [a for a in argv[2:] if not a.startswith("--")]
        existing = load_config()
        irs = [parse(open(p, encoding="utf-8").read())[1] for p in paths]
        cfg, unmapped = init_config(irs, existing)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {CONFIG_FILE}")
        for k, v in unmapped.items():
            print(f"unmapped {k} ({len(v)}): {', '.join(v) or '-'}")
        return 0
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, path = argv[1], argv[2]
    html = open(path, encoding="utf-8").read()
    th, ir, warn = parse(html)
    opt = next((o for o in ("--config", "--map") if o in argv), None)
    mapping = load_config(argv[argv.index(opt) + 1] if opt else None)
    name = argv[argv.index("--name") + 1] if "--name" in argv else "StitchScreen"
    if cmd == "ir":
        print(json.dumps(ir, indent=1, ensure_ascii=False))
    elif cmd == "tokens":
        print(theme_swift(th))
    elif cmd == "tokens-kotlin":
        print(theme_kotlin(th))
    elif cmd in ("swiftui", "compose"):
        em = (SwiftEmitter if cmd == "swiftui" else ComposeEmitter)(th, mapping)
        if "--mode" in argv and argv[argv.index("--mode") + 1] == "state":
            m = re.search(r"<html[^>]*\blang=\"([^\"]+)\"", html)
            extract_state(ir, mapping, name, m.group(1) if m else None)
        print(em.screen(ir, name))
        rep = sorted(set(em.literals))
        sys.stderr.write(f"warnings: {len(warn)}  off-token literals: {rep}\n")
        for w in sorted(set(warn)):
            sys.stderr.write(f"  - {w}\n")
    else:
        print(__doc__)
        return 2
    return 0


def cli() -> None:
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()
