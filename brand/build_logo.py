"""Build the Kraken 2.0 logo set as exact SVG geometry.

Concept "Reach & Return": a K on an 8x8 grid, one stroke weight. The upper arm
reaches out; the lower arm comes back and coils around a document.

Run: python brand/build_logo.py  (writes the SVG files next to this script)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

OUT = Path(__file__).resolve().parent
U = 10.0  # SVG units per grid unit

# Palette
NAVY = "#0A1A3F"
BLUE = "#2F6BFF"
RED = "#E5283A"
PAPER = "#F5F6F8"
WHITE = "#FFFFFF"


@dataclass(frozen=True)
class Geometry:
    sw: float = 1.0  # stroke weight (grid units)
    junction: tuple[float, float] = (2.0, 4.0)  # where both arms start
    reach: float = 3.5  # upper arm length along each axis (45 degrees)
    straight: float = 2 * math.sqrt(2)  # lower arm straight part, local frame
    r1: float = 2.0  # outer coil radius
    r2: float = 1.0  # inner coil radius
    a2: float = 90.0  # inner coil sweep (degrees)
    doc: float = 1.15  # document side (clearance = half a stroke)
    cut: float = 0.4  # document cut corner
    doc_offset: tuple[float, float] = (0.2, 0.1)  # optical centre of the coil eye


def f(v: float) -> str:
    s = f"{v * U:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def to_global(g: Geometry, x: float, y: float) -> tuple[float, float]:
    """Local frame of the lower arm (along +x) rotated 45 degrees at the junction."""
    c = s = math.sqrt(0.5)
    jx, jy = g.junction
    return jx + c * x - s * y, jy + s * x + c * y


def coil_points(g: Geometry, n: int = 90) -> list[tuple[float, float]]:
    """Centre line of the lower arm, in the local frame."""
    pts = [(0.0, 0.0), (g.straight, 0.0)]
    c1 = (g.straight, -g.r1)
    for i in range(n + 1):
        t = math.radians(90 - 180 * i / n)
        pts.append((c1[0] + g.r1 * math.cos(t), c1[1] + g.r1 * math.sin(t)))
    c2 = (g.straight, -2 * g.r1 + g.r2)
    for i in range(n + 1):
        t = math.radians(-90 - g.a2 * i / n)
        pts.append((c2[0] + g.r2 * math.cos(t), c2[1] + g.r2 * math.sin(t)))
    return pts


def lower_arm_path(g: Geometry) -> str:
    L = g.straight
    c2y = -2 * g.r1 + g.r2
    t = math.radians(-90 - g.a2)
    ex, ey = L + g.r2 * math.cos(t), c2y + g.r2 * math.sin(t)
    large = 1 if g.a2 > 180 else 0
    return (
        f"M0 0H{f(L)}"
        f"A{f(g.r1)} {f(g.r1)} 0 0 0 {f(L)} {f(-2 * g.r1)}"
        f"A{f(g.r2)} {f(g.r2)} 0 {large} 0 {f(ex)} {f(ey)}"
    )


def doc_path(g: Geometry) -> str:
    cx, cy = to_global(g, g.straight + g.doc_offset[0], -g.r1 + g.doc_offset[1])
    h = g.doc / 2
    x0, y0, x1, y1 = cx - h, cy - h, cx + h, cy + h
    return (
        f"M{f(x0)} {f(y0)}H{f(x1 - g.cut)}L{f(x1)} {f(y0 + g.cut)}"
        f"V{f(y1)}H{f(x0)}Z"
    )


def bbox(g: Geometry) -> tuple[float, float, float, float]:
    r = g.sw / 2
    jx, jy = g.junction
    pts = [(r, r), (r, 8 - r), (jx + g.reach, jy - g.reach)]
    pts += [to_global(g, x, y) for x, y in coil_points(g)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r


def _hex_to_oklab(h: str) -> tuple[float, float, float]:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(int(h[i : i + 2], 16) / 255) for i in (1, 3, 5))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _oklab_to_hex(L: float, a: float, b: float) -> str:
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )

    def enc(c: float) -> int:
        c = min(1.0, max(0.0, c))
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(c * 255)

    return "#" + "".join(f"{enc(c):02X}" for c in rgb)


def _mix_oklch(c0: str, c1: str, k: float) -> str:
    """Interpolate in OKLCH along the shorter hue arc: chroma stays high, no grey midpoint."""
    l0, a0, b0 = _hex_to_oklab(c0)
    l1, a1, b1 = _hex_to_oklab(c1)
    h0, h1 = math.atan2(b0, a0), math.atan2(b1, a1)
    dh = (h1 - h0 + math.pi) % (2 * math.pi) - math.pi
    ch0, ch1 = math.hypot(a0, b0), math.hypot(a1, b1)
    lum, ch, h = l0 + (l1 - l0) * k, ch0 + (ch1 - ch0) * k, h0 + dh * k
    return _oklab_to_hex(lum, ch * math.cos(h), ch * math.sin(h))


def ramp(stops: tuple[tuple[float, str], ...], t: float) -> str:
    """Colour at t in [0, 1] along the given stops."""
    t = min(1.0, max(0.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            return _mix_oklch(c0, c1, 0.0 if t1 == t0 else (t - t0) / (t1 - t0))
    return stops[-1][1]


@dataclass(frozen=True)
class Theme:
    body: str  # stem + upper arm
    grad: tuple[tuple[float, str], ...] | None  # lower arm colour along its length; None = solid
    doc: str


# The tentacle runs blue -> red along its length; it starts blue under the body's chevron.
TENTACLE = ((0.0, BLUE), (0.12, BLUE), (1.0, RED))
LIGHT = Theme(NAVY, TENTACLE, RED)
DARK = Theme(WHITE, TENTACLE, RED)
MONO = Theme("currentColor", None, "currentColor")


def _gradient(uid: str, p0: tuple[float, float], p1: tuple[float, float], stops: list[tuple[float, str]]) -> str:
    return (
        f'<linearGradient id="{uid}" gradientUnits="userSpaceOnUse" '
        f'x1="{f(p0[0])}" y1="{f(p0[1])}" x2="{f(p1[0])}" y2="{f(p1[1])}">'
        + "".join(f'<stop offset="{o:.4f}" stop-color="{c}"/>' for o, c in stops)
        + "</linearGradient>"
    )


def tentacle(g: Geometry, grad: tuple[tuple[float, str], ...], uid: str) -> tuple[str, str]:
    """Lower arm whose colour flows along its length.

    SVG has no path-following gradient, so the arcs are cut into short segments,
    each with a two-stop gradient along its chord (colours taken at the segment's
    arc length). Each segment starts slightly before the previous one ends, over
    the same colour, so no seam shows. Only the two free ends are round.
    """
    L, r1, r2 = g.straight, g.r1, g.r2
    total = L + math.pi * r1 + math.radians(g.a2) * r2
    overlap = math.radians(1.5)

    def col(s_: float) -> str:
        return ramp(grad, s_ / total)

    defs: list[str] = [_gradient(f"{uid}-0", (0, 0), (L, 0), [(k / 8, col(L * k / 8)) for k in range(9)])]
    paths: list[str] = [f'<path stroke="url(#{uid}-0)" stroke-linecap="round" d="M0 0H{f(L)}"/>']

    arcs = [  # centre, radius, start angle, sweep (negative = turning left on screen), arc length offset
        ((L, -r1), r1, math.radians(90), -math.pi, L, 24),
        ((L, -2 * r1 + r2), r2, math.radians(-90), -math.radians(g.a2), L + math.pi * r1, 8),
    ]
    k = 0
    for (cx, cy), rad, a0, sweep, s0, n in arcs:
        for i in range(n):
            ta = a0 + sweep * i / n
            tb = a0 + sweep * (i + 1) / n
            ta_ext = ta + overlap  # reach back over the previous segment (sweep < 0)
            pa = (cx + rad * math.cos(ta_ext), cy + rad * math.sin(ta_ext))
            pb = (cx + rad * math.cos(tb), cy + rad * math.sin(tb))
            sa = s0 + rad * abs(ta - a0) - rad * overlap
            sb = s0 + rad * abs(tb - a0)
            k += 1
            defs.append(_gradient(f"{uid}-{k}", pa, pb, [(0.0, col(max(sa, 0))), (1.0, col(sb))]))
            paths.append(
                f'<path stroke="url(#{uid}-{k})" stroke-linecap="butt" '
                f'd="M{f(pa[0])} {f(pa[1])}A{f(rad)} {f(rad)} 0 0 0 {f(pb[0])} {f(pb[1])}"/>'
            )
            tip = pb
    # Round tip as its own disc (a round cap would repaint the previous segment).
    # Painted first so the last segment covers its back half.
    paths.insert(0, f'<circle cx="{f(tip[0])}" cy="{f(tip[1])}" r="{f(g.sw / 2)}" fill="{col(total)}" stroke="none"/>')
    return "".join(defs), "".join(paths)


def mark_group(g: Geometry, th: Theme, uid: str) -> str:
    r = g.sw / 2
    jx, jy = g.junction
    if th.grad:
        defs, arm = tentacle(g, th.grad, uid)
        defs = f"<defs>{defs}</defs>"
    else:
        defs, arm = "", f'<path stroke="{th.body}" d="{lower_arm_path(g)}"/>'
    stroke = f'fill="none" stroke-width="{f(g.sw)}" stroke-linecap="round" stroke-linejoin="round"'
    return (
        f"{defs}"
        f"<g {stroke}>"
        f'<g transform="translate({f(jx)} {f(jy)}) rotate(45)">{arm}</g>'
        f'<path stroke="{th.body}" d="M{f(r)} {f(r)}V{f(8 - r)}'
        f'M{f(jx)} {f(jy)}L{f(jx + g.reach)} {f(jy - g.reach)}"/>'
        f"</g>"
        f'<path fill="{th.doc}" d="{doc_path(g)}"/>'
    )


def mark_svg(g: Geometry, th: Theme, uid: str, pad: float = 0.0, bg: str | None = None) -> str:
    x0, y0, x1, y1 = bbox(g)
    side = max(x1 - x0, y1 - y0) + 2 * pad
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vx, vy = cx - side / 2, cy - side / 2
    rect = f'<rect x="{f(vx)}" y="{f(vy)}" width="{f(side)}" height="{f(side)}" fill="{bg}"/>' if bg else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{f(vx)} {f(vy)} {f(side)} {f(side)}">'
        f"<title>Kraken 2.0</title>{rect}{mark_group(g, th, uid)}</svg>\n"
    )


# --- Wordmark: drawn monoline capitals, no font dependency -------------------

@dataclass(frozen=True)
class Type:
    h: float = 2.8  # centre-line cap height (outer cap height = h + w)
    w: float = 0.42  # stroke weight
    track: float = 1.0  # space between letter boxes
    space: float = 1.7  # space between KRAKEN and 2.0


def _letters(t: Type) -> dict[str, tuple[float, list[str]]]:
    """Each glyph: (width, path data in a centre-line box 0..width x 0..h)."""
    h, w = t.h, t.w
    gap = 1.5 * w  # K: the arms float off the stem, like the mark
    half = h / 2
    rb = 0.74  # R bowl radius
    bx = 0.8
    r2 = 0.76  # "2" bowl radius
    a45 = math.radians(45)
    p2 = (round(r2 + r2 * math.cos(a45), 4), round(r2 + r2 * math.sin(a45), 4))
    h, half, gap = round(h, 4), round(half, 4), round(gap, 4)
    return {
        "K": (gap + half, [f"M0 0V{h}", f"M{gap + half} 0L{gap} {half}L{gap + half} {h}"]),
        "R": (bx + rb, [f"M0 {h}V0H{bx}A{rb} {rb} 0 0 1 {bx} {2 * rb}H0", f"M{bx} {2 * rb}L{bx + rb} {h}"]),
        "A": (2.2, [f"M0 {h}L1.1 0L2.2 {h}", f"M{1.1 * 0.36} {h * 0.64}H{2.2 - 1.1 * 0.36}"]),
        "E": (1.45, [f"M1.45 0H0V{h}H1.45", f"M0 {half}H1.25"]),
        "N": (1.95, [f"M0 {h}V0L1.95 {h}V0"]),
        "2": (2 * r2, [f"M0 {r2}A{r2} {r2} 0 1 1 {p2[0]} {p2[1]}L0 {h}H{2 * r2}"]),
        ".": (0.0, []),
        "0": (1.5, [f"M0.75 0A0.75 0.75 0 0 1 1.5 0.75V{h - 0.75}A0.75 0.75 0 0 1 0 {h - 0.75}V0.75A0.75 0.75 0 0 1 0.75 0Z"]),
    }




def wordmark(t: Type, ox: float, oy: float, body: str, accent: str) -> tuple[str, float]:
    """KRAKEN in the body colour, 2.0 in the accent colour. Returns (svg, width in grid units)."""
    glyphs = _letters(t)
    x = ox + t.w / 2
    parts: dict[str, list[str]] = {"body": [], "accent": []}
    dots: list[str] = []
    for i, ch in enumerate("KRAKEN 2.0"):
        if ch == " ":
            x += t.space - t.track
            continue
        width, ds = glyphs[ch]
        tone = "body" if i < 6 else "accent"
        if ch == ".":
            dots.append(f'<circle cx="{f(x)}" cy="{f(oy + t.w / 2 + t.h)}" r="{f(t.w * 0.62)}" fill="{accent}"/>')
            x += t.track * 0.7
            continue
        for d in ds:
            # Glyphs are written in grid units: scale them (stroke width is set in grid units too).
            parts[tone].append(f'<path transform="translate({f(x)} {f(oy + t.w / 2)}) scale({U:g})" d="{d}"/>')
        x += width + t.track
    x -= t.track
    common = f'fill="none" stroke-width="{t.w:g}" stroke-linecap="round" stroke-linejoin="round"'
    svg = (
        f'<g {common} stroke="{body}">{"".join(parts["body"])}</g>'
        f'<g {common} stroke="{accent}">{"".join(parts["accent"])}</g>' + "".join(dots)
    )
    return svg, x + t.w / 2 - ox


def lockup_svg(g: Geometry, th: Theme, accent: str, uid: str, pad: float = 1.0) -> str:
    """Mark + wordmark, wordmark centred on the mark's height."""
    t = Type()
    x0, y0, x1, y1 = bbox(g)
    cap = t.h + t.w
    wx = x1 + 2.6
    wy = (y0 + y1) / 2 - cap / 2
    words, ww = wordmark(t, wx, wy, th.body, accent)
    vx, vy = x0 - pad, y0 - pad
    vw, vh = (wx + ww + pad) - vx, (y1 + pad) - vy
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{f(vx)} {f(vy)} {f(vw)} {f(vh)}">'
        f"<title>Kraken 2.0</title>{mark_group(g, th, uid)}{words}</svg>\n"
    )


