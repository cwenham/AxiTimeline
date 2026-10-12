"""``draw(layout) -> Drawing``: every stroke the plotter will make, with its pen, before any windowing.

Everything is a polyline in the layout's own millimetre coordinates (x along the roll from the start, y across
it from the finished top edge), so the same stroke has the same coordinates however the job is later cut into
windows. Curves are flattened here, once, so nothing downstream has to understand them.

Strokes come out in the draw order of language spec §11: baseline and ticks, then bars (outlines, labels and
fills), then event poles and flags, then illustrations; crop marks (interpreter spec) are last.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .diagnostics import Diagnostic, Diagnostics
from .geometry import Box, Point, cut_out, keep_inside
from .illustrate import illustration_strokes
from .layout import LabelPlacement, PlacedBar, PlacedText, ResolvedLayout
from .model import Fill, OpenEndStyle
from .svgpath import flatten


class Stage(Enum):
    AXIS = "axis"
    BARS = "bars"
    EVENTS = "events"
    ILLUSTRATIONS = "illustrations"
    CROP_MARKS = "crop-marks"


@dataclass(frozen=True)
class DrawStyle:
    """How things are drawn where the specs leave it open. Millimetres. Provisional values."""

    curve_piece: float = 0.25  # curves are drawn as straight pieces about this long
    cap_tooth: float = 1.5  # height of one sawtooth tooth or sine wave (rounded to fit the bar)
    hatch_spacing: float = 2.0  # between lines of diagonal, crosshatch and wave fills, and between dots
    solid_spacing: float = 0.4  # "solid" is dense hatching (§3.7)
    wave_amplitude: float = 0.5
    wave_length: float = 3.0
    dot_size: float = 0.25  # a dot is a short stroke this long
    label_clearance: float = 0.75  # fills and outlines keep this far from a bar's label (§3.7)
    crop_interval: float = 500.0  # crop marks every 50cm (interpreter spec)
    crop_arm: float = 2.5  # each arm of a crop mark's cross
    crop_pen: str = "2H-pencil"  # crop marks are pencil, never one of the job's own pens


DEFAULT_DRAW_STYLE = DrawStyle()


@dataclass(frozen=True)
class Stroke:
    pen: str
    stage: Stage
    points: tuple[Point, ...]

    @property
    def length(self) -> float:
        return sum(math.dist(p, q) for p, q in zip(self.points, self.points[1:], strict=False))


@dataclass(frozen=True)
class Drawing:
    width_mm: float
    length_mm: float
    page_margin_mm: float  # crop marks reach this far beyond the finished width, so pages include it
    pens: tuple[str, ...]  # every pen, in pass order: the axis pen first (§10.4)
    strokes: tuple[Stroke, ...]  # in draw order
    diagnostics: tuple[Diagnostic, ...]

    def length_by_pen(self) -> dict[str, float]:
        """Total draw length per pen, in mm, in pass order."""
        totals = {pen: 0.0 for pen in self.pens}
        for stroke in self.strokes:
            totals[stroke.pen] += stroke.length
        return totals


def draw(layout: ResolvedLayout, style: DrawStyle = DEFAULT_DRAW_STYLE) -> Drawing:
    return _Drawer(layout, style).run()


class _Drawer:
    def __init__(self, layout: ResolvedLayout, style: DrawStyle):
        self.layout = layout
        self.style = style
        self.strokes: list[Stroke] = []
        self.sink = Diagnostics()

    def add(self, pen: str, stage: Stage, lines) -> None:
        for points in lines:
            if len(points) > 1:
                self.strokes.append(Stroke(pen, stage, tuple(points)))

    def text(self, placed: PlacedText) -> list[list[Point]]:
        return flatten(placed.shaped.segments(placed.x, placed.y), self.style.curve_piece)

    def run(self) -> Drawing:
        L = self.layout
        self.axis()
        for bar in L.bars:
            self.bar(bar)
        for ev in L.events:
            pen = ev.entity.pen
            self.add(pen, Stage.EVENTS, ([(ev.x, a), (ev.x, b)] for a, b in ev.pole_segments))
            self.add(pen, Stage.EVENTS, self.text(ev.flag))
            if ev.time_label is not None:
                self.add(pen, Stage.EVENTS, self.text(ev.time_label))
        for ill in L.illustrations:
            lines, notes = illustration_strokes(
                ill.illustration.svg, ill.illustration.name, ill.box, self.style.curve_piece
            )
            self.add(ill.owner.pen, Stage.ILLUSTRATIONS, lines)
            for note in notes:
                self.sink.warning(
                    "illustration-content", f"illustration '{ill.illustration.name}': {note}", ill.owner.location
                )
        self.crop_marks()
        pens = L.pens + ((self.style.crop_pen,) if self.style.crop_pen not in L.pens else ())
        return Drawing(L.width_mm, L.length_mm, self.style.crop_arm, pens, tuple(self.strokes), tuple(self.sink.items))

    # -- baseline and ticks ----------------------------------------------------------------------------------

    def axis(self) -> None:
        L, pen = self.layout, self.layout.axis_pen
        y = L.baseline_y
        self.add(pen, Stage.AXIS, [[(0.0, y), (L.length_mm, y)]])
        for tick in L.ticks:
            self.add(pen, Stage.AXIS, [[(tick.x, y), (tick.x, y + tick.length)]])
            if tick.label is not None:
                self.add(pen, Stage.AXIS, self.text(tick.label))

    # -- bars --------------------------------------------------------------------------------------------------

    def bar(self, bar: PlacedBar) -> None:
        st, e = self.style, bar.entity
        x0, x1, y0, y1 = bar.x0, bar.x1, bar.y0, bar.y1
        caps = bar.cap_start + bar.cap_end
        depth = min(self.layout.cap_depth_mm, 0.9 * (x1 - x0) / caps) if caps else 0.0
        style = self.layout.document.timeline.open_end_style
        left = self.cap(x0, y0, y1, +1, depth, style) if bar.cap_start else [(x0, y0), (x0, y1)]
        right = self.cap(x1, y0, y1, -1, depth, style) if bar.cap_end else [(x1, y0), (x1, y1)]
        outline = left + list(reversed(right)) + [left[0]]  # groups too: a group looks like a span (§9)
        on_bar = bar.label_placement in (LabelPlacement.INSIDE, LabelPlacement.OVERRUN)
        keep_clear = bar.label.box.padded(st.label_clearance) if on_bar else Box(0, 0, 0, 0)
        self.add(e.pen, Stage.BARS, cut_out(outline, keep_clear))
        self.add(e.pen, Stage.BARS, self.text(bar.label))
        self.add(e.pen, Stage.BARS, ([p, q] for p, q in bar.leader_segments))
        if e.fill is not Fill.NONE:
            region = Box(x0 + (depth if bar.cap_start else 0.0), y0, x1 - (depth if bar.cap_end else 0.0), y1)
            if region.width > 0 and region.height > 0:
                # The fill stops in a clean vertical edge either side of the label, across the whole bar, and
                # leaves out any strip too narrow to hatch without leaving stubs (§3.7).
                fill_clear = Box(0, 0, 0, 0)
                if on_bar:
                    fx0, fx1 = keep_clear.x0, keep_clear.x1
                    if fx0 - region.x0 < st.hatch_spacing:
                        fx0 = region.x0 - 1
                    if region.x1 - fx1 < st.hatch_spacing:
                        fx1 = region.x1 + 1
                    fill_clear = Box(fx0, y0 - 1, fx1, y1 + 1)
                for line in self.fill(e.fill, region):
                    self.add(e.pen, Stage.BARS, cut_out(line, fill_clear))

    def cap(self, x: float, y0: float, y1: float, inward: int, depth: float, style: OpenEndStyle) -> list[Point]:
        """The torn edge drawn where a bar is open or clipped (§3.6), from its top to its bottom."""
        height = y1 - y0
        waves = max(1, round(height / self.style.cap_tooth))
        if style is OpenEndStyle.SAWTOOTH:
            return [(x + inward * depth if k % 2 else x, y0 + height * k / (2 * waves)) for k in range(2 * waves + 1)]
        samples = 12 * waves
        return [
            (x + inward * depth * (1 - math.cos(2 * math.pi * waves * k / samples)) / 2, y0 + height * k / samples)
            for k in range(samples + 1)
        ]

    def fill(self, fill: Fill, r: Box) -> list[list[Point]]:
        """Fill patterns, anchored to the page rather than the bar, so a windowed reprint draws the same lines."""
        st = self.style
        lines: list[list[Point]] = []
        if fill in (Fill.DIAGONAL, Fill.CROSSHATCH):
            step = st.hatch_spacing * math.sqrt(2)
            for k in range(math.ceil((r.x0 + r.y0) / step), math.floor((r.x1 + r.y1) / step) + 1):
                c = k * step  # the line x + y = c, drawn "/" on the page
                lines += keep_inside([(c - r.y1, r.y1), (c - r.y0, r.y0)], r)
            if fill is Fill.CROSSHATCH:
                for k in range(math.ceil((r.x0 - r.y1) / step), math.floor((r.x1 - r.y0) / step) + 1):
                    c = k * step  # the line x - y = c, drawn "\\"
                    lines += keep_inside([(c + r.y0, r.y0), (c + r.y1, r.y1)], r)
        elif fill is Fill.SOLID:
            s = st.solid_spacing
            for k in range(math.ceil(r.y0 / s), math.floor(r.y1 / s) + 1):
                lines.append([(r.x0, k * s), (r.x1, k * s)])
        elif fill is Fill.WAVE:
            s, a, wl = st.hatch_spacing, st.wave_amplitude, st.wave_length
            xs = [r.x0] + [k * wl / 16 for k in range(math.floor(r.x0 * 16 / wl) + 1, math.ceil(r.x1 * 16 / wl))] + [r.x1]
            for k in range(math.ceil((r.y0 + a) / s), math.floor((r.y1 - a) / s) + 1):
                lines.append([(x, k * s + a * math.sin(2 * math.pi * x / wl)) for x in xs])
        elif fill is Fill.DOTS:
            s, d = st.hatch_spacing, st.dot_size / 2
            for j in range(math.ceil(r.y0 / s), math.floor(r.y1 / s) + 1):
                for i in range(math.ceil((r.x0 + d) / s), math.floor((r.x1 - d) / s) + 1):
                    lines.append([(i * s - d, j * s), (i * s + d, j * s)])
        # Alternate directions so the pen sweeps back and forth instead of returning to the same edge.
        return [line if n % 2 == 0 else line[::-1] for n, line in enumerate(lines)]

    # -- crop marks ----------------------------------------------------------------------------------------

    def crop_marks(self) -> None:
        """Pencil crosses centred on both finished edges every 50cm: a trim guide and a ruler (interpreter spec)."""
        st, L = self.style, self.layout
        arm = st.crop_arm
        for k in range(math.floor(L.length_mm / st.crop_interval + 1e-9) + 1):
            x = k * st.crop_interval
            across = [(max(x - arm, 0.0), 0.0), (min(x + arm, L.length_mm), 0.0)]  # never past the job's ends
            for y in (0.0, L.width_mm):
                along = [(across[0][0], y), (across[1][0], y)]
                self.add(st.crop_pen, Stage.CROP_MARKS, [along, [(x, y - arm), (x, y + arm)]])
