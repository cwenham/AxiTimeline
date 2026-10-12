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
