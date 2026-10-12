"""SVG path handling for glyphs and illustrations.

Paths are normalised to absolute ``M``, ``L``, ``C`` and ``Z`` commands. Relative commands, ``H``/``V``, the
smooth and quadratic curve forms and elliptical arcs are all converted on the way in (arcs and quadratics
exactly or to within a hair, as cubic Béziers). For the plotter, :func:`flatten` turns curves into polylines.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

from .units import format_number

# A segment is a tuple: ("M", x, y) | ("L", x, y) | ("C", x1, y1, x2, y2, x, y) | ("Z",)
Segment = tuple

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARG_COUNTS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


class PathError(ValueError):
    pass


def parse_path(d: str) -> tuple[Segment, ...]:
    """Parse SVG path data into absolute M/L/C/Z segments."""
    if _TOKEN.sub("", d).strip(" \t\r\n,"):
        raise PathError(f"unreadable path data: {d[:40]!r}")
    tokens = _TOKEN.findall(d)
    out: list[Segment] = []
    i = 0
    cmd = None
    cx = cy = 0.0  # current point
    sx = sy = 0.0  # subpath start
    last_ctrl: tuple[float, float] | None = None  # for S/T reflection
    last_cmd = None
    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                out.append(("Z",))
                cx, cy = sx, sy
                last_cmd, last_ctrl = "Z", None
                continue
        elif cmd is None:
            raise PathError("path data must start with a command")
        upper = cmd.upper()
        rel = cmd.islower()
        if upper == "A":
            vals = []
            while len(vals) < 7:
                if i >= len(tokens) or tokens[i].isalpha():
                    raise PathError(f"command {cmd} is missing arguments")
                tok = tokens[i]
                if len(vals) in (3, 4):  # flags are one character each and may run into what follows
                    if tok[0] not in "01":
                        raise PathError("arc flags must be 0 or 1")
                    vals.append(float(tok[0]))
                    if len(tok) > 1:
                        tokens[i] = tok[1:]
                        continue
                else:
                    vals.append(float(tok))
                i += 1
            rx, ry, angle, large, sweep, x, y = vals
            if rel:
                x, y = cx + x, cy + y
            out.extend(arc_to_cubics(cx, cy, rx, ry, angle, bool(large), bool(sweep), x, y))
            cx, cy = x, y
            last_cmd, last_ctrl = "A", None
            continue
        n = _ARG_COUNTS[upper]
        args = tokens[i : i + n]
        if len(args) < n or any(a.isalpha() for a in args):
            raise PathError(f"command {cmd} is missing arguments")
        vals = [float(a) for a in args]
        i += n
        if upper == "M":
            x, y = (cx + vals[0], cy + vals[1]) if rel else (vals[0], vals[1])
            out.append(("M", x, y))
            cx, cy = sx, sy = x, y
            last_ctrl = None
            cmd = "l" if rel else "L"  # subsequent pairs are implicit lineto
        elif upper in "LHV":
            if upper == "L":
                x, y = (cx + vals[0], cy + vals[1]) if rel else (vals[0], vals[1])
            elif upper == "H":
                x, y = (cx + vals[0] if rel else vals[0]), cy
            else:
                x, y = cx, (cy + vals[0] if rel else vals[0])
            out.append(("L", x, y))
            cx, cy = x, y
            last_ctrl = None
        elif upper in "CS":
            if upper == "C":
                pts = [(vals[k] + (cx if rel else 0), vals[k + 1] + (cy if rel else 0)) for k in (0, 2, 4)]
                c1, c2, end = pts
            else:
                c1 = (2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1]) if last_cmd in ("C", "S") and last_ctrl else (cx, cy)
                c2, end = [(vals[k] + (cx if rel else 0), vals[k + 1] + (cy if rel else 0)) for k in (0, 2)]
            out.append(("C", *c1, *c2, *end))
            cx, cy = end
            last_ctrl = c2
        else:  # Q or T: quadratic, converted exactly to cubic
            if upper == "Q":
                q = (vals[0] + (cx if rel else 0), vals[1] + (cy if rel else 0))
                end = (vals[2] + (cx if rel else 0), vals[3] + (cy if rel else 0))
            else:
                q = (2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1]) if last_cmd in ("Q", "T") and last_ctrl else (cx, cy)
                end = (vals[0] + (cx if rel else 0), vals[1] + (cy if rel else 0))
            c1 = (cx + 2 / 3 * (q[0] - cx), cy + 2 / 3 * (q[1] - cy))
            c2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
            out.append(("C", *c1, *c2, *end))
            cx, cy = end
            last_ctrl = q
        last_cmd = upper
    return tuple(out)


def _cubic_extrema(p0: float, p1: float, p2: float, p3: float) -> list[float]:
    """Parameter values in (0, 1) where one coordinate of a cubic Bézier has a turning point."""
    a = -p0 + 3 * p1 - 3 * p2 + p3
    b = 2 * (p0 - 2 * p1 + p2)
    c = p1 - p0
    ts: list[float] = []
    if abs(a) < 1e-12:
        if abs(b) > 1e-12:
            ts.append(-c / b)
    else:
        disc = b * b - 4 * a * c
        if disc >= 0:
            r = math.sqrt(disc)
            ts.extend(((-b + r) / (2 * a), (-b - r) / (2 * a)))
    return [t for t in ts if 0 < t < 1]


def _cubic_at(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    u = 1 - t
    return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3


def bounding_box(segments: Iterable[Segment]) -> tuple[float, float, float, float] | None:
    """Exact ink extents (min x, min y, max x, max y) of a path, or None if it draws nothing."""
    xs: list[float] = []
    ys: list[float] = []
    cx = cy = 0.0
    for seg in segments:
        kind = seg[0]
        if kind in ("M", "L"):
            cx, cy = seg[1], seg[2]
            xs.append(cx)
            ys.append(cy)
        elif kind == "C":
            _, x1, y1, x2, y2, x, y = seg
            xs.append(x)
            ys.append(y)
            xs.extend(_cubic_at(cx, x1, x2, x, t) for t in _cubic_extrema(cx, x1, x2, x))
            ys.extend(_cubic_at(cy, y1, y2, y, t) for t in _cubic_extrema(cy, y1, y2, y))
            cx, cy = x, y
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def transform(segments: Iterable[Segment], scale: float, dx: float, dy: float, flip_y: bool = True) -> tuple[Segment, ...]:
    """Scale (and, by default, flip vertically, for font units which are y-up) then translate a path."""
    sy = -scale if flip_y else scale
    out: list[Segment] = []
    for seg in segments:
        if seg[0] == "Z":
            out.append(seg)
            continue
        coords = seg[1:]
        mapped = []
        for k in range(0, len(coords), 2):
            mapped.extend((coords[k] * scale + dx, coords[k + 1] * sy + dy))
        out.append((seg[0], *mapped))
    return tuple(out)


def to_path_data(segments: Iterable[Segment]) -> str:
    """Serialise segments as SVG path data, with deterministic number formatting."""
    parts = []
    for seg in segments:
        if seg[0] == "Z":
            parts.append("Z")
        else:
            parts.append(seg[0] + " " + " ".join(format_number(v) for v in seg[1:]))
    return " ".join(parts)


def arc_to_cubics(
    x1: float, y1: float, rx: float, ry: float, angle: float, large: bool, sweep: bool, x2: float, y2: float
) -> list[Segment]:
    """An SVG elliptical arc as cubic Bézier segments (SVG 1.1 implementation notes, F.6.5)."""
    if (x1, y1) == (x2, y2):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [("L", x2, y2)]
    phi = math.radians(angle)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cos_p * dx + sin_p * dy, -sin_p * dx + cos_p * dy
    scale = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if scale > 1:  # radii too small to reach: scale them up just enough
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def angle_between(ux: float, uy: float, vx: float, vy: float) -> float:
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta = angle_between(1, 0, ux, uy)
    delta = angle_between(ux, uy, vx, vy)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    pieces = max(1, math.ceil(abs(delta) / (math.pi / 2) - 1e-9))
    step = delta / pieces
    t = 4 / 3 * math.tan(step / 4)

    def on_ellipse(px: float, py: float) -> tuple[float, float]:
        return cx + rx * cos_p * px - ry * sin_p * py, cy + rx * sin_p * px + ry * cos_p * py

    out: list[Segment] = []
    for k in range(pieces):
        a1, a2 = theta + k * step, theta + (k + 1) * step
        c1 = on_ellipse(math.cos(a1) - t * math.sin(a1), math.sin(a1) + t * math.cos(a1))
        c2 = on_ellipse(math.cos(a2) + t * math.sin(a2), math.sin(a2) - t * math.cos(a2))
        end = (x2, y2) if k == pieces - 1 else on_ellipse(math.cos(a2), math.sin(a2))
        out.append(("C", *c1, *c2, *end))
    return out


# An affine transform (a, b, c, d, e, f), as in SVG: x' = a·x + c·y + e, y' = b·x + d·y + f.
Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(outer: Matrix, inner: Matrix) -> Matrix:
    """The transform that applies ``inner`` first, then ``outer``."""
    a1, b1, c1, d1, e1, f1 = outer
    a2, b2, c2, d2, e2, f2 = inner
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply_matrix(segments: Iterable[Segment], m: Matrix) -> tuple[Segment, ...]:
    """Transform a path. Exact for Béziers, since an affine map of the control points maps the curve."""
    a, b, c, d, e, f = m
    out: list[Segment] = []
    for seg in segments:
        if seg[0] == "Z":
            out.append(seg)
            continue
        coords = seg[1:]
        mapped: list[float] = []
        for k in range(0, len(coords), 2):
            x, y = coords[k], coords[k + 1]
            mapped.extend((a * x + c * y + e, b * x + d * y + f))
        out.append((seg[0], *mapped))
    return tuple(out)


Point = tuple[float, float]


def flatten(segments: Iterable[Segment], max_piece: float = 0.5) -> list[list[Point]]:
    """Polylines that follow a path: curves are cut into straight pieces no longer than about ``max_piece``."""
    lines: list[list[Point]] = []
    current: list[Point] = []
    start: Point | None = None
    cx = cy = 0.0
    for seg in segments:
        kind = seg[0]
        if kind == "M":
            if len(current) > 1:
                lines.append(current)
            cx, cy = seg[1], seg[2]
            current, start = [(cx, cy)], (cx, cy)
        elif kind == "L":
            cx, cy = seg[1], seg[2]
            current.append((cx, cy))
        elif kind == "C":
            _, x1, y1, x2, y2, x, y = seg
            control = math.dist((cx, cy), (x1, y1)) + math.dist((x1, y1), (x2, y2)) + math.dist((x2, y2), (x, y))
            pieces = max(1, min(64, math.ceil(control / max_piece)))
            for k in range(1, pieces + 1):
                t = k / pieces
                current.append((_cubic_at(cx, x1, x2, x, t), _cubic_at(cy, y1, y2, y, t)))
            cx, cy = x, y
        elif start is not None:  # Z
            current.append(start)
            cx, cy = start
            lines.append(current)
            current = [start]
    if len(current) > 1:
        lines.append(current)
    return lines
