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
    return {"kind": "box", "tag": node.tag, "style": style, "children": kids}


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
        return f".system(size: {size or 17:g}, weight: {w})"

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

    def emit(self, n: dict, ind: str = "") -> list[str]:
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
                    sub.append(f"{inner}        .frame(width: geo.size.width * {cs['widthPct']:g})")
                elif "span" in cs and s.get("cols"):
                    sub.append(f"{inner}        .frame(maxWidth: .infinity)  // col-span {cs['span']}/{s['cols']}")
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

    def emit(self, n: dict, ind: str = "", extra: list[str] | None = None) -> list[str]:
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
