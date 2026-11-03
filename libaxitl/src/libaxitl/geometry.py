"""Physical geometry shared by layout and render: millimetres, SVG orientation (y grows downward)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float  # top
    x1: float
    y1: float  # bottom

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def padded(self, pad: float) -> Box:
        return Box(self.x0 - pad, self.y0 - pad, self.x1 + pad, self.y1 + pad)

    def union(self, other: Box) -> Box:
        return Box(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))

    def overlap_area(self, other: Box) -> float:
        """Area shared with ``other``; zero when they only touch or are apart."""
        w = min(self.x1, other.x1) - max(self.x0, other.x0)
        h = min(self.y1, other.y1) - max(self.y0, other.y0)
        return w * h if w > 0 and h > 0 else 0.0

    def overlaps(self, other: Box) -> bool:
        return self.overlap_area(other) > 0


Point = tuple[float, float]


def _inside_interval(p: Point, q: Point, box: Box) -> tuple[float, float] | None:
    """The stretch t0..t1 (0 ≤ t ≤ 1) of the segment p→q that lies inside ``box`` (Liang–Barsky)."""
    t0, t1 = 0.0, 1.0
    dx, dy = q[0] - p[0], q[1] - p[1]
    for pk, qk in ((-dx, p[0] - box.x0), (dx, box.x1 - p[0]), (-dy, p[1] - box.y0), (dy, box.y1 - p[1])):
        if pk == 0:
            if qk < 0:
                return None
        elif pk < 0:
            t0 = max(t0, qk / pk)
        else:
            t1 = min(t1, qk / pk)
    return (t0, t1) if t0 < t1 else None


def _at(p: Point, q: Point, t: float) -> Point:
    if t == 1.0:  # exactly q, so an uncut polyline isn't split by rounding where one segment meets the next
        return q
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def _split(polyline: list[Point] | tuple[Point, ...], box: Box, keep_inside: bool) -> list[list[Point]]:
    pieces: list[list[Point]] = []
    current: list[Point] = []

    def end_piece() -> None:
        nonlocal current
        if len(current) > 1:
            pieces.append(current)
        current = []

    for p, q in zip(polyline, polyline[1:], strict=False):
        interval = _inside_interval(p, q, box)
        if interval is None:
            parts = [] if keep_inside else [(0.0, 1.0)]
        elif keep_inside:
            parts = [interval]
        else:
            parts = [(a, b) for a, b in ((0.0, interval[0]), (interval[1], 1.0)) if b > a]
        for a, b in parts:
            start, end = _at(p, q, a), _at(p, q, b)
            if not current or current[-1] != start:
                end_piece()
                current = [start]
            current.append(end)
        if not parts or parts[-1][1] < 1.0:
            end_piece()
    end_piece()
    return pieces


def keep_inside(polyline: list[Point] | tuple[Point, ...], box: Box) -> list[list[Point]]:
    """The parts of a polyline inside ``box``."""
    return _split(polyline, box, keep_inside=True)


def cut_out(polyline: list[Point] | tuple[Point, ...], box: Box) -> list[list[Point]]:
    """The parts of a polyline outside ``box``: how ink is kept from running through other ink."""
    return _split(polyline, box, keep_inside=False)


def segment_crosses(p: Point, q: Point, box: Box) -> bool:
    """True if any part of the segment p→q lies inside ``box``."""
    return _inside_interval(p, q, box) is not None


# -- regions, for a graph's shading (language spec §15.7) ---------------------------------------------------
#
# A region is described by a function telling, for a segment p→q, which stretches t0..t1 (0 ≤ t ≤ 1) of it lie
# inside. Pattern lines are cut to a region with clip().

Interval = tuple[float, float]


def _linear(f0: float, f1: float, lo: float, hi: float) -> Interval | None:
    """The t in [0, 1] where lo ≤ f0 + f1·t ≤ hi."""
    if abs(f1) < 1e-15:
        return (0.0, 1.0) if lo <= f0 <= hi else None
    a, b = sorted(((lo - f0) / f1, (hi - f0) / f1))
    a, b = max(a, 0.0), min(b, 1.0)
    return (a, b) if a < b else None


def _within_circle(p: Point, d: Point, c: Point, r: float) -> Interval | None:
    ox, oy = p[0] - c[0], p[1] - c[1]
    qa = d[0] * d[0] + d[1] * d[1]
    qb = 2 * (d[0] * ox + d[1] * oy)
    qc = ox * ox + oy * oy - r * r
    if qa == 0:
        return (0.0, 1.0) if qc <= 0 else None
    disc = qb * qb - 4 * qa * qc
    if disc <= 0:
        return None
    root = disc**0.5
    a, b = max((-qb - root) / (2 * qa), 0.0), min((-qb + root) / (2 * qa), 1.0)
    return (a, b) if a < b else None


def near_segment(p: Point, q: Point, a: Point, b: Point, r: float) -> list[Interval]:
    """Where p→q comes within r of the segment a→b (not merged)."""
    d = (q[0] - p[0], q[1] - p[1])
    out = []
    length = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    if length > 0:
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        across = _linear((p[0] - a[0]) * uy - (p[1] - a[1]) * ux, d[0] * uy - d[1] * ux, -r, r)
        along = _linear((p[0] - a[0]) * ux + (p[1] - a[1]) * uy, d[0] * ux + d[1] * uy, 0.0, length)
        if across and along and max(across[0], along[0]) < min(across[1], along[1]):
            out.append((max(across[0], along[0]), min(across[1], along[1])))
    for c in (a, b):
        iv = _within_circle(p, d, c, r)
        if iv:
            out.append(iv)
    return out


def inside_convex(p: Point, q: Point, polygon: list[Point]) -> Interval | None:
    """Where p→q is inside a convex polygon (Cyrus–Beck); None for a polygon with no area."""
    area = sum(polygon[i - 1][0] * polygon[i][1] - polygon[i][0] * polygon[i - 1][1] for i in range(len(polygon)))
    if abs(area) < 1e-9:
        return None
    sign = 1.0 if area > 0 else -1.0
    d = (q[0] - p[0], q[1] - p[1])
    lo, hi = 0.0, 1.0
    for i in range(len(polygon)):
        e0, e1 = polygon[i], polygon[(i + 1) % len(polygon)]
        ex, ey = e1[0] - e0[0], e1[1] - e0[1]
        iv = _linear(sign * (ex * (p[1] - e0[1]) - ey * (p[0] - e0[0])), sign * (ex * d[1] - ey * d[0]), 0.0, float("inf"))
        if iv is None:
            return None
        lo, hi = max(lo, iv[0]), min(hi, iv[1])
        if lo >= hi:
            return None
    return (lo, hi)


def inside_even_odd(p: Point, q: Point, polygon: list[Point]) -> list[Interval]:
    """Where p→q is inside a polygon by the even–odd rule (the polygon may cross itself)."""
    d = (q[0] - p[0], q[1] - p[1])
    l2 = d[0] * d[0] + d[1] * d[1]
    if l2 == 0:
        return []
    side = [(v[0] - p[0]) * -d[1] + (v[1] - p[1]) * d[0] for v in polygon]
    ts = []
    for i in range(len(polygon)):
        j = (i + 1) % len(polygon)
        if (side[i] >= 0) != (side[j] >= 0):
            u = side[i] / (side[i] - side[j])
            x = polygon[i][0] + u * (polygon[j][0] - polygon[i][0]), polygon[i][1] + u * (polygon[j][1] - polygon[i][1])
            ts.append(((x[0] - p[0]) * d[0] + (x[1] - p[1]) * d[1]) / l2)
    ts.sort()
    out = []
    for k in range(0, len(ts) - 1, 2):
        a, b = max(ts[k], 0.0), min(ts[k + 1], 1.0)
        if a < b:
            out.append((a, b))
    return out


def merge(intervals: list[Interval]) -> list[Interval]:
    """The union of some intervals, sorted and without overlaps."""
    out: list[list[float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def intersect(xs: list[Interval], ys: list[Interval]) -> list[Interval]:
    """The parts of xs also in ys (both merged)."""
    out = []
    for a, b in xs:
        for c, d in ys:
            lo, hi = max(a, c), min(b, d)
            if lo < hi:
                out.append((lo, hi))
    return merge(out)


def subtract(xs: list[Interval], ys: list[Interval]) -> list[Interval]:
    """The parts of xs not in ys."""
    out = []
    for a, b in xs:
        pieces = [(a, b)]
        for c, d in ys:
            pieces = [part for lo, hi in pieces for part in ((lo, min(hi, c)), (max(lo, d), hi)) if part[0] < part[1]]
        out += pieces
    return out


def clip(polyline: list[Point] | tuple[Point, ...], inside, shortest: float = 0.0) -> list[list[Point]]:
    """The parts of a polyline inside a region, given as ``inside(p, q) -> merged intervals``. Pieces shorter
    than ``shortest`` are left out."""
    pieces: list[list[Point]] = []
    current: list[Point] = []

    def end() -> None:
        nonlocal current
        if len(current) > 1:
            pieces.append(current)
        current = []

    for p, q in zip(polyline, polyline[1:], strict=False):
        intervals = inside(p, q)
        for a, b in intervals:
            start, stop = _at(p, q, a), _at(p, q, b)
            if current and current[-1] == start:
                current.append(stop)
            else:
                end()
                current = [start, stop]
        if not intervals or intervals[-1][1] < 1.0:
            end()
    end()
    return [piece for piece in pieces if polyline_length(piece) >= shortest]


def polyline_length(points: list[Point] | tuple[Point, ...]) -> float:
    return sum(((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5 for p, q in zip(points, points[1:], strict=False))


def segment_box(p: Point, q: Point, pad: float = 0.0) -> Box:
    return Box(min(p[0], q[0]) - pad, min(p[1], q[1]) - pad, max(p[0], q[0]) + pad, max(p[1], q[1]) + pad)


def touches(a: Box, b: Box) -> bool:
    """True if two boxes overlap or meet."""
    return a.x0 <= b.x1 and b.x0 <= a.x1 and a.y0 <= b.y1 and b.y0 <= a.y1


def simplify(points: list[Point], tolerance: float) -> list[Point]:
    """Fewer points, none of the left-out ones further than ``tolerance`` from what's drawn (Ramer–Douglas–
    Peucker, measured to segments rather than lines, so a spike is never cut off)."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        best, index = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
            distance = ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5
            if distance > best:
                best, index = distance, i
        if best > tolerance:
            keep[index] = True
            stack += [(a, index), (index, b)]
    return [p for p, k in zip(points, keep, strict=True) if k]
