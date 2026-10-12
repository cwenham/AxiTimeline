"""``render(layout, options) -> svg``: the SVG a plotter draws from, or a person previews.

**Units.** One SVG user unit is one millimetre, and the ``width``/``height`` attributes are in mm, so plotter
software draws at true size. Coordinates are the layout's own (x along the roll from the timeline's start, y
across it from the finished top edge), so a stroke has the same coordinates in every file of a job.

**The page** (``viewBox``) covers the window being rendered, plus any bleed, along the roll, and the finished
width plus the crop-mark margin across it. Every pen's SVG from one render shares that page, which is what
makes separately plotted passes line up.

**Windows** are cut geometrically: strokes are clipped at the window's edges (plus bleed) rather than hidden
with an SVG clip path, which plotter software ignores. Bleed extends strokes past an edge only where that edge
is a cut in the middle of the job, never at the job's own start or end (interpreter spec, ``--bleed``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Mapping
from xml.sax.saxutils import quoteattr

from ._version import __version__
from .draw import Drawing, Stage, draw
from .geometry import Box, keep_inside
from .layout import ResolvedLayout
from .pens import PENCIL_GRADES
from .units import format_number

METADATA_NAMESPACE = "urn:axitimeline:job:1"
_INKSCAPE = "http://www.inkscape.org/namespaces/inkscape"
_FIELD = re.compile(r"^[a-z][a-z0-9-]*$")

# Screen colours for previews; on paper the pen decides.
_COLOURS = {
    "red": "#c62828", "orange": "#ef6c00", "yellow": "#f9a825", "green": "#2e7d32", "blue": "#1565c0",
    "indigo": "#3949ab", "violet": "#6a1b9a", "black": "#212121", "grey": "#757575",
}


class RenderError(ValueError):
    """Render options that don't fit the job. The message is written for the operator."""


@dataclass(frozen=True)
class RenderOptions:
    pen: str | None = None  # only this pen's strokes (a file to plot); None for every pen (a preview)
    window: tuple[float, float] | None = None  # (start, length) along the roll in mm; None for the whole job
    bleed_mm: float = 0.0  # how far strokes run past an edge that is a cut in the middle of the job
    metadata: Mapping[str, str] = field(default_factory=dict)  # host fields for <metadata>: job hash and so on
    stroke_width_mm: float = 0.3  # for viewing on screen only


@dataclass(frozen=True)
class Page:
    """The stretch of the roll a render covers, and where its strokes are cut."""

    window_start: float
    window_end: float
    bleed_start: float
    bleed_end: float
    x0: float  # where strokes are cut: the window less any bleed
    x1: float
    y0: float  # the page's top edge, above the finished width by the crop-mark margin
    y1: float


def pen_colour(pen: str) -> str:
    if pen in _COLOURS:
        return _COLOURS[pen]
    if pen.startswith("fountain-"):
        return _COLOURS.get(pen.removeprefix("fountain-"), "#212121")
    grade = pen.removesuffix("-pencil")
    if grade in PENCIL_GRADES:  # soft grades darker, hard grades lighter
        shade = 0x55 + PENCIL_GRADES.index(grade) * 6
        return f"#{shade:02x}{shade:02x}{shade + 8:02x}"
    return "#212121"


def page_for(drawing: Drawing, window: tuple[float, float] | None, bleed: float) -> Page:
    total = drawing.length_mm
    if window is None:
        start, end = 0.0, total
    else:
        start, length = window
        if not 0 <= start < total:
            raise RenderError(
                f"the window starts at {format_number(start)}mm, outside the job (0 to {format_number(total)}mm)"
            )
        if length <= 0:
            raise RenderError(f"the window's length must be more than zero, not {format_number(length)}mm")
        end = min(start + length, total)
    if bleed < 0:
        raise RenderError("bleed can't be negative")
    bleed_start = bleed if start > 0 else 0.0
    bleed_end = bleed if end < total else 0.0
    margin = drawing.page_margin_mm
    return Page(
        start, end, bleed_start, bleed_end, max(0.0, start - bleed_start), min(total, end + bleed_end),
        -margin, drawing.width_mm + margin,
    )


