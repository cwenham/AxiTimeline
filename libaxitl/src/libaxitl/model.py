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


@dataclass(frozen=True)
class TimelineDocument:
    timeline: TimelineSettings
    entities: tuple[Entity, ...]  # top level, in document order
    fonts: Mapping[str, Font] = field(repr=False)

    def walk(self) -> Iterator[Entity]:
        """Every entity, groups before their members, in document order."""
        for entity in self.entities:
            yield from entity.walk()
