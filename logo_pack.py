#!/usr/bin/env python3
"""logo-pack: one master SVG logo -> every delivery variant plus a one-page contact sheet.

  python logo_pack.py logo.svg --mono "#0F7C80" --title "Harbor logo" --out-dir dist

Writes <name>-black/-white/-mono-<hex>/-square/-favicon/-app-icon.svg (same bytes as logo-design-skill's
export_variants.py) and <name>-sheet.svg: the mark large on light and dark, the one-colour versions, and the
favicon and app icon at the sizes they will really be seen (64/32/16 px), as in brand-identity-skill's sheet.

Variant and geometry code: logo-design-skill (MIT, kaankiziltug). Standard library only, Python 3.8+.
"""
import argparse
import base64
import colorsys
import functools
import html
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080", "gray": "#808080", "grey": "#808080",
    "silver": "#c0c0c0", "navy": "#000080", "teal": "#008080", "maroon": "#800000", "lime": "#00ff00",
    "aqua": "#00ffff", "cyan": "#00ffff", "fuchsia": "#ff00ff", "magenta": "#ff00ff", "olive": "#808000",
    "pink": "#ffc0cb", "brown": "#a52a2a", "gold": "#ffd700", "indigo": "#4b0082", "violet": "#ee82ee",
}
HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB_RE = re.compile(r"rgba?\(\s*([\d.]+%?)\s*,\s*([\d.]+%?)\s*,\s*([\d.]+%?)")
NUM_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
SHAPE_TAGS = ("path", "circle", "ellipse", "rect", "polygon", "polyline", "line")
HIDDEN_TAGS = ("defs", "clipPath", "mask", "pattern", "symbol", "marker", "title", "desc", "metadata", "style")
ARGC = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
PAINT_ATTR = re.compile(r'\b(fill|stroke|stop-color)\s*=\s*"([^"]*)"')
PAINT_CSS = re.compile(r'\b(fill|stroke|stop-color)\s*:\s*([^;"}]+)')
IDENTITY = (1, 0, 0, 1, 0, 0)


def local(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def normalize_color(value):
    """'#rrggbb' for hex / named / rgb() values, None for none/url/currentColor/unknown."""
    if not value:
        return None
    v = value.strip().lower()
    if v in ("none", "transparent", "currentcolor", "inherit") or v.startswith("url("):
        return None
    m = HEX_RE.fullmatch(v) if v.startswith("#") else None
    if m:
        h = m.group(1)
        return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h)
    if v in NAMED_COLORS:
        return NAMED_COLORS[v]
    m = RGB_RE.match(v)
    if m:
        vals = [round(float(c[:-1]) * 2.55) if c.endswith("%") else round(float(c)) for c in m.groups()]
        return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in vals)
    return None


def has_white_paint(root):
    """True when the master mixes white with other colours (white 'cut-outs' turn into blobs in one colour)."""
    parents = {c: p for p in root.iter() for c in p}
    found, painted = [], False
    for el in root.iter():
        p, hidden = parents.get(el), False
        while p is not None:
            hidden = hidden or local(p.tag) in ("clipPath", "mask", "pattern", "symbol", "marker")
            p = parents.get(p)
        if hidden:
            continue
        props = dict(kv.split(":", 1) for kv in (el.get("style") or "").split(";") if ":" in kv)
        props = {k.strip().lower(): v.strip() for k, v in props.items()}
        for attr in ("fill", "stroke", "stop-color"):
            c = normalize_color(props.get(attr, el.get(attr)))
            if c and c not in found:
                found.append(c)
        painted = painted or local(el.tag) in SHAPE_TAGS
    if not found and painted:
        found = ["#000000"]
    light = lambda hx: colorsys.rgb_to_hls(*[int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)])[1]
    return len(found) > 1 and any(light(c) > 0.97 for c in found)


# ---------------------------------------------------------------- geometry: bounding box of the painted artwork