def wordmark_svg(body: str, accent: str, pad: float = 0.4) -> str:
    t = Type()
    words, ww = wordmark(t, 0, 0, body, accent)
    cap = t.h + t.w
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{f(-pad)} {f(-pad)} {f(ww + 2 * pad)} {f(cap + 2 * pad)}">'
        f"<title>Kraken 2.0</title>{words}</svg>\n"
    )


def app_icon_svg(g: Geometry, uid: str) -> str:
    """Navy rounded tile with the dark mark: favicon, app icon, avatar."""
    x0, y0, x1, y1 = bbox(g)
    side = 8 / 0.64  # mark takes 64 % of the tile
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vx, vy = cx - side / 2, cy - side / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{f(vx)} {f(vy)} {f(side)} {f(side)}">'
        f"<title>Kraken 2.0</title>"
        f'<rect x="{f(vx)}" y="{f(vy)}" width="{f(side)}" height="{f(side)}" rx="{f(side * 0.22)}" fill="{NAVY}"/>'
        f"{mark_group(g, DARK, uid)}</svg>\n"
    )


def main() -> None:
    g = Geometry()
    files = {
        "kraken-mark.svg": mark_svg(g, LIGHT, "kg-l"),
        "kraken-mark-dark.svg": mark_svg(g, DARK, "kg-d"),
        "kraken-mark-mono.svg": mark_svg(g, MONO, "kg-m"),
        "kraken-lockup.svg": lockup_svg(g, LIGHT, RED, "kl-l"),
        "kraken-lockup-dark.svg": lockup_svg(g, DARK, RED, "kl-d"),
        "kraken-lockup-mono.svg": lockup_svg(g, MONO, "currentColor", "kl-m"),
        "kraken-wordmark.svg": wordmark_svg(NAVY, RED),
        "kraken-wordmark-dark.svg": wordmark_svg(WHITE, RED),
        "kraken-app-icon.svg": app_icon_svg(g, "ki"),
        "favicon.svg": app_icon_svg(g, "kf"),
    }
    for name, svg in files.items():
        (OUT / name).write_text(svg, encoding="utf-8")
        print("wrote", name)
    # The demo UI serves only static/: keep its copies in sync.
    static = OUT.parent / "static"
    for name in ("kraken-lockup-dark.svg", "favicon.svg"):
        (static / name).write_text(files[name], encoding="utf-8")
        print("wrote static/" + name)


if __name__ == "__main__":
    main()
