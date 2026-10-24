"""The AST: what a document *says*, with no physical resolution yet (interpreter spec, "Internal architecture").

Everything here is immutable. Inheritance that is purely a matter of what the text says (a group child's pen,
font and font size) is resolved here; anything that depends on layout (a group child's side) is left for
layout, so ``Entity.side`` is only ever an explicitly written (or include-forced) side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Mapping

from .dates import DateRange, DateValue
from .diagnostics import SourceLocation
from .fonts import Font
from .units import Scale


class Kind(Enum):
    PERSON = "person"
    EVENT = "event"
    SPAN = "span"
    GROUP = "group"

    @property
    def is_banded(self) -> bool:
        return self is not Kind.EVENT


class Side(Enum):
    ABOVE = "above"
    BELOW = "below"


class Baseline(Enum):
    HIGH = "high"
    MIDDLE = "middle"
    LOW = "low"


class OpenEndStyle(Enum):
    SAWTOOTH = "sawtooth"
    SINE = "sine"


class TimeLabel(Enum):
    """An event's time label (§3.11): which part of its date to write under its flag."""

    NONE = "none"
    DATE = "date"  # the date exactly as written
    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    HOUR = "hour"
    MIN = "min"
    SEC = "sec"


class Fill(Enum):
    NONE = "none"
    SOLID = "solid"
    DIAGONAL = "diagonal"
    CROSSHATCH = "crosshatch"
    WAVE = "wave"
    DOTS = "dots"


@dataclass(frozen=True)
class Illustration:
    name: str  # the resource name it was fetched under
    svg: bytes
    width: float  # intrinsic size, in the SVG's own units (only the ratio matters)
    height: float
    height_mm: float | None  # explicit height=, or None for the default of 2 lanes

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


@dataclass(frozen=True)
class Entity:
    kind: Kind
    label: str
    when: DateValue | DateRange  # DateValue for an event, DateRange for everything else
    priority: int  # net priority delta, include offsets applied
    side: Side | None  # explicitly written or include-forced; None = automatic (or inherited from a group)
    pen: str  # effective pen: its own, else its group's, else black
    fill: Fill
    fill_pen: str  # effective pen for the fill pattern: its own fill_pen, else its group's, else its pen (§3.7)
    font: str  # effective font: a key into TimelineDocument.fonts
    font_size_mm: float  # effective font size (the em)
    time_label: TimeLabel  # effective, for an event; for a group, what its members inherit; NONE for bars
    illustration: Illustration | None
    children: tuple[Entity, ...]  # groups only
    member_of: str | None  # the label of the enclosing group (metadata only)
    order: int  # position in the flattened document, for deterministic tie-breaks
    location: SourceLocation

    def walk(self) -> Iterator[Entity]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class TimelineSettings:
    start: DateValue
    end: DateValue | None  # None when end=now; layout resolves it from the host-supplied now
    width_mm: float
    length_mm: float | None  # exactly one of length_mm and scale is set
    scale: Scale | None
    baseline: Baseline
    above_lane_height_mm: float
    below_lane_height_mm: float
    above_baseline_offset_mm: float
    below_baseline_offset_mm: float
    ticks_mm: float | None  # target tick spacing; None = ticks=off
    tick_label_every: int | None
    open_end_style: OpenEndStyle
    font: str
    font_size_mm: float
    time_label: TimeLabel
    location: SourceLocation

    @property
    def end_is_now(self) -> bool:
        return self.end is None


class YScale(Enum):
    """How a graph's values map to distance from the baseline (§15.5)."""

    LINEAR = "linear"
    LOG = "log"


class LineMode(Enum):
    """How a graph's line joins its points (§15.6)."""

    STRAIGHT = "straight"
    SMOOTH = "smooth"
    STEP = "step"


class ValueScaleMode(Enum):
    """Where a graph's value scales go (§15.9)."""

    OFF = "off"
    START = "start"
    EVERY = "every"  # repeated at value_scale_mm along the roll


@dataclass(frozen=True)
class GraphPoint:
    seconds: int  # the start of the point's date (§15.4)
    value: float | None  # None marks a gap in the line
    location: SourceLocation  # the CSV row, or the line of the graph's body


@dataclass(frozen=True)
class Graph:
    """A background graph (§15): a line of values against the timeline's time axis, drawn under the foreground."""

    title: str  # "" for none
    pen: str
    points: tuple[GraphPoint, ...]  # in time order, gaps included
    data: str | None  # the CSV file's resource name, or None for points written inline
    origin: float | None  # the value drawn on the baseline; None for origin=first
    y_scale: YScale
    height_mm: float | None
    range: float | None  # with height_mm, pins the rate: a difference (linear) or a ratio (log)
    line: LineMode
    fill: Fill
    fill_pen: str  # the pen its shading is drawn in: its own fill_pen, else its pen (§15.7)
    fill_depth_mm: float | None
    shadow_mm: float | None
    value_scale: ValueScaleMode
    value_scale_mm: float | None  # the interval, for ValueScaleMode.EVERY
    value_marks: tuple[float, ...] | None  # None: chosen automatically
    unit: str  # printed on each value scale (§15.9); "" for none
    font: str  # a key into TimelineDocument.fonts
    font_size_mm: float
    order: int  # among graphs, in document order
    location: SourceLocation


@dataclass(frozen=True)
class TimelineDocument:
    timeline: TimelineSettings
    entities: tuple[Entity, ...]  # top level, in document order
    fonts: Mapping[str, Font] = field(repr=False)
    graphs: tuple[Graph, ...] = ()  # backgrounds (§15), in document order

    def walk(self) -> Iterator[Entity]:
        """Every entity, groups before their members, in document order."""
        for entity in self.entities:
            yield from entity.walk()
