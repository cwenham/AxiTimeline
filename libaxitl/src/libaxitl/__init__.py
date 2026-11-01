"""libaxitl: the reusable engine behind axitime — parse, layout and render ``.axitl`` timelines.

Pure three-stage pipeline (interpreter spec, "Library boundary"):

- ``parse(source, resolve) -> ParseResult`` — the only stage that calls host I/O, via ``resolve``.
- ``layout(ast, now) -> ResolvedLayout`` — pure; ``now`` comes from the host.
- ``render(layout, options) -> svg`` — pure; ``draw(layout)`` gives the strokes behind it.
"""

from ._version import __version__
from .dates import DateRange, DateValue, Precision, parse_date, parse_when
from .draw import Drawing, DrawStyle, Stage, Stroke, draw
from .diagnostics import AxitlError, Diagnostic, Severity, SourceLocation
from .fetch import Resource
from .fonts import BUILTIN_FONTS, Font
from .geometry import Box
from .graphs import PlacedGraph
from .layout import (
    FlagDirection,
    LabelPlacement,
    LayoutStyle,
    PlacedBar,
    PlacedBlock,
    PlacedEvent,
    PlacedIllustration,
    PlacedText,
    ResolvedLayout,
    Tick,
    layout,
)
from .model import (
    Baseline,
    CreditLine,
    Credits,
    Edge,
    Entity,
    Fill,
    Graph,
    GraphPoint,
    Horizontal,
    Illustration,
    Kind,
    LineMode,
    Note,
    NoteAnchor,
    NoteParagraph,
    OpenEndStyle,
    Side,
    TimelineDocument,
    TimelineSettings,
    Title,
    ValueScaleMode,
    YScale,
)
from .parser import ParseResult, parse
from .pens import PENS
from .render import Page, RenderError, RenderOptions, page_for, render, stroke_lengths
from .text import ShapedText, shape
from .units import parse_length


__all__ = [
    "draw", "layout", "page_for", "parse", "render", "stroke_lengths", "parse_date", "parse_length", "parse_when", "shape", "AxitlError", "BUILTIN_FONTS",
    "Baseline", "Box", "CreditLine", "Credits", "Edge", "Horizontal", "DrawStyle", "Drawing", "Page", "RenderError", "RenderOptions", "Stage", "Stroke", "DateRange", "DateValue", "Diagnostic", "Entity", "Fill", "FlagDirection", "LabelPlacement", "Font",
    "Graph", "GraphPoint", "Illustration", "Kind", "LayoutStyle", "LineMode", "Note", "NoteAnchor", "NoteParagraph", "OpenEndStyle", "PENS", "ParseResult",
    "PlacedBar", "PlacedBlock", "PlacedEvent", "PlacedGraph", "ValueScaleMode", "YScale",
    "PlacedIllustration", "PlacedText", "Precision", "ResolvedLayout", "Resource", "Severity", "ShapedText", "Side",
    "SourceLocation", "Tick", "TimelineDocument", "TimelineSettings", "Title", "__version__",
]
