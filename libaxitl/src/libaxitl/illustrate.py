"""An illustration's SVG as pen strokes inside the box layout gave it (§3.5).

A pen plotter draws lines, so every shape becomes the polyline of its outline: paths (arcs included),
lines, polylines, polygons, rectangles, circles and ellipses, through any nesting of groups and transforms.
What a pen can't draw is left out and reported: text, embedded images, ``<use>`` references and foreign
objects. Each shape keeps how the SVG paints it (its fill and stroke colours and fill rule), so ``draw`` can
hatch its fill and choose its pens (§3.5); with neither asked for, a filled shape is drawn as its outline, which is
reported once per illustration.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .colours import ColourError, parse_colour
from .geometry import Box
from .illustration import intrinsic_size
from .svgpath import IDENTITY, Matrix, PathError, Point, Segment, apply_matrix, flatten, multiply, parse_path

_NOT_DRAWN = {
    "defs", "metadata", "title", "desc", "clipPath", "mask", "pattern", "symbol", "style", "script", "marker",
    "linearGradient", "radialGradient", "filter",
}
_UNPLOTTABLE = {"text": "text", "image": "embedded images", "use": "<use> references", "foreignObject": "foreign objects"}
_SHAPES = {"path", "line", "polyline", "polygon", "rect", "circle", "ellipse"}
_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _number(value: str | None, default: float = 0.0) -> float:
    m = _NUMBER.match(value or "")
    return float(m.group(1)) if m else default


def _style(el: ET.Element, name: str) -> str | None:
    """A presentation property, from the style attribute or the attribute of the same name."""
    for part in (el.get("style") or "").split(";"):
        key, _, value = part.partition(":")
        if key.strip() == name:
            return value.strip()
    return el.get(name)


def parse_transform(text: str | None) -> Matrix:
    m = IDENTITY
    for name, args in _TRANSFORM.findall(text or ""):
        v = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            t = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0], 0.0, 0.0)
        elif name == "rotate" and v:
            a = math.radians(v[0])
            t = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0.0, 0.0)
            if len(v) == 3:
                cx, cy = v[1], v[2]
                t = multiply(multiply((1.0, 0.0, 0.0, 1.0, cx, cy), t), (1.0, 0.0, 0.0, 1.0, -cx, -cy))
        elif name == "skewX" and v:
            t = (1.0, 0.0, math.tan(math.radians(v[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and v:
            t = (1.0, math.tan(math.radians(v[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = multiply(m, t)
    return m


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> str:
    return f"M {cx + rx} {cy} A {rx} {ry} 0 1 1 {cx - rx} {cy} A {rx} {ry} 0 1 1 {cx + rx} {cy} Z"


def _shape(el: ET.Element, tag: str) -> tuple[Segment, ...]:
    g = el.get
    if tag == "path":
        return parse_path(g("d") or "")
    if tag == "line":
        return (("M", _number(g("x1")), _number(g("y1"))), ("L", _number(g("x2")), _number(g("y2"))))
    if tag in ("polyline", "polygon"):
        values = [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", g("points") or "")]
        pairs = list(zip(values[0::2], values[1::2], strict=False))
        if len(pairs) < 2:
            return ()
        segs = [("M", *pairs[0])] + [("L", *p) for p in pairs[1:]]
        return tuple(segs + ([("Z",)] if tag == "polygon" else []))
    if tag == "rect":
        x, y, w, h = _number(g("x")), _number(g("y")), _number(g("width")), _number(g("height"))
        if w <= 0 or h <= 0:
            return ()
        rx, ry = _number(g("rx"), -1), _number(g("ry"), -1)
        rx, ry = (ry if rx < 0 else rx), (rx if ry < 0 else ry)
        rx, ry = min(max(rx, 0), w / 2), min(max(ry, 0), h / 2)
        if rx == 0 or ry == 0:
            return parse_path(f"M {x} {y} H {x + w} V {y + h} H {x} Z")
        return parse_path(
            f"M {x + rx} {y} H {x + w - rx} A {rx} {ry} 0 0 1 {x + w} {y + ry} V {y + h - ry} "
            f"A {rx} {ry} 0 0 1 {x + w - rx} {y + h} H {x + rx} A {rx} {ry} 0 0 1 {x} {y + h - ry} "
            f"V {y + ry} A {rx} {ry} 0 0 1 {x + rx} {y} Z"
        )
    if tag == "circle":
        r = _number(g("r"))
        return parse_path(_ellipse(_number(g("cx")), _number(g("cy")), r, r)) if r > 0 else ()
    if tag == "ellipse":
        rx, ry = _number(g("rx")), _number(g("ry"))
        return parse_path(_ellipse(_number(g("cx")), _number(g("cy")), rx, ry)) if rx > 0 and ry > 0 else ()
    return ()


@dataclass(frozen=True)
class Shape:
    """One drawable element of an illustration: its outline in mm, and how the SVG paints it."""

    lines: tuple[tuple[Point, ...], ...]  # the outline, flattened; each subpath as a polyline
    fill: str | None  # #rrggbb, None for no fill, or UNREADABLE for paint that isn't a plain colour
    stroke: str | None  # likewise
    evenodd: bool  # fill-rule: evenodd (else nonzero, the SVG default)


UNREADABLE = "?"  # a gradient, pattern or other paint that isn't one plain colour


def _paint(value: str | None) -> str | None:
    try:
        return parse_colour(value)
    except ColourError:
        return UNREADABLE


def _opacity(el: ET.Element, name: str) -> bool:
    """False if the element says the property is fully transparent."""
    value = _style(el, name)
    return value is None or _number(value, 1.0) > 0


def _walk(root: ET.Element, matrix: Matrix):
    """Every drawable shape element: (element, tag, transform, fill, stroke, evenodd), with inherited paint;
    and, separately, notes on what can't be plotted."""
    shapes: list[tuple[ET.Element, str, Matrix, str | None, str | None, bool]] = []
    left_out: dict[str, None] = {}

    def walk(el: ET.Element, m: Matrix, fill: str | None, stroke: str | None, evenodd: bool) -> None:
        tag = _local(el.tag)
        if tag in _NOT_DRAWN or _style(el, "display") == "none" or _style(el, "visibility") == "hidden":
            return
        if not _opacity(el, "opacity"):
            return
        if tag in _UNPLOTTABLE:
            what = _UNPLOTTABLE[tag]
            left_out[f"{what} can't be plotted and {'is' if what == 'text' else 'are'} left out"] = None
            return
        m = multiply(m, parse_transform(el.get("transform")))
        if (value := _style(el, "fill")) is not None:
            fill = _paint(value)
        if (value := _style(el, "stroke")) is not None:
            stroke = _paint(value)
        if not _opacity(el, "fill-opacity"):
            fill = None
        if not _opacity(el, "stroke-opacity"):
            stroke = None
        if (rule := _style(el, "fill-rule")) is not None:
            evenodd = rule.strip() == "evenodd"
        if tag in _SHAPES:
            shapes.append((el, tag, m, fill, stroke, evenodd))
        for child in el:
            walk(child, m, fill, stroke, evenodd)

    walk(root, matrix, "#000000", None, False)  # SVG's default paint: filled black, no stroke
    return shapes, list(left_out)