def _pieces(drawing: Drawing, page: Page, pen: str, stage: Stage) -> list[list[tuple[float, float]]]:
    cut = Box(page.x0, -1e9, page.x1, 1e9)
    return [
        piece
        for stroke in drawing.strokes
        if stroke.pen == pen and stroke.stage is stage
        for piece in keep_inside(stroke.points, cut)
    ]


def stroke_lengths(drawing: Drawing, page: Page) -> dict[str, float]:
    """How much each pen draws within a page (window plus bleed), in mm, in pass order."""
    return {pen: sum(_length(p) for stage in Stage for p in _pieces(drawing, page, pen, stage)) for pen in drawing.pens}


def _points(points) -> str:
    first, *rest = points
    head = f"M{format_number(first[0])} {format_number(first[1])}"
    return head + "L" + " ".join(f"{format_number(x)} {format_number(y)}" for x, y in rest)


def render(layout: ResolvedLayout, options: RenderOptions | None = None, *, drawing: Drawing | None = None) -> str:
    """The SVG for ``layout``: every pen (a preview) or one pen (to plot), whole or windowed.

    ``drawing`` can be passed in when the caller already has ``draw(layout)``, to render several pens from one
    drawing without redrawing it.
    """
    options = options or RenderOptions()
    drawing = drawing or draw(layout)
    if options.pen is not None and options.pen not in drawing.pens:
        raise RenderError(f"this job doesn't use the pen '{options.pen}'; it uses {', '.join(drawing.pens)}")
    page = page_for(drawing, options.window, options.bleed_mm)
    pens = [options.pen] if options.pen else list(drawing.pens)

    layers = []
    total = 0.0
    for pen in pens:
        paths = []
        for stage in Stage:
            pieces = _pieces(drawing, page, pen, stage)
            if pieces:
                total += sum(_length(p) for p in pieces)
                paths.append(f'<path id="{pen}-{stage.value}" d="{" ".join(_points(p) for p in pieces)}"/>')
        layers.append(
            f'<g inkscape:groupmode="layer" inkscape:label="{pen}" id="pen-{pen}" fill="none" '
            f'stroke="{pen_colour(pen)}" stroke-width="{format_number(options.stroke_width_mm)}" '
            f'stroke-linecap="round" stroke-linejoin="round">\n' + "".join(p + "\n" for p in paths) + "</g>"
        )

    fields = {
        "pen": options.pen or "all",
        "stroke-length-mm": format_number(total, 1),
        "window-start-mm": format_number(page.window_start),
        "window-end-mm": format_number(page.window_end),
        "bleed-start-mm": format_number(page.bleed_start),
        "bleed-end-mm": format_number(page.bleed_end),
        "libaxitl-version": __version__,
    }
    for key, value in options.metadata.items():
        if not _FIELD.match(key) or key in fields:
            raise RenderError(f"'{key}' can't be used as a metadata field")
        fields[key] = str(value)
    attributes = " ".join(f"{k}={quoteattr(fields[k])}" for k in sorted(fields))
    width, height = page.x1 - page.x0, page.y1 - page.y0
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="{_INKSCAPE}" '
        f'width="{format_number(width)}mm" height="{format_number(height)}mm" '
        f'viewBox="{format_number(page.x0)} {format_number(page.y0)} {format_number(width)} {format_number(height)}">\n'
        f'<metadata><axitime:job xmlns:axitime="{METADATA_NAMESPACE}" {attributes}/></metadata>\n'
        + "\n".join(layers)
        + "\n</svg>\n"
    )


def _length(points) -> float:
    return sum(math.dist(p, q) for p, q in zip(points, points[1:], strict=False))