def mat_mul(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def parse_transform(s):
    m = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in NUM_RE.findall(args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate":
            a = math.radians(v[0])
            r = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            t = mat_mul(mat_mul((1, 0, 0, 1, v[1], v[2]), r), (1, 0, 0, 1, -v[1], -v[2])) if len(v) == 3 else r
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = mat_mul(m, t)
    return m


def tokenize_path(d):
    """Command letters and numbers; handles compact arc flags such as 'a10 10 0 0110 10'."""
    out, i, n, cmd, argi = [], 0, len(d or ""), None, 0
    while i < n:
        ch = d[i]
        if ch.isspace() or ch == ",":
            i += 1
        elif ch.isalpha() and ch not in "eE":
            cmd, argi = ch.upper(), 0
            out.append(ch)
            i += 1
        elif cmd == "A" and argi % 7 in (3, 4) and ch in "01":
            out.append(ch)
            argi += 1
            i += 1
        else:
            m = NUM_RE.match(d, i)
            if not m:
                i += 1
                continue
            out.append(m.group(0))
            argi += 1
            i = m.end()
    return out


def parse_path(d):
    """Subpaths of absolute segments: ('L', p0, p1) | ('C', p0, c1, c2, p1) | ('Q', p0, c, p1) | ('A', p0, p1, arc)."""
    tokens = tokenize_path(d)
    subpaths, segs = [], []
    cur = start = (0.0, 0.0)
    last_ctrl = last_cmd = cmd = None
    i = 0
    is_cmd = lambda t: re.fullmatch(r"[A-Za-z]", t)

    def num():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    while i < len(tokens):
        t = tokens[i]
        if is_cmd(t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if segs:
                    if cur != start:
                        segs.append(("L", cur, start))
                    subpaths.append(segs)
                    segs = []
                cur, last_ctrl, last_cmd = start, None, "Z"
                continue
        if cmd is None:
            i += 1
            continue
        up, rel = cmd.upper(), cmd.islower()
        need = ARGC[up]
        if i + need > len(tokens) or any(is_cmd(tokens[j]) for j in range(i, i + need)):
            i += 1  # malformed: skip token
            continue
        ox, oy = cur if rel else (0.0, 0.0)
        if up == "M":
            x, y = num() + ox, num() + oy
            if segs:
                subpaths.append(segs)
                segs = []
            cur = start = (x, y)
            cmd, last_ctrl = ("l" if rel else "L"), None  # implicit lineto after moveto
        elif up in "LHV":
            if up == "L":
                p = (num() + ox, num() + oy)
            elif up == "H":
                p = (num() + (cur[0] if rel else 0), cur[1])
            else:
                p = (cur[0], num() + (cur[1] if rel else 0))
            segs.append(("L", cur, p))
            cur, last_ctrl = p, None
        elif up in "CS":
            if up == "C":
                c1 = (num() + ox, num() + oy)
            else:
                c1 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_cmd in ("C", "S") and last_ctrl else cur
            c2 = (num() + ox, num() + oy)
            p = (num() + ox, num() + oy)
            segs.append(("C", cur, c1, c2, p))
            cur, last_ctrl = p, c2
        elif up in "QT":
            if up == "Q":
                c = (num() + ox, num() + oy)
            else:
                c = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_cmd in ("Q", "T") and last_ctrl else cur
            p = (num() + ox, num() + oy)
            segs.append(("Q", cur, c, p))
            cur, last_ctrl = p, c
        elif up == "A":
            rx, ry, rot = abs(num()), abs(num()), num()
            fa, fs = num(), num()
            p = (num() + ox, num() + oy)
            segs.append(("A", cur, p, (rx, ry, rot, int(fa) != 0, int(fs) != 0)))
            cur, last_ctrl = p, None
        last_cmd = up if up != "M" else "L"
    if segs:
        subpaths.append(segs)
    return subpaths


def arc_points(p0, p1, params, steps=24):
    rx, ry, phi_deg, fa, fs = params
    if rx == 0 or ry == 0 or p0 == p1:
        return [p0, p1]
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num_ = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    coef = math.sqrt(max(0.0, num_ / den)) if den else 0.0
    if fa == fs:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (p0[0] + p1[0]) / 2
    cy = sp * cxp + cp * cyp + (p0[1] + p1[1]) / 2
    ang = lambda u, v: math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
    t1 = ang((1, 0), ((x1p - cxp) / rx, (y1p - cyp) / ry))
    dt = ang(((x1p - cxp) / rx, (y1p - cyp) / ry), ((-x1p - cxp) / rx, (-y1p - cyp) / ry))
    if not fs and dt > 0:
        dt -= 2 * math.pi
    elif fs and dt < 0:
        dt += 2 * math.pi
    return [(cx + rx * math.cos(t) * cp - ry * math.sin(t) * sp, cy + rx * math.cos(t) * sp + ry * math.sin(t) * cp)
            for t in (t1 + dt * k / steps for k in range(steps + 1))]


def segment_points(seg, steps=16):
    kind = seg[0]
    if kind == "L":
        return [seg[1], seg[2]]
    if kind == "C":
        p0, c1, c2, p1 = seg[1:]
        return [((1 - t) ** 3 * p0[0] + 3 * (1 - t) * (1 - t) * t * c1[0] + 3 * (1 - t) * t * t * c2[0] + t ** 3 * p1[0],
                 (1 - t) ** 3 * p0[1] + 3 * (1 - t) * (1 - t) * t * c1[1] + 3 * (1 - t) * t * t * c2[1] + t ** 3 * p1[1])
                for t in (k / steps for k in range(steps + 1))]
    if kind == "Q":
        p0, c, p1 = seg[1:]
        return [((1 - t) * (1 - t) * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
                 (1 - t) * (1 - t) * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1])
                for t in (k / steps for k in range(steps + 1))]
    return arc_points(seg[1], seg[2], seg[3]) if kind == "A" else []


def shape_to_subpaths(el):
    tag = local(el.tag)
    f = lambda k, d=0.0: float(re.sub(r"[^0-9.eE+-]", "", el.get(k, str(d))) or d)
    if tag == "path":
        return parse_path(el.get("d", ""))
    if tag == "rect":
        x, y, w, h = f("x"), f("y"), f("width"), f("height")
        k = f("rx", 0) or f("ry", 0)
        if k:
            k = min(k, w / 2, h / 2)
            return parse_path(f"M{x + k},{y} H{x + w - k} A{k},{k} 0 0 1 {x + w},{y + k} V{y + h - k} "
                              f"A{k},{k} 0 0 1 {x + w - k},{y + h} H{x + k} A{k},{k} 0 0 1 {x},{y + h - k} "
                              f"V{y + k} A{k},{k} 0 0 1 {x + k},{y} Z")
        return parse_path(f"M{x},{y} H{x + w} V{y + h} H{x} Z")
    if tag in ("circle", "ellipse"):
        cx, cy = f("cx"), f("cy")
        rx = f("r") if tag == "circle" else f("rx")
        ry = f("r") if tag == "circle" else f("ry")
        return parse_path(f"M{cx - rx},{cy} A{rx},{ry} 0 1 0 {cx + rx},{cy} A{rx},{ry} 0 1 0 {cx - rx},{cy} Z")
    if tag in ("polygon", "polyline"):
        nums = [float(n) for n in NUM_RE.findall(el.get("points", ""))]
        pts = list(zip(nums[0::2], nums[1::2]))
        if not pts:
            return []
        return parse_path("M" + " L".join(f"{x},{y}" for x, y in pts) + (" Z" if tag == "polygon" else ""))
    if tag == "line":
        return parse_path(f"M{f('x1')},{f('y1')} L{f('x2')},{f('y2')}")
    return []


@functools.lru_cache(maxsize=16)  # square, favicon and app icon all measure the same root
def artwork_bbox(root):
    """Union bbox of every visible shape with ancestor transforms applied (defs/clipPath/... skipped)."""
    bbox = None

    def walk(el, m, hidden):
        nonlocal bbox
        tag = local(el.tag)
        hidden = hidden or tag in HIDDEN_TAGS
        mm = mat_mul(m, parse_transform(el.get("transform")))
        if tag in SHAPE_TAGS and not hidden:
            for sp in shape_to_subpaths(el):
                pts = [(mm[0] * x + mm[2] * y + mm[4], mm[1] * x + mm[3] * y + mm[5])
                       for seg in sp for x, y in segment_points(seg)]
                if pts:
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    b = (min(xs), min(ys), max(xs), max(ys))
                    bbox = b if bbox is None else (min(bbox[0], b[0]), min(bbox[1], b[1]),
                                                   max(bbox[2], b[2]), max(bbox[3], b[3]))
        for ch in el:
            walk(ch, mm, hidden)
    walk(root, IDENTITY, False)
    return bbox


def view_box(root):
    vb = root.get("viewBox")
    if vb:
        parts = [float(x) for x in re.split(r"[ ,]+", vb.strip()) if x]
        if len(parts) == 4:
            return tuple(parts)
    try:
        w = float(re.sub(r"[^0-9.]", "", root.get("width", "")) or 0)
        h = float(re.sub(r"[^0-9.]", "", root.get("height", "")) or 0)
        if w and h:
            return (0.0, 0.0, w, h)
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------- variants (same output as export_variants.py)

def recolor(raw, color, keep_white=False):
    def swap(value):
        v = value.strip()
        low = v.lower()
        if low in ("none", "transparent") or low.startswith("url("):
            return v
        norm = normalize_color(v) or (low if low == "currentcolor" else None)
        if norm is None or (keep_white and norm == "#ffffff"):
            return v
        return color

    raw = PAINT_ATTR.sub(lambda m: f'{m.group(1)}="{swap(m.group(2))}"', raw)
    raw = PAINT_CSS.sub(lambda m: f"{m.group(1)}:{swap(m.group(2))}", raw)
    # Unpainted shapes default to black; give the root a fill so they follow the new colour.
    return re.sub(r"<svg\b(?![^>]*\bfill=)", f'<svg fill="{color}"', raw, count=1)


def set_title(raw, title):
    if not title:
        return raw
    raw = re.sub(r"<title>.*?</title>", "", raw, flags=re.S)
    return re.sub(r"(<svg\b[^>]*>)", lambda m: m.group(1) + f"<title>{html.escape(title)}</title>", raw, count=1)


def square_wrap(raw, root, padding=0.1, bg=None, radius=0.0, fg=None, symbol_scale=None, offset=0.0, title=None):
    """Centre the artwork's real bounding box on a 256x256 canvas (optionally on a rounded tile)."""
    vb = view_box(root)
    bb = artwork_bbox(root) or (vb[0], vb[1], vb[0] + vb[2], vb[1] + vb[3])
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    s = round(256.0 * (symbol_scale if symbol_scale else 1 - 2 * padding) / max(w, h), 3)
    tx = round((256.0 - w * s) / 2 - bb[0] * s, 2)
    ty = round((256.0 - h * s) / 2 - bb[1] * s + offset * 256.0, 2)
    src = recolor(raw, fg) if fg else raw
    m = re.search(r"<svg\b[^>]*>(.*)</svg>", src, re.S)
    body = re.sub(r"<title>.*?</title>", "", m.group(1) if m else src, flags=re.S)
    root_tag = re.search(r"<svg\b[^>]*>", src)
    carried = ""
    if root_tag:
        for attr in ("fill", "stroke", "fill-rule", "clip-rule", "stroke-width", "stroke-linecap", "stroke-linejoin", "style"):
            am = re.search(r'\s%s\s*=\s*"([^"]*)"' % re.escape(attr), root_tag.group(0))
            if am:
                carried += f' {attr}="{am.group(1)}"'
    tile = f'<rect width="256" height="256" rx="{256.0 * radius:g}" fill="{bg}"/>' if bg else ""
    t = f"<title>{html.escape(title)}</title>" if title else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">{t}'
            f'{tile}<g transform="translate({tx:g} {ty:g}) scale({s:g})"{carried}>{body}</g></svg>')


def variants(raw, root, small_raw, small_root, mono=(), title=None, keep_white=False, icon_bg="#111111",
             icon_fg="#ffffff", icon_scale=0.62, offset=0.0, only=None):
    """{suffix: svg text} in export_variants.py's order."""
    want = set(only) if only else {"black", "white", "mono", "square", "favicon", "app-icon"}
    fg = None if icon_fg == "keep" else icon_fg
    out = {}
    if "black" in want:
        out["black"] = set_title(recolor(raw, "#000000", keep_white), title)
    if "white" in want:
        out["white"] = set_title(recolor(raw, "#ffffff"), title)
    if "mono" in want:
        for c in mono:
            hx = normalize_color(c)
            if not hx:
                print("skip invalid colour", c)
                continue
            out[f"mono-{hx[1:]}"] = set_title(recolor(raw, hx, keep_white), title)
    if "square" in want:
        out["square"] = square_wrap(raw, root, padding=0.08, offset=offset, title=title)
    if "favicon" in want:
        out["favicon"] = square_wrap(small_raw, small_root, padding=0.02, offset=offset, title=title)
    if "app-icon" in want:
        out["app-icon"] = square_wrap(small_raw, small_root, bg=icon_bg, radius=0.225, fg=fg,
                                      symbol_scale=icon_scale, offset=offset, title=title)
    return out


# ---------------------------------------------------------------- contact sheet

def data_uri(svg):
    """<image> source; adds width/height from the viewBox, since viewBox-only SVGs get a 300x150 box."""
    tag = re.search(r"<svg\b[^>]*>", svg)
    vb = re.search(r'viewBox\s*=\s*"([^"]+)"', tag.group(0)) if tag else None
    if vb and not (re.search(r'\swidth\s*=', tag.group(0)) and re.search(r'\sheight\s*=', tag.group(0))):
        parts = [p for p in re.split(r"[ ,]+", vb.group(1).strip()) if p]
        if len(parts) == 4:
            new = re.sub(r'\s(width|height)\s*=\s*"[^"]*"', "", tag.group(0))
            svg = svg.replace(tag.group(0), new[:-1].rstrip("/") + f' width="{parts[2]}" height="{parts[3]}">', 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def sheet(name, raw, root, out, light="#F4F5F7", dark="#14161A"):
    """One page: master on light and dark, one-colour versions, and favicon/app icon at real sizes."""
    vb = view_box(root) or (0, 0, 100, 100)
    ratio = vb[2] / vb[3]
    W, items = 960, []
    font = "font-family=\"system-ui,-apple-system,'Segoe UI',sans-serif\""

    def img(svg, x, y, w, h):
        items.append(f'<image x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" href="{data_uri(svg)}"/>')

    def label(x, y, text, fill="#6B7280"):
        items.append(f'<text x="{x:g}" y="{y:g}" fill="{fill}" font-size="12" {font}>{html.escape(text)}</text>')

    def fit(svg, x, y, w, h, r):
        bw, bh = (w, w / r) if w / r <= h else (h * r, h)
        img(svg, x + (w - bw) / 2, y + (h - bh) / 2, bw, bh)

    items.append(f'<rect width="{W}" height="660" fill="#FFFFFF"/>')
    items.append(f'<text x="32" y="44" fill="#111827" font-size="22" font-weight="700" {font}>'
                 f'{html.escape(name)} — logo pack</text>')
    # Row 1: master on light and dark.
    items.append(f'<rect x="32" y="68" width="440" height="240" rx="12" fill="{light}"/>')
    items.append(f'<rect x="488" y="68" width="440" height="240" rx="12" fill="{dark}"/>')
    fit(raw, 72, 98, 360, 180, ratio)
    fit(out.get("white", raw), 528, 98, 360, 180, ratio)
    label(32, 328, "master on light")
    label(488, 328, "white on dark")
    # Row 2: one-colour versions.
    mono = [(k, v) for k, v in out.items() if k == "black" or k.startswith("mono-")]
    cw = (W - 64 - 16 * max(len(mono) - 1, 0)) / max(len(mono), 1)
    for i, (k, v) in enumerate(mono):
        x = 32 + i * (cw + 16)
        items.append(f'<rect x="{x:g}" y="352" width="{cw:g}" height="120" rx="12" fill="{light}"/>')
        fit(v, x + 20, 368, cw - 40, 88, ratio)
        label(x, 492, k)
    # Row 3: favicon and app icon at the sizes they are actually seen.
    x = 32
    for k, bg in (("favicon", light), ("favicon", dark), ("app-icon", light)):
        if k not in out:
            continue
        items.append(f'<rect x="{x:g}" y="516" width="288" height="100" rx="12" fill="{bg}"/>')
        cx = x + 20
        for size in (64, 32, 16):
            img(out[k], cx, 566 - size / 2, size, size)
            cx += size + 24
        label(x, 636, f"{k} 64 / 32 / 16 px" + (" on dark" if bg == dark and k == "favicon" else ""))
        x += 304
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="660" viewBox="0 0 {W} 660">'
            f"<title>{html.escape(name)} logo pack</title>\n" + "\n".join(items) + "\n</svg>\n")


def load_svg(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        raw = fh.read()
    return raw, ET.fromstring(raw)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master")
    ap.add_argument("--out-dir")
    ap.add_argument("--name", help="base name for outputs (default: master file name)")
    ap.add_argument("--title", help="accessible <title> for every output, e.g. 'Harbor logo'")
    ap.add_argument("--mono", action="append", default=[], help="extra one-colour version(s), e.g. '#0F7C80'")
    ap.add_argument("--icon-bg", default="#111111", help="app-icon tile colour")
    ap.add_argument("--icon-fg", default="#ffffff", help="mark colour on the tile ('keep' = original colours)")
    ap.add_argument("--icon-scale", type=float, default=0.62, help="mark size on the app-icon tile (0.55-0.7 typical)")
    ap.add_argument("--optical-offset", type=float, default=0.0, help="vertical nudge for square outputs (negative = up)")
    ap.add_argument("--favicon-source", help="simplified small-size drawing used for favicon/app-icon")
    ap.add_argument("--keep-white", action="store_true", help="leave pure-white paint untouched in one-colour versions")
    ap.add_argument("--only", nargs="*", help="subset: black white mono square favicon app-icon")
    ap.add_argument("--no-sheet", action="store_true", help="skip <name>-sheet.svg")
    a = ap.parse_args(argv)

    raw, root = load_svg(a.master)
    small_raw, small_root = load_svg(a.favicon_source) if a.favicon_source else (raw, root)
    out_dir = a.out_dir or os.path.dirname(os.path.abspath(a.master))
    os.makedirs(out_dir, exist_ok=True)
    base = a.name or os.path.splitext(os.path.basename(a.master))[0]
    out = variants(raw, root, small_raw, small_root, a.mono, a.title, a.keep_white, a.icon_bg, a.icon_fg,
                   a.icon_scale, a.optical_offset, a.only)
    files = {f"{base}-{k}.svg": v for k, v in out.items()}
    if not a.no_sheet:
        files[f"{base}-sheet.svg"] = sheet(a.title or base, raw, root, out)
    if has_white_paint(root):
        print("note: master contains white paint — check the one-colour files for blobs (fake cut-outs).")
    for fname, content in files.items():
        p = os.path.join(out_dir, fname)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