def illustration_colours(content: bytes | str) -> tuple[list[str], bool]:
    """The plain colours an illustration paints with, in document order, and whether it also has paint that
    isn't a plain colour."""
    shapes, _ = _walk(ET.fromstring(content), IDENTITY)
    found: dict[str, None] = {}
    unreadable = False
    for *_, fill, stroke, _ in shapes:
        for paint in (fill, stroke):
            if paint == UNREADABLE:
                unreadable = True
            elif paint is not None:
                found[paint] = None
    return list(found), unreadable


def illustration_shapes(content: bytes | str, name: str, box: Box, max_piece: float) -> tuple[list[Shape], list[str]]:
    """The illustration's shapes, fitted into ``box`` in mm, and notes on anything left out."""
    root = ET.fromstring(content)
    box_ = (root.get("viewBox") or "").replace(",", " ").split()
    try:
        vx, vy, vw, vh = (float(v) for v in box_)
    except ValueError:
        vx, vy = 0.0, 0.0
        vw, vh = intrinsic_size(content, name)
    scale = min(box.width / vw, box.height / vh)  # the SVG default, xMidYMid meet
    dx = box.x0 + (box.width - vw * scale) / 2 - vx * scale
    dy = box.y0 + (box.height - vh * scale) / 2 - vy * scale
    found, notes = _walk(root, (scale, 0.0, 0.0, scale, dx, dy))
    shapes = []
    for el, tag, m, fill, stroke, evenodd in found:
        try:
            segments = _shape(el, tag)
        except PathError as exc:
            note = f"a path that can't be read is left out ({exc})"
            if note not in notes:
                notes.append(note)
            continue
        if segments:
            lines = flatten(apply_matrix(segments, m), max_piece)
            shapes.append(Shape(tuple(tuple(line) for line in lines), fill, stroke, evenodd))
    return shapes, notes


def illustration_strokes(content: bytes | str, name: str, box: Box, max_piece: float) -> tuple[list[list[Point]], list[str]]:
    """The illustration's outlines as polylines in mm, fitted into ``box``, and notes on anything left out."""
    shapes, notes = illustration_shapes(content, name, box, max_piece)
    if any(s.fill is not None for s in shapes):
        notes.append("filled shapes are drawn as their outlines only")
    return [list(line) for s in shapes for line in s.lines], notes
