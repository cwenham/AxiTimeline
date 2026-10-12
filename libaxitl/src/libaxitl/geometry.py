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
