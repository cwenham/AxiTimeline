"""Minimal SVG path handling for stroke-font glyphs.

Paths are normalised to absolute ``M``, ``L``, ``C`` and ``Z`` commands, which is all the bundled fonts use
and all a pen plotter needs. Relative commands, ``H``/``V``, and the smooth and quadratic curve forms are
converted on the way in. Elliptical arcs (``A``) are rejected rather than approximated.
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
        if upper == "A":
            raise PathError("elliptical arc commands (A) are not supported in glyphs")
        n = _ARG_COUNTS[upper]
        args = tokens[i : i + n]
        if len(args) < n or any(a.isalpha() for a in args):
            raise PathError(f"command {cmd} is missing arguments")
        vals = [float(a) for a in args]
        i += n
        rel = cmd.islower()
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
