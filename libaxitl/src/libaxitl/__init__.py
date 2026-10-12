"""libaxitl: the reusable engine behind axitime — parse, layout and render ``.axitl`` timelines.

Pure three-stage pipeline (interpreter spec, "Library boundary"):

- ``parse(source, resolve) -> ParseResult`` — the only stage that calls host I/O, via ``resolve``.
- ``layout(ast, now) -> ResolvedLayout`` — not yet implemented.
- ``render(layout, options) -> svg`` — not yet implemented.
"""

from .dates import DateRange, DateValue, Precision, parse_date, parse_when
from .diagnostics import AxitlError, Diagnostic, Severity, SourceLocation
from .fetch import Resource
from .fonts import BUILTIN_FONTS, Font
from .model import Baseline, Entity, Fill, Illustration, Kind, OpenEndStyle, Side, TimelineDocument, TimelineSettings
from .parser import ParseResult, parse
from .pens import PENS
from .text import ShapedText, shape
from .units import parse_length

__version__ = "0.1.0"

__all__ = [
    "AxitlError", "BUILTIN_FONTS", "Baseline", "DateRange", "DateValue", "Diagnostic", "Entity", "Fill", "Font",
    "Illustration", "Kind", "OpenEndStyle", "PENS", "ParseResult", "Precision", "Resource", "Severity", "ShapedText",
    "Side", "SourceLocation", "TimelineDocument", "TimelineSettings", "parse", "parse_date", "parse_length",
    "parse_when", "shape", "__version__",
]
