"""Background graphs (language spec §15): laid out after everything else, and moving nothing.

A graph is placed in a fourth phase, once bars, events, illustrations and ticks are all where they will be. Its
line is fitted to the paper (or to the height asked for), its title and value scales go only where they are clear
of all foreground ink, and its line, shading and scales are broken wherever they would run through text or an
illustration. Nothing in the first three phases looks at graphs, so adding one never moves the foreground.

Like the rest of layout, every search here steps along the roll in fixed increments from fixed starting points,
so the same document always gives the same result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .diagnostics import Diagnostics
from .geometry import (
    Box,
    Point,
    clip,
    cut_out,
    inside_convex,
    inside_even_odd,
    intersect,
    keep_inside,
    merge,
    near_segment,
    polyline_length,
    segment_box,
    simplify,
    subtract,
    touches,
)
from .model import Graph, LineMode, ValueScaleMode, YScale

Polyline = tuple[Point, ...]


@dataclass(frozen=True)
class PlacedGraph:
    graph: Graph
    origin: float  # the value drawn on the baseline
    rate_mm: float  # mm per unit (linear) or per power of ten (log)
    above_mm: float  # how far the line reaches above and below the baseline
    below_mm: float
    path: tuple[Polyline, ...]  # the line inside the timeline, before breaking, less any dots: what shading follows
    line: tuple[Polyline, ...]  # the line as drawn, dots too: kept inside the paper and broken around text (§15.8)
    rules: tuple[Polyline, ...]  # the value scales' rules and marks, broken around text
    texts: tuple  # PlacedText: the title and value labels
    clear: tuple[Box, ...]  # text and illustrations, padded: shading is broken around these too
    baseline_y: float
    paper: Box  # the finished paper less the edge margin: nothing of the graph goes outside it

    @property
    def rate_unit(self) -> str:
        return "power of ten" if self.graph.y_scale is YScale.LOG else "unit"


@dataclass
class _Draft:
    graph: Graph
    origin: float
    rate: float
    above: float
    below: float
    lowest: float  # the smallest and largest values the line draws
    highest: float
    path: list[list[Point]]
    drawn: list[list[Point]]
    y_of: Callable[[float], float]
    rules: list[list[Point]] = field(default_factory=list)
    texts: list = field(default_factory=list)


def steffen(points: list[Point], piece: float) -> list[Point]:
    """A smooth curve through every point that never overshoots them: between two points it stays between their
    values (monotone cubic interpolation, Steffen 1990). Drawn as straight pieces about ``piece`` long."""
    n = len(points)
    if n < 3:
        return list(points)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] if h[i] > 0 else 0.0 for i in range(n - 1)]
    slope = [0.0] * n

    def sign(v: float) -> int:
        return (v > 0) - (v < 0)

    for i in range(1, n - 1):
        if h[i - 1] <= 0 or h[i] <= 0:
            continue
        p = (d[i - 1] * h[i] + d[i] * h[i - 1]) / (h[i - 1] + h[i])
        slope[i] = (sign(d[i - 1]) + sign(d[i])) * min(abs(d[i - 1]), abs(d[i]), 0.5 * abs(p))

    def end(d0: float, d1: float, h0: float, h1: float) -> float:
        p = d0 * (1 + h0 / (h0 + h1)) - d1 * h0 / (h0 + h1)
        if p * d0 <= 0:
            return 0.0
        return 2 * d0 if abs(p) > 2 * abs(d0) else p

    slope[0] = end(d[0], d[1], h[0], h[1])
    slope[-1] = end(d[-1], d[-2], h[-1], h[-2])
    out = [points[0]]
    for i in range(n - 1):
        if h[i] <= 0:
            out.append(points[i + 1])
            continue
        pieces = min(4000, max(1, math.ceil(math.hypot(h[i], ys[i + 1] - ys[i]) / piece)))
        a = (slope[i] + slope[i + 1] - 2 * d[i]) / h[i] ** 2
        b = (3 * d[i] - 2 * slope[i] - slope[i + 1]) / h[i]
        for k in range(1, pieces + 1):
            t = h[i] * k / pieces
            out.append((xs[i] + t, ys[i] + t * (slope[i] + t * (b + t * a))))
        out[-1] = points[i + 1]
    return out


def number_text(value: float) -> str:
    """A value label: thousands separated by commas, no needless decimals, no negative zero."""
    value = round(value, 9)
    if value == 0:
        return "0"
    if value == round(value):
        return f"{int(round(value)):,}"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def auto_marks(lowest: float, highest: float, log: bool) -> list[float]:
    """3 to 5 round values between lowest and highest (§15.9)."""
    if highest <= lowest:
        return []
    if log:
        marks: list[float] = []
        for ladder in ((1,), (1, 3), (1, 2, 5)):
            marks = [
                k * 10.0**e
                for e in range(math.floor(math.log10(lowest)) - 1, math.ceil(math.log10(highest)) + 1)
                for k in ladder
                if lowest <= k * 10.0**e <= highest
            ]
            if len(marks) >= 3:
                break
        while len(marks) > 5:
            marks = marks[::2]
        return marks
    for e in range(math.floor(math.log10(highest - lowest)) - 2, 400):
        for k in (1, 2, 5):
            step = k * 10.0**e
            marks = [n * step for n in range(math.ceil(lowest / step - 1e-9), math.floor(highest / step + 1e-9) + 1)]
            if len(marks) <= 5:
                return marks
    return []


class GraphLayout:
    """Places a document's graphs around a foreground that has already been laid out."""

    def __init__(self, *, baseline_y: float, width: float, length: float, x: Callable[[int], float],
                 window: tuple[int, int], text, style, sink: Diagnostics, ink: list[Box], text_boxes: list[Box],
                 tick_bottom: float):
        self.by, self.width, self.length = baseline_y, width, length
        self.x = x
        self.t0, self.t1 = window
        self.text = text  # (font key, size, label) -> layout's measured text
        self.style = style
        self.sink = sink
        self.taken = list(ink)  # where a graph's own text must not go
        self.text_boxes = list(text_boxes)  # what a graph is broken around
        self.tick_bottom = tick_bottom
        self.columns: list[Box] = []  # value scales already placed
        self.paper = Box(-1e12, style.graph_edge_margin, 1e12, width - style.graph_edge_margin)

    def place(self, graphs) -> tuple[PlacedGraph, ...]:
        drafts = []
        for g in graphs:
            draft = self.draft(g)
            if draft is None:
                continue
            self.value_scales(draft)
            self.title(draft)
            drafts.append(draft)
        gap = self.style.pole_gap
        clear = tuple(b.padded(gap) for b in self.text_boxes + [t.box for d in drafts for t in d.texts])
        return tuple(self.finish(d, clear) for d in drafts)

    # -- the line -----------------------------------------------------------------------------------------

    def draft(self, g: Graph) -> _Draft | None:
        st = self.style
        log = g.y_scale is YScale.LOG
        if g.origin is None:
            first = next((p for p in g.points if p.value is not None and self.t0 <= p.seconds < self.t1), None)
            if first is None:
                self.sink.warning(
                    "graph-outside-window",
                    f'graph "{g.title}" has origin=first, but none of its points lies inside the timeline, so it '
                    "is left out",
                    g.location,
                )
                return None
            origin = first.value
        else:
            origin = g.origin

        def mapped(value: float) -> float:
            return math.log10(value / origin) if log else value - origin

        # Runs of points between gaps, as (x, mapped value), each with the time a gap ends its hold (step mode).
        runs: list[tuple[list[Point], float | None]] = []
        current: list[Point] = []
        for p in g.points:
            x = self.x(p.seconds)
            if p.value is None:
                if current:
                    runs.append((current, x))
                current = []
            else:
                current.append((x, mapped(p.value)))
        if current:
            runs.append((current, None))

        window = Box(0.0, -1e12, self.length, 1e12)
        rough = [piece for run, hold in runs for piece in keep_inside(self.shape(g, run, hold, smooth=False), window)]
        if not rough:
            self.sink.warning(
                "graph-outside-window", f'graph "{g.title}" lies wholly outside the timeline, so it is left out',
                g.location,
            )
            return None
        top = max(v for piece in rough for _, v in piece)
        bottom = min(v for piece in rough for _, v in piece)
        up, down = max(top, 0.0), max(-bottom, 0.0)

        if g.range is not None:
            rate = g.height_mm / (math.log10(g.range) if log else g.range)
        elif g.height_mm is not None:
            rate = g.height_mm / max(up, down) if max(up, down) > 0 else g.height_mm
        else:
            room_above, room_below = self.by - st.graph_fit_margin, self.width - self.by - st.graph_fit_margin
            rates = ([room_above / up] if up > 0 else []) + ([room_below / down] if down > 0 else [])
            rate = min(rates) if rates else min(room_above, room_below)

        path: list[list[Point]] = []  # the line, less dots
        dots: list[list[Point]] = []  # isolated points (§15.6)
        for run, hold in runs:
            on_paper = [(x, self.by - rate * v) for x, v in run]
            is_dot = len(run) == 1 and not (g.line is LineMode.STEP and hold is not None)
            for piece in keep_inside(self.shape(g, on_paper, hold, smooth=True), window):
                (dots if is_dot else path).append(piece if is_dot else simplify(piece, st.graph_simplify))
        whole = path + dots
        drawn = [piece for line in whole for piece in keep_inside(line, self.paper)]
        if sum(polyline_length(p) for p in drawn) < sum(polyline_length(p) for p in whole) - 1e-6:
            self.sink.warning(
                "graph-off-paper",
                f'graph "{g.title}" runs past the edge of the paper and is cut off there; give it a smaller height=',
                g.location,
            )

        def value_of(m: float) -> float:
            return origin * 10**m if log else origin + m

        def y_of(value: float) -> float:
            return self.by - rate * mapped(value)

        return _Draft(g, origin, rate, rate * up, rate * down, value_of(min(bottom, 0.0)), value_of(max(top, 0.0)),
                      path, drawn, y_of)

    def shape(self, g: Graph, run: list[Point], hold: float | None, smooth: bool) -> list[Point]:
        """A run of points as the line joins them (§15.6). An isolated point is a dot."""
        dot = self.style.graph_dot
        if len(run) == 1 and not (g.line is LineMode.STEP and hold is not None):
            x, v = run[0]
            return [(x - dot / 2, v), (x + dot / 2, v)]
        if g.line is LineMode.STEP:
            line = [run[0]]
            for (_, v0), (x1, v1) in zip(run, run[1:], strict=False):
                line += [(x1, v0), (x1, v1)]
            if hold is not None:
                line.append((hold, run[-1][1]))
            return line
        if g.line is LineMode.SMOOTH and smooth:
            return steffen(run, self.style.graph_curve_piece)
        return list(run)

    # -- the graph's own text (§15.9) ---------------------------------------------------------------------

    def free(self, box: Box) -> bool:
        if box.x0 < 0.5 or box.x1 > self.length - 0.5 or box.y0 < self.paper.y0 or box.y1 > self.paper.y1:
            return False
        padded = box.padded(self.style.collision_pad)
        return not any(padded.overlaps(o) for o in self.taken)

    def value_scales(self, d: _Draft) -> None:
        g, st = d.graph, self.style
        if g.value_scale is ValueScaleMode.OFF:
            return
        log = g.y_scale is YScale.LOG
        marks = list(g.value_marks) if g.value_marks is not None else auto_marks(d.lowest, d.highest, log)
        size = g.font_size_mm * st.tick_label_scale
        sample = self.text(g.font, size, "0")
        cap = sample.shaped.cap_height
        clearance = st.pen_half_width + st.collision_pad + 0.1
        above = self.by - clearance - sample.y1  # the origin's label, just over the baseline
        below = self.tick_bottom + clearance - sample.y0  # or else just under the tick labels
        reserved = Box(-1e12, above + sample.y0 - st.collision_pad, 1e12, self.tick_bottom)
        chosen: list[tuple[float, list[float], str]] = [(d.origin, [above, below], number_text(d.origin))]
        for v in sorted(marks, key=d.y_of):
            y_mark = d.y_of(v)
            if abs(y_mark - self.by) < 1e-6 or not self.paper.y0 + 1 < y_mark < self.paper.y1 - 1:
                continue
            label = number_text(v)
            y = y_mark + cap / 2
            box = self.text(g.font, size, label).placed(label, 0, y).box.padded(st.collision_pad)
            if box.overlaps(reserved):
                continue
            if all(not box.overlaps(self.text(g.font, size, t).placed(t, 0, ys[0]).box) for _, ys, t in chosen):
                chosen.append((v, [y], label))
        ys = [d.y_of(v) for v, _, _ in chosen]
        names = [t for _, _, t in chosen]
        widest = max(self.text(g.font, size, t).width for t in names)
        unit_options: list[float] = []
        if g.unit:
            # The unit heads the labels at the end of the rule further from the baseline, or else the other end.
            unit = self.text(g.font, size, g.unit)
            pitch = 1.25 * (sample.y1 - sample.y0) + 2 * st.collision_pad
            first_choices = [options[0] for _, options, _ in chosen]
            top, bottom = min(first_choices) - pitch, max(first_choices) + pitch
            unit_options = [top, bottom] if self.by - min(ys) >= max(ys) - self.by else [bottom, top]
            names.append(g.unit)
            widest = max(widest, unit.width)
        span = st.value_tick + st.value_label_gap + widest

        if g.value_scale is ValueScaleMode.START:
            wanted, reach = [1.0], st.graph_start_reach
        else:
            every = g.value_scale_mm
            wanted = [1.0] + [k * every for k in range(1, math.floor(self.length / every + 1e-9) + 1)]
            reach = every - span
        last = self.length - span - 0.5
        steps = max(1, int(reach / st.graph_search_step))
        for want in wanted:
            if want <= last:
                candidates = [want + k * st.graph_search_step for k in range(steps)]
                candidates = [x for x in candidates if x <= last]
            else:
                candidates = [last - k * st.graph_search_step for k in range(steps)]
                candidates = [x for x in candidates if x >= 0.5]
            best = None
            for x in candidates:
                if any(Box(x - 1, min(ys), x + span, max(ys)).overlaps(c) for c in self.columns):
                    continue
                labels, ok = [], []
                for _, options, label in chosen:
                    placed = [self.text(g.font, size, label).placed(label, x + st.value_tick + st.value_label_gap, y)
                              for y in options]
                    fits = [p for p in placed if self.free(p.box)]
                    labels.append((fits or placed)[0])
                    ok.append(bool(fits))
                if unit_options:
                    mine = [p.box.padded(st.collision_pad) for p, k in zip(labels, ok, strict=True) if k]
                    placed = [unit.placed(g.unit, x + st.value_tick + st.value_label_gap, y) for y in unit_options]
                    fits = [p for p in placed if self.free(p.box) and not any(p.box.overlaps(m) for m in mine)]
                    labels.append((fits or placed)[0])
                    ok.append(bool(fits))
                if best is None or sum(ok) > sum(best[2]):
                    best = (x, labels, ok)
                if all(ok):
                    break
            if best is None:
                self.sink.warning(
                    "graph-scale-room", f'graph "{g.title}" has no room for a value scale near {want / 10:.0f}cm',
                    g.location,
                )
                continue
            x, labels, ok = best
            if not all(ok):
                left_out = ", ".join(t for t, k in zip(names, ok, strict=True) if not k)
                self.sink.warning(
                    "graph-label-room",
                    f'graph "{g.title}": no room for the value label{"s" if sum(not k for k in ok) > 1 else ""} '
                    f"{left_out} on its value scale near {x / 10:.0f}cm",
                    g.location,
                )
            d.rules.append([(x, min(ys)), (x, max(ys))])
            for v, _, _ in chosen:
                if abs(d.y_of(v) - self.by) > 1e-6:
                    d.rules.append([(x, d.y_of(v)), (x + st.value_tick, d.y_of(v))])
            shown = [label for label, fits in zip(labels, ok, strict=True) if fits]
            for label in shown:
                d.texts.append(label)
                self.taken.append(label.box)
            top = min([min(ys)] + [label.box.y0 for label in shown])
            bottom = max([max(ys)] + [label.box.y1 for label in shown])
            self.columns.append(Box(x - 1, top - 3, x + span, bottom + 3))

    def title(self, d: _Draft) -> None:
        g, st = d.graph, self.style
        if not g.title:
            return
        text = self.text(g.font, g.font_size_mm, g.title)
        lines = d.drawn
        if not lines:
            return
        x = max(0.5, min(p[0] for line in lines for p in line))
        while x + text.width <= self.length - 0.5:
            extent = self.extent(lines, x - 0.5, x + text.width + 0.5)
            if extent is not None:
                top, bottom = extent
                over = top - st.graph_title_gap - text.y1  # text sitting above the line
                under = bottom + st.graph_title_gap - text.y0  # text hanging below it
                options = (over, under) if (top + bottom) / 2 < self.by else (under, over)  # away from the baseline first
                for y in options:
                    placed = text.placed(g.title, x - text.x0, y)
                    if self.free(placed.box):
                        d.texts.append(placed)
                        self.taken.append(placed.box)
                        return
            x += st.graph_search_step
        self.sink.warning("graph-title-room", f'no room anywhere for the title of graph "{g.title}", so it is left out',
                          g.location)

    @staticmethod
    def extent(lines: list[list[Point]], xa: float, xb: float) -> tuple[float, float] | None:
        """The highest and lowest the line goes (smallest and largest y) between xa and xb."""
        ys = []
        for line in lines:
            for a, b in zip(line, line[1:], strict=False):
                lo, hi = min(a[0], b[0]), max(a[0], b[0])
                if hi < xa or lo > xb:
                    continue
                ys += [p[1] for p in (a, b) if xa <= p[0] <= xb]
                if hi > lo:
                    ys += [a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]) for x in (xa, xb) if lo <= x <= hi]
        return (min(ys), max(ys)) if ys else None

    # -- breaking around text (§15.8) -------------------------------------------------------------------------

    def finish(self, d: _Draft, clear: tuple[Box, ...]) -> PlacedGraph:
        def broken(lines: list[list[Point]]) -> tuple[Polyline, ...]:
            out = []
            for line in lines:
                bounds = _bounds(line)
                pieces = [line]
                for box in clear:
                    if touches(box, bounds):
                        pieces = [part for piece in pieces for part in cut_out(piece, box)]
                out += [tuple(p) for p in pieces if len(p) > 1]
            return tuple(out)

        return PlacedGraph(
            graph=d.graph,
            origin=d.origin,
            rate_mm=d.rate,
            above_mm=d.above,
            below_mm=d.below,
            path=tuple(tuple(p) for p in d.path),
            line=broken(d.drawn),
            rules=broken(d.rules),
            texts=tuple(d.texts),
            clear=clear,
            baseline_y=self.by,
            paper=Box(0.0, self.paper.y0, self.length, self.paper.y1),
        )


