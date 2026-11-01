"""``draw(layout) -> Drawing``: every stroke the plotter will make, with its pen, before any windowing.

Everything is a polyline in the layout's own millimetre coordinates (x along the roll from the start, y across
it from the finished top edge), so the same stroke has the same coordinates however the job is later cut into
windows. Curves are flattened here, once, so nothing downstream has to understand them.

Strokes come out in the draw order of language spec §11: baseline and ticks, then background graphs (§15), then
bars (outlines, labels and fills), then event poles and flags, then illustrations, then the title and credits
(§16) and notes (§17); crop marks (interpreter spec) are last.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .colours import WHITE
from .diagnostics import Diagnostic, Diagnostics, SourceLocation
from .geometry import Box, Point, cut_out, keep_inside
from .graphs import PlacedGraph, shading, shading_box
from .hatch import Outline
from .illustrate import illustration_shapes
from .layout import LabelPlacement, PlacedBar, PlacedBlock, PlacedText, ResolvedLayout
from .model import Fill, Illustration, OpenEndStyle
from .svgpath import flatten


class Stage(Enum):
    AXIS = "axis"
    BACKGROUND = "background"
    BARS = "bars"
    EVENTS = "events"
    ILLUSTRATIONS = "illustrations"
    TITLES = "titles"  # the title and credits (§16), and notes (§17)
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
    shade_shortest: float = 0.5  # pieces of a graph's shading shorter than this are left out (§15.7)
    shadow_gap: float = 0.75  # a graph's shadow keeps this far from its own line (§15.7)


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
        for graph in L.graphs:
            self.graph(graph)
        for bar in L.bars:
            self.bar(bar)
        for ev in L.events:
            pen = ev.entity.pen
            self.add(pen, Stage.EVENTS, ([(ev.x, a), (ev.x, b)] for a, b in ev.pole_segments))
            self.add(pen, Stage.EVENTS, self.text(ev.flag))
            if ev.time_label is not None:
                self.add(pen, Stage.EVENTS, self.text(ev.time_label))
        for ill in L.illustrations:
            self.illustration(ill.illustration, ill.box, ill.owner.pen, Stage.ILLUSTRATIONS, ill.owner.location)
        for block in (L.title, L.credits, *L.notes):
            if block is not None:
                self.block(block)
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

    # -- the title and credits (§16), and notes (§17) ------------------------------------------------------

    def block(self, block: PlacedBlock) -> None:
        for i, text in enumerate(block.texts):
            lines = self.text(text)
            self.add(block.pen, Stage.TITLES, lines)
            fill = block.fills[i] if i < len(block.fills) else Fill.NONE
            if fill is not Fill.NONE:  # an outline font's letters, hatched inside (§16.1)
                self.add(block.pen, Stage.TITLES, self.inside(lines, False, fill))
        if block.illustration is not None and block.illustration_box is not None:
            self.illustration(block.illustration, block.illustration_box, block.pen, Stage.TITLES, block.location)

    # -- illustrations (§3.5) ------------------------------------------------------------------------------

    def illustration(self, ill: Illustration, box: Box, owner_pen: str, stage: Stage, location: SourceLocation) -> None:
        """An illustration's shapes: each outline in its pen, and with fill= each filled shape hatched inside.

        Without pens= everything is in its owner's pen, as an illustration always was. With pens=, an outline is in
        its stroke's pen, or its fill's if it has no stroke; a hatch is in its fill's pen; and nothing white (the
        paper) is drawn. Paint that isn't a plain colour, and a colour pens= doesn't name, are in the owner's pen."""
        shapes, notes = illustration_shapes(ill.svg, ill.name, box, self.style.curve_piece)
        mapping = dict(ill.pens) if ill.pens is not None else None

        def pen_for(paint: str | None) -> str | None:
            if mapping is None:
                return owner_pen
            if paint is None or paint == WHITE:
                return None
            return mapping.get(paint, owner_pen)

        outlines_only = False
        for shape in shapes:
            if mapping is None:
                edge = owner_pen
            else:
                edge = pen_for(shape.stroke) if shape.stroke is not None else pen_for(shape.fill)
            if edge is not None:
                self.add(edge, stage, shape.lines)
            if shape.fill is None:
                continue
            if ill.fill is Fill.NONE:
                outlines_only = True
                continue
            hatch_pen = pen_for(shape.fill)
            if hatch_pen is None or shape.fill == WHITE:
                continue  # white is the paper: never hatched
            self.add(hatch_pen, stage, self.inside(shape.lines, shape.evenodd, ill.fill))
        if outlines_only:
            notes.append("filled shapes are drawn as their outlines only (fill= hatches them)")
        for note in notes:
            self.sink.warning("illustration-content", f"illustration '{ill.name}': {note}", location)

    def inside(self, lines: list[list[Point]], evenodd: bool, fill: Fill) -> list[list[Point]]:
        """A fill pattern cut to the inside of closed outlines (a filled shape, or an outline font's letters), with
        any piece too short to draw without leaving a stub left out."""
        points = [p for line in lines for p in line]
        if len(points) < 3:
            return []
        region = Box(min(x for x, _ in points), min(y for _, y in points),
                     max(x for x, _ in points), max(y for _, y in points))
        if region.width <= 0 or region.height <= 0:
            return []
        shortest = 0.0 if fill is Fill.DOTS else self.style.shade_shortest
        return [h for h in Outline(lines, evenodd).clip(self.fill(fill, region)) if _length(h) >= shortest]

    # -- background graphs (§15) -------------------------------------------------------------------------

    def graph(self, pg: PlacedGraph) -> None:
        g, st = pg.graph, self.style
        self.add(g.pen, Stage.BACKGROUND, pg.line)
        if g.fill is not Fill.NONE:
            box = shading_box(pg)
            if box is not None:
                shortest = 0.0 if g.fill is Fill.DOTS else st.shade_shortest
                self.add(g.fill_pen, Stage.BACKGROUND, shading(pg, self.fill(g.fill, box), shortest, st.shadow_gap))
        self.add(g.pen, Stage.BACKGROUND, pg.rules)
        for text in pg.texts:
            self.add(g.pen, Stage.BACKGROUND, self.text(text))

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
                    self.add(e.fill_pen, Stage.BARS, cut_out(line, fill_clear))  # its own pen if it has one (§3.7)

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


def _length(points) -> float:
    return sum(math.dist(p, q) for p, q in zip(points, points[1:], strict=False))
