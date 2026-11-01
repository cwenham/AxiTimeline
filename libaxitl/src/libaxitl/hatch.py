"""Hatching inside an outline: the fill patterns of §3.7, cut to the inside of an illustration's filled shape.

A shape's outline is a set of closed polylines (each subpath is closed for filling, as SVG closes it). A pattern
line is cut wherever it crosses the outline, and each piece is kept if its midpoint is inside the shape by the
SVG's fill rule: nonzero, so a letter's counter (wound the other way) stays empty, or evenodd. Testing each
piece's midpoint, rather than counting crossings along the line, means a line that grazes a corner can't flip
inside and outside.

Edges are indexed in horizontal bands, so a piece only meets the edges near it.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .geometry import Point

_BAND = 0.5  # mm: the height of the bands edges are indexed in


class Outline:
    """A filled shape's outline, ready for testing points and cutting lines against."""

    def __init__(self, lines, evenodd: bool):
        self.evenodd = evenodd
        self.edges: list[tuple[float, float, float, float]] = []
        for line in lines:
            points = list(line)
            if len(points) < 2:
                continue
            if points[0] != points[-1]:
                points.append(points[0])  # filling closes every subpath
            for (ax, ay), (bx, by) in zip(points, points[1:], strict=False):
                if (ax, ay) != (bx, by):
                    self.edges.append((ax, ay, bx, by))
        self.bands: dict[int, list[int]] = defaultdict(list)
        for i, (ax, ay, bx, by) in enumerate(self.edges):
            for band in range(math.floor(min(ay, by) / _BAND), math.floor(max(ay, by) / _BAND) + 1):
                self.bands[band].append(i)

    def inside(self, x: float, y: float) -> bool:
        """Whether (x, y) is inside, by the winding number of the edges a ray to the right crosses."""
        winding = 0
        for i in self.bands.get(math.floor(y / _BAND), ()):
            ax, ay, bx, by = self.edges[i]
            if ay <= y < by:  # an upward edge (in the page's y-down terms, a downward one: only the sign matters)
                if (bx - ax) * (y - ay) - (x - ax) * (by - ay) > 0:
                    winding += 1
            elif by <= y < ay:
                if (bx - ax) * (y - ay) - (x - ax) * (by - ay) < 0:
                    winding -= 1
        return winding % 2 == 1 if self.evenodd else winding != 0

    def crossings(self, p: Point, q: Point) -> list[float]:
        """Where the segment p→q meets an edge, as fractions of the way along it (0 < t < 1)."""
        (px, py), (qx, qy) = p, q
        dx, dy = qx - px, qy - py
        lo, hi = math.floor(min(py, qy) / _BAND), math.floor(max(py, qy) / _BAND)
        seen: set[int] = set()
        ts = []
        x_lo, x_hi = min(px, qx), max(px, qx)
        for band in range(lo, hi + 1):
            for i in self.bands.get(band, ()):
                if i in seen:
                    continue
                seen.add(i)
                ax, ay, bx, by = self.edges[i]
                if max(ax, bx) < x_lo or min(ax, bx) > x_hi:
                    continue
                ex, ey = bx - ax, by - ay
                denominator = dx * ey - dy * ex
                if denominator == 0:
                    continue  # parallel: the midpoint test settles which side the line is on
                wx, wy = ax - px, ay - py
                t = (wx * ey - wy * ex) / denominator
                u = (wx * dy - wy * dx) / denominator
                if 0 < t < 1 and 0 <= u <= 1:
                    ts.append(t)
        return sorted(ts)

    def clip(self, lines) -> list[list[Point]]:
        """The parts of ``lines`` (polylines) that are inside the shape."""
        out: list[list[Point]] = []
        for line in lines:
            current: list[Point] = []
            for p, q in zip(line, line[1:], strict=False):
                ts = [0.0, *self.crossings(p, q), 1.0]
                for t0, t1 in zip(ts, ts[1:], strict=False):
                    if t1 - t0 < 1e-9:
                        continue
                    mid = (p[0] + (q[0] - p[0]) * (t0 + t1) / 2, p[1] + (q[1] - p[1]) * (t0 + t1) / 2)
                    start = (p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0)
                    end = (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)
                    if self.inside(*mid):
                        if current and math.dist(current[-1], start) < 1e-9:
                            current.append(end)
                        else:
                            if len(current) > 1:
                                out.append(current)
                            current = [start, end]
                    elif len(current) > 1:
                        out.append(current)
                        current = []
                    else:
                        current = []
            if len(current) > 1:
                out.append(current)
        return out