# -- shading (§15.7), for draw ------------------------------------------------------------------------------


def _bounds(points) -> Box:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return Box(min(xs), min(ys), max(xs), max(ys))


def shading_box(pg: PlacedGraph) -> Box | None:
    """Where a graph's shading can be: a box to fill with pattern lines before clipping them to the shading."""
    g = pg.graph
    points = [p for line in pg.path for p in line]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    if g.shadow_mm is not None:
        reach = g.shadow_mm + g.fill_depth_mm
        box = Box(min(xs) + g.shadow_mm, min(ys) + g.shadow_mm, max(xs) + reach, max(ys) + reach)
    else:
        box = Box(min(xs), min(ys + [pg.baseline_y]), max(xs), max(ys + [pg.baseline_y]))
    box = Box(max(box.x0, pg.paper.x0), max(box.y0, pg.paper.y0), min(box.x1, pg.paper.x1), min(box.y1, pg.paper.y1))
    return box if box.width > 0 and box.height > 0 else None


def shading(pg: PlacedGraph, candidates: list[list[Point]], shortest: float, shadow_gap: float) -> list[list[Point]]:
    """The parts of ``candidates`` (pattern lines) that lie in the graph's shading, broken around text."""
    g = pg.graph
    lines = list(pg.path)
    segments = [(a, b) for line in lines for a, b in zip(line, line[1:], strict=False)]
    if not segments:
        return []
    if g.shadow_mm is not None:
        s, depth = g.shadow_mm, g.fill_depth_mm
        quads = []
        for a, b in segments:
            quad = [(a[0] + s, a[1] + s), (b[0] + s, b[1] + s), (b[0] + s + depth, b[1] + s + depth),
                    (a[0] + s + depth, a[1] + s + depth)]
            quads.append((quad, Box(min(p[0] for p in quad), min(p[1] for p in quad), max(p[0] for p in quad),
                                    max(p[1] for p in quad))))
        near = [(a, b, segment_box(a, b, shadow_gap)) for a, b in segments]

        def inside(p: Point, q: Point) -> list:
            sb = segment_box(p, q)
            intervals = merge([iv for quad, qb in quads if touches(qb, sb) if (iv := inside_convex(p, q, quad))])
            if not intervals:
                return []
            gaps = [iv for a, b, nb in near if touches(nb, sb) for iv in near_segment(p, q, a, b, shadow_gap)]
            return subtract(intervals, merge(gaps))
    else:
        by = pg.baseline_y
        polygons = [line + ((line[-1][0], by), (line[0][0], by)) for line in lines]
        depth = g.fill_depth_mm
        reach = [(a, b, segment_box(a, b, depth)) for a, b in segments] if depth is not None else []

        def inside(p: Point, q: Point) -> list:
            intervals = merge([iv for poly in polygons for iv in inside_even_odd(p, q, list(poly))])
            if not intervals or depth is None:
                return intervals
            sb = segment_box(p, q)
            close = [iv for a, b, rb in reach if touches(rb, sb) for iv in near_segment(p, q, a, b, depth)]
            return intersect(intervals, merge(close))

    out = []
    for candidate in candidates:
        for piece in clip(candidate, inside, shortest):
            pieces = [piece]
            for box in pg.clear:
                pieces = [part for part in pieces for part in cut_out(part, box)]
            out += [p for p in pieces if polyline_length(p) >= shortest]
    return out
