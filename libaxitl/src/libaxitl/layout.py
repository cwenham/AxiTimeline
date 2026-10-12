"""``layout(document, now) -> ResolvedLayout``: where everything goes on the paper (language spec §§4, 6–10).

Pure: no I/O and no clock. ``now`` is supplied by the host and only consulted when the timeline ends at ``now``.

Coordinates are millimetres in SVG orientation: x runs along the roll from ``start`` (0) to ``end``
(``length_mm``); y runs across it from the top edge (0) to the bottom edge (``width_mm``). "Above" the baseline
means smaller y. Internally, positions across the roll are often handled as a *distance from the baseline* on
one side, which is the same calculation for both sides.

Layout runs in three phases (§6):

- **A** — bars (person, span, group) get a side and a lane, and their illustrations a band of lanes;
- **B** — events get a side and a base pole length, and their illustrations a band beside the pole;
  illustrations in a pole's path are nudged sideways;
- **C** — colliding event flags are staggered, then flipped, then reported.

Every ordering uses the spec's explicit tie-breaks (priority, then start, then document order), so the same
document and ``now`` always give the same layout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .dates import DateRange, DateValue, time_label_text
from .diagnostics import Diagnostic, Diagnostics
from .geometry import Box
from .model import Baseline, Entity, Illustration, Kind, Side, TimeLabel, TimelineDocument
from .pens import PENS
from .text import ShapedText, shape
from .ticks import plan_ticks
from .units import Scale, format_number

PHI = (1 + 5**0.5) / 2
# Seconds in each scale unit. A year is the mean Gregorian year (365.2425 days), so mm/year is exact on average.
SECONDS_PER_UNIT = {"year": 31556952, "day": 86400, "hour": 3600, "minute": 60, "second": 1}
AXIS_PEN = "black"


@dataclass(frozen=True)
class LayoutStyle:
    """Spacing the spec leaves open ("a small margin"). Millimetres unless noted. Provisional values."""

    bar_inset: float = 1.0  # between a bar and the edges of its lane, top and bottom
    label_inset: float = 1.5  # between the end of a bar and its label
    label_margin: float = 0.5  # space a bar label needs above and below it, inside the bar
    lane_gap: float = 1.5  # least horizontal gap between neighbours in a lane
    flag_gap: float = 1.0  # between an event's pole and its flag text
    flag_clearance: float = 1.0  # between the outer edge of the bars a pole clears and its flag
    stagger_gap: float = 0.5  # between flags stacked by staggering
    collision_pad: float = 0.4  # around text when testing for collisions
    illustration_gap: float = 1.5  # between a pole and an illustration
    minor_tick: float = 1.0
    major_tick: float = 2.0
    tick_label_gap: float = 0.5  # between the end of a labelled tick and its label
    tick_label_scale: float = 0.75  # tick label size as a fraction of the timeline's font_size
    tick_label_spacing: float = 1.0  # least gap between neighbouring tick labels
    time_label_scale: float = 0.75  # an event's time label, as a fraction of its font_size (§3.11)
    time_label_gap: float = 0.4  # between an event's label and its time label
    pole_gap: float = 0.75  # left either side where a pole is broken around other ink (§8)
    min_pole_segment: float = 1.0  # shorter pieces of a broken pole are left out


DEFAULT_STYLE = LayoutStyle()


class FlagDirection(Enum):
    RIGHT = "right"  # towards later dates
    LEFT = "left"


# -- the result ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlacedText:
    text: str  # as written in the source
    shaped: ShapedText  # what will be drawn (with any missing characters replaced)
    x: float  # pen origin: the left end of the text's baseline
    y: float
    box: Box  # the font's line box joined with the actual ink; what collisions are tested against


@dataclass(frozen=True)
class PlacedIllustration:
    illustration: Illustration
    owner: Entity
    side: Side
    lane: int  # innermost lane of the band
    lanes: int  # how many lanes the band reserves
    box: Box  # where the drawing goes


@dataclass(frozen=True)
class PlacedBar:
    entity: Entity
    side: Side
    lane: int
    x0: float
    x1: float
    y0: float  # top of the bar's rectangle
    y1: float  # bottom
    open_end: bool  # the entity is ongoing (written 1953- or 1953-04-01/)
    clipped_start: bool  # it began before the timeline's start
    clipped_end: bool  # it continues past the timeline's end
    label: PlacedText
    illustration: PlacedIllustration | None

    @property
    def cap_start(self) -> bool:
        """Draw the open-end cap at the start (§4.2)."""
        return self.clipped_start

    @property
    def cap_end(self) -> bool:
        """Draw the open-end cap at the end (§3.6, §4.2)."""
        return self.open_end or self.clipped_end


@dataclass(frozen=True)
class PlacedEvent:
    entity: Entity
    side: Side
    x: float
    pole_length: float  # from the baseline to the pole's tip
    base_pole_length: float  # the §8.1 floor it was never shortened below
    tip_y: float
    pole_segments: tuple[tuple[float, float], ...]  # (y from, y to), baseline outward: what's left to draw (§8)
    direction: FlagDirection
    flag: PlacedText  # the event's label
    time_label: PlacedText | None  # under the label (§3.11)
    flag_box: Box  # label and time label together
    illustration: PlacedIllustration | None


@dataclass(frozen=True)
class Tick:
    seconds: int
    x: float
    length: float  # labelled ticks are longer
    label: PlacedText | None


@dataclass(frozen=True)
class SideSummary:
    side: Side
    space_mm: float  # from the baseline to the paper's edge
    inner_mm: float  # from the baseline to the inner edge of lane 0
    lane_height_mm: float
    lane_capacity: int
    lanes_used: int


@dataclass(frozen=True)
class ResolvedLayout:
    document: TimelineDocument
    width_mm: float
    length_mm: float
    baseline_y: float
    start_seconds: int  # the first moment the timeline shows (x = 0)
    end_seconds: int  # the moment at x = length_mm (the end of the end date's period)
    scale: Scale  # as written, or derived from length= in a readable unit
    scale_derived: bool
    now: DateValue | None  # the resolved, truncated now, when the timeline ends at now
    above: SideSummary
    below: SideSummary
    bars: tuple[PlacedBar, ...]  # in document order
    events: tuple[PlacedEvent, ...]  # in document order
    ticks: tuple[Tick, ...]
    tick_interval: str | None  # e.g. "2 years"; None with ticks=off
    tick_label_interval: str | None
    axis_pen: str  # draws the baseline and ticks, in the first pass (§10.4)
    pens: tuple[str, ...]  # every pen the job needs, axis pen first
    omitted: tuple[Entity, ...]  # wholly outside the timeline window (§4.2)
    diagnostics: tuple[Diagnostic, ...]  # warnings; a layout with errors raises AxitlError instead

    def seconds_to_position(self, seconds: int) -> float:
        return self.length_mm * (seconds - self.start_seconds) / (self.end_seconds - self.start_seconds)

    def time_to_position(self, date: DateValue, *, end: bool = False) -> float:
        """Where ``date`` falls along the roll, in mm: the start of its period, or with ``end``, the end of it.

        Not clamped: a date outside the timeline gives a position before 0 or after ``length_mm``.
        """
        return self.seconds_to_position(date.next_period_start() if end else date.first_second())

    @property
    def illustrations(self) -> tuple[PlacedIllustration, ...]:
        found = [b.illustration for b in self.bars] + [e.illustration for e in self.events]
        return tuple(i for i in found if i is not None)


# -- working state ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _SideGeometry:
    side: Side
    space: float
    inner: float
    lane_height: float
    capacity: int


class _Lanes:
    """Occupied stretches of each lane on one side: (x0, x1, owner)."""

    def __init__(self, capacity: int):
        self.items: list[list[tuple[float, float, str]]] = [[] for _ in range(capacity)]

    def free(self, lane: int, x0: float, x1: float, gap: float, ignore: str | None = None) -> bool:
        return all(b + gap <= x0 or x1 + gap <= a for a, b, owner in self.items[lane] if owner != ignore)

    def find(self, x0: float, x1: float, gap: float, height: int = 1, start: int = 0, ignore: str | None = None):
        """The lowest lane (at or after ``start``) beginning a band of ``height`` lanes free over [x0, x1]."""
        for lane in range(start, len(self.items) - height + 1):
            if all(self.free(i, x0, x1, gap, ignore) for i in range(lane, lane + height)):
                return lane
        return None

    def add(self, lane: int, height: int, x0: float, x1: float, owner: str) -> None:
        for i in range(lane, lane + height):
            self.items[i].append((x0, x1, owner))

    def remove(self, owner: str) -> None:
        for items in self.items:
            items[:] = [item for item in items if item[2] != owner]

    def used(self) -> int:
        """How many lanes from the baseline outward are in use (the highest occupied lane + 1)."""
        return max((i + 1 for i, items in enumerate(self.items) if items), default=0)


@dataclass
class _Text:
    """A shaped label and its line box relative to its pen origin."""

    shaped: ShapedText
    x0: float
    y0: float  # negative: above the text's baseline
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def placed(self, source: str, x: float, y: float) -> PlacedText:
        return PlacedText(source, self.shaped, x, y, Box(x + self.x0, y + self.y0, x + self.x1, y + self.y1))


@dataclass
class _Flag:
    """An event's flag: its label and, under it, any time label, both aligned on the pole's side."""

    name: _Text
    time: _Text | None
    time_text: str
    gap: float

    @property
    def width(self) -> float:
        return max(self.name.width, self.time.width if self.time else 0.0)

    @property
    def height(self) -> float:
        return self.name.height + (self.gap + self.time.height if self.time else 0.0)

    def placed(self, label: str, box: Box, direction: FlagDirection) -> tuple[PlacedText, PlacedText | None]:
        def at(text: _Text, top: float) -> tuple[float, float]:
            x = box.x0 - text.x0 if direction is FlagDirection.RIGHT else box.x1 - text.x1
            return x, top - text.y0

        name = self.name.placed(label, *at(self.name, box.y0))
        if self.time is None:
            return name, None
        return name, self.time.placed(self.time_text, *at(self.time, box.y0 + self.name.height + self.gap))


@dataclass
class _Illustration:
    illustration: Illustration
    owner: Entity
    side: Side
    lane: int
    lanes: int
    x0: float
    width: float
    height: float
    d_in: float  # distance of the band's inner edge from the baseline

    @property
    def key(self) -> str:
        return f"illustration:{self.owner.order}"

    @property
    def x1(self) -> float:
        return self.x0 + self.width


@dataclass
class _Event:
    entity: Entity
    side: Side
    x: float
    text: _Flag
    floor: float
    length: float
    default_direction: FlagDirection
    direction: FlagDirection
    illustration: _Illustration | None = None


@dataclass
class _Bar:
    entity: Entity
    side: Side
    lane: int
    x0: float
    x1: float
    open_end: bool
    clipped_start: bool
    clipped_end: bool
    text: _Text
    label_x: float
    illustration: _Illustration | None = None
    occupied: tuple[float, float] = field(default=(0.0, 0.0))


def layout(document: TimelineDocument, now: DateValue | None = None, *, style: LayoutStyle = DEFAULT_STYLE) -> ResolvedLayout:
    """Lay out a parsed document. ``now`` (from the host's clock or ``--now``) is needed when it ends at now.

    Raises :class:`AxitlError`, carrying every diagnostic, if the content can't be drawn.
    """
    return _Layout(document, now, style).run()


class _Layout:
    def __init__(self, document: TimelineDocument, now: DateValue | None, style: LayoutStyle):
        self.doc = document
        self.t = document.timeline
        self.now_in = now
        self.style = style
        self.sink = Diagnostics()
        self.bars: dict[int, _Bar] = {}
        self.events: list[_Event] = []
        self.ills: list[_Illustration] = []
        self.failed: set[int] = set()
        self.omitted: list[Entity] = []
        self.obstacle_cache: dict[Side, list[tuple[Box, str]]] = {}

    # -- setup -----------------------------------------------------------------------------------------------

    def run(self) -> ResolvedLayout:
        self.window()
        self.sink.raise_if_errors()
        self.sides()
        self.collect()
        self.phase_a()
        self.phase_b()
        self.nudge(warn=False)
        self.phase_c()
        self.nudge(warn=True)
        self.report_collisions()
        ticks = self.ticks()
        self.sink.raise_if_errors()
        return self.result(ticks)

    def window(self) -> None:
        start = self.t.start
        self.now = None
        end = self.t.end
        if end is None:
            if self.now_in is None:
                self.sink.error("needs-now", "the timeline ends at now, but no value for now was supplied", self.t.location)
                return
            if self.now_in.precision < start.precision:
                self.sink.error(
                    "now-too-coarse",
                    f"now ({self.now_in}) is less precise than the timeline's start ({start}); "
                    f"give it at least {start.precision.name.lower()} precision",
                    self.t.location,
                )
                return
            self.now = end = self.now_in.truncate(start.precision)
            if end.last_second() < start.first_second():
                self.sink.error("now-before-start", f"now ({end}) is before the timeline's start ({start})", self.t.location)
                return
        self.t0 = start.first_second()
        self.t1 = end.next_period_start()
        span = self.t1 - self.t0
        if self.t.length_mm is not None:
            self.length = self.t.length_mm
            self.mm_per_second = self.length / span
            self.scale = _readable_scale(self.mm_per_second, span)
            self.scale_derived = True
        else:
            self.mm_per_second = self.t.scale.mm / SECONDS_PER_UNIT[self.t.scale.unit]
            self.length = self.mm_per_second * span
            self.scale = self.t.scale
            self.scale_derived = False

    def x(self, seconds: int) -> float:
        return self.length * (seconds - self.t0) / (self.t1 - self.t0)

    def sides(self) -> None:
        w = self.t.width_mm
        self.baseline = {Baseline.LOW: w / PHI, Baseline.HIGH: w / PHI**2, Baseline.MIDDLE: w / 2}[self.t.baseline]
        self.tick_font = self.doc.fonts[self.t.font]
        self.tick_size = self.t.font_size_mm * self.style.tick_label_scale
        tick_band = 0.0
        if self.t.ticks_mm is not None:
            f, s = self.tick_font, self.tick_size / self.tick_font.units_per_em
            tick_band = self.style.major_tick + self.style.tick_label_gap + (f.ascender - f.descender) * s
        self.geom: dict[Side, _SideGeometry] = {}
        for side, space, inner, lane in (
            (Side.ABOVE, self.baseline, self.t.above_baseline_offset_mm, self.t.above_lane_height_mm),
            # Ticks and their labels hang below the baseline, so lanes there start beyond them.
            (Side.BELOW, w - self.baseline, tick_band + self.t.below_baseline_offset_mm, self.t.below_lane_height_mm),
        ):
            capacity = max(0, math.floor((space - inner) / lane + 1e-9))
            self.geom[side] = _SideGeometry(side, space, inner, lane, capacity)
        self.lanes = {side: _Lanes(g.capacity) for side, g in self.geom.items()}

    def y(self, side: Side, distance: float) -> float:
        return self.baseline - distance if side is Side.ABOVE else self.baseline + distance

    def band(self, side: Side, lane: int, height: int = 1) -> tuple[float, float]:
        g = self.geom[side]
        return g.inner + lane * g.lane_height, g.inner + (lane + height) * g.lane_height

    def text(self, entity_font: str, size: float, label: str) -> _Text:
        shaped = shape(self.doc.fonts[entity_font], label, size)
        f, s = shaped.font, shaped.scale
        x0, y0, x1, y1 = 0.0, -f.ascender * s, shaped.width, -f.descender * s
        ink = shaped.ink_box()
        if ink:
            x0, y0, x1, y1 = min(x0, ink[0]), min(y0, ink[1]), max(x1, ink[2]), max(y1, ink[3])
        return _Text(shaped, x0, y0, x1, y1)

    def collect(self) -> None:
        """Every entity's extent on the paper; entities wholly outside the window are omitted (§4.2)."""
        self.parent: dict[int, Entity] = {}
        for top in self.doc.entities:
            for e in top.walk():
                for child in e.children:
                    self.parent[child.order] = e
        self.extent: dict[int, tuple] = {}
        for e in self.doc.walk():
            if isinstance(e.when, DateRange):
                s = e.when.start.first_second()
                end = e.when.end.next_period_start() if e.when.end is not None else self.t1
                if end <= self.t0 or s >= self.t1:
                    self.omit(e)
                    continue
                self.extent[e.order] = (self.x(max(s, self.t0)), self.x(min(end, self.t1)), s < self.t0, end > self.t1)
            else:
                s = e.when.first_second()
                if not self.t0 <= s < self.t1:
                    self.omit(e)
                    continue
                self.extent[e.order] = (self.x(s),)

    def omit(self, e: Entity) -> None:
        self.omitted.append(e)
        self.sink.warning(
            "outside-window",
            f'{e.kind.value} "{e.label}" ({e.when}) lies wholly outside the timeline, so it is left out',
            e.location,
        )

    @staticmethod
    def key(e: Entity) -> tuple:
        start = e.when.start.first_second() if isinstance(e.when, DateRange) else e.when.first_second()
        return (-e.priority, start, e.order)

    def ordered(self, entities: list[Entity]) -> list[Entity]:
        """Forced entities first (§3.2), then the rest; each in priority, start, document order."""
        return sorted((e for e in entities if e.side is not None), key=self.key) + sorted(
            (e for e in entities if e.side is None), key=self.key
        )

    def inherited_side(self, e: Entity) -> Side | None:
        """A group member without its own ^/v takes its group's resolved side (§9)."""
        if e.side is not None:
            return e.side
        group = self.parent.get(e.order)
        if group is None or group.order not in self.extent:
            return None
        self.place_bar(group)  # a group is always placed before its members (§6)
        bar = self.bars.get(group.order)
        return bar.side if bar else None

    def choose_side(self, options: dict[Side, float]) -> Side:
        """The side with the lower value; a tie goes to the side with more remaining capacity (§6)."""
        best = min(options.values())
        tied = [s for s in (Side.ABOVE, Side.BELOW) if s in options and options[s] == best]
        if len(tied) == 1:
            return tied[0]

        def used_fraction(side: Side) -> float:
            g = self.geom[side]
            return (g.inner + self.lanes[side].used() * g.lane_height) / g.space if g.space > 0 else 1.0

        # Less of its width used wins; then the side with more space; then above.
        return min(tied, key=lambda s: (used_fraction(s), -self.geom[s].space, s is not Side.ABOVE))

    # -- phase A: bars -------------------------------------------------------------------------------------------

    def phase_a(self) -> None:
        banded = [e for e in self.doc.walk() if e.kind.is_banded and e.order in self.extent]
        for e in self.ordered(banded):
            self.place_bar(e)

    def place_bar(self, e: Entity) -> None:
        if e.order in self.bars or e.order in self.failed:
            return
        side = self.inherited_side(e)
        x0, x1, clipped_start, clipped_end = self.extent[e.order]
        st = self.style
        text = self.text(e.font, e.font_size_mm, e.label)
        label_x = self.bar_label_x(e, text, x0, x1)
        occupied = (min(x0, label_x + text.x0), max(x1, label_x + text.x1))
        candidates = [side] if side is not None else [Side.ABOVE, Side.BELOW]
        options = {s: lane for s in candidates if (lane := self.lanes[s].find(*occupied, st.lane_gap)) is not None}
        if not options:
            self.failed.add(e.order)
            where = f"the {side.value} side" if side else "either side"
            capacity = " and ".join(f"{self.geom[s].capacity} {s.value}" for s in candidates)
            self.sink.error(
                "no-room",
                f'no room for {e.kind.value} "{e.label}" on {where}: every lane is taken where it falls '
                f"({capacity} lanes in all)",
                e.location,
            )
            return
        side = self.choose_side({s: float(lane) for s, lane in options.items()})
        lane = options[side]
        self.lanes[side].add(lane, 1, *occupied, f"bar:{e.order}")
        bar = _Bar(e, side, lane, x0, x1, e.when.is_open, clipped_start, clipped_end, text, label_x, None, occupied)
        self.bars[e.order] = bar
        self.check_label_fits(bar)
        if e.illustration is not None:
            bar.illustration = self.place_bar_illustration(bar)

    def bar_label_x(self, e: Entity, text: _Text, x0: float, x1: float) -> float:
        """Just inside the bar's start; or, if that runs off the far end, ending just inside its end (§7)."""
        inset = self.style.label_inset
        x = x0 + inset - text.x0
        if x + text.x1 > self.length:
            x = x1 - inset - text.x1
            if x + text.x0 < 0:
                x = -text.x0
                self.sink.warning(
                    "off-paper",
                    f'the label of {e.kind.value} "{e.label}" is longer than the paper and runs off its end',
                    e.location,
                )
        return x

    def check_label_fits(self, bar: _Bar) -> None:
        g = self.geom[bar.side]
        f = bar.text.shaped.font
        needed = (f.ascender - f.descender) * bar.text.shaped.scale
        room = g.lane_height - 2 * self.style.bar_inset - 2 * self.style.label_margin
        if needed > room:
            e = bar.entity
            self.sink.warning(
                "label-too-tall",
                f'the {format_number(e.font_size_mm)}mm label of {e.kind.value} "{e.label}" needs '
                f"{format_number(needed, 1)}mm but its {format_number(g.lane_height)}mm lane leaves "
                f"{format_number(room, 1)}mm",
                e.location,
            )

    def illustration_size(self, ill: Illustration, side: Side) -> tuple[float, float, int]:
        lane = self.geom[side].lane_height
        height = ill.height_mm if ill.height_mm is not None else 2 * lane
        return height * ill.aspect_ratio, height, max(1, math.ceil(height / lane - 1e-9))

    def place_bar_illustration(self, bar: _Bar) -> _Illustration | None:
        """Left edge on the bar's start, in the nearest free band outward from the bar's lane (§3.5)."""
        e = bar.entity
        width, height, lanes = self.illustration_size(e.illustration, bar.side)
        x0 = self.inside(bar.x0, width, e)
        lane = self.lanes[bar.side].find(x0, x0 + width, self.style.lane_gap, lanes, start=bar.lane + 1)
        if lane is None:
            self.no_room_for_illustration(e, bar.side, lanes)
            return None
        return self.reserve_illustration(e, bar.side, lane, lanes, x0, width, height)

    def inside(self, x0: float, width: float, e: Entity) -> float:
        """Shift a width starting at x0 inward so it stays on the paper (§4.1)."""
        if x0 + width > self.length:
            x0 = self.length - width
        if x0 < 0:
            x0 = 0.0
            self.sink.warning(
                "off-paper", f'the illustration of {e.kind.value} "{e.label}" is wider than the paper', e.location
            )
        return x0

    def no_room_for_illustration(self, e: Entity, side: Side, lanes: int) -> None:
        self.sink.error(
            "no-room-for-illustration",
            f'no room for the illustration of {e.kind.value} "{e.label}": it needs {lanes} free lanes together '
            f"on the {side.value} side and none are left where it falls",
            e.location,
        )

    def reserve_illustration(self, owner, side, lane, lanes, x0, width, height) -> _Illustration:
        ill = _Illustration(owner.illustration, owner, side, lane, lanes, x0, width, height, self.band(side, lane)[0])
        self.lanes[side].add(lane, lanes, x0, x0 + width, ill.key)
        self.ills.append(ill)
        return ill

    # -- phase B: events -------------------------------------------------------------------------------------

    def phase_b(self) -> None:
        events = [e for e in self.doc.walk() if e.kind is Kind.EVENT and e.order in self.extent]
        for e in self.ordered(events):
            self.place_event(e)
        self.events.sort(key=lambda ev: ev.entity.order)

    def flag(self, e: Entity) -> _Flag:
        name = self.text(e.font, e.font_size_mm, e.label)
        if e.time_label is TimeLabel.NONE:
            return _Flag(name, None, "", self.style.time_label_gap)
        words = time_label_text(e.when, e.time_label.value)
        time = self.text(e.font, e.font_size_mm * self.style.time_label_scale, words)
        return _Flag(name, time, words, self.style.time_label_gap)

    def base_pole(self, e: Entity, side: Side, x: float, text: _Flag) -> float:
        """§8.1: clear every higher-priority bar on this side that the event's position falls within."""
        clearance = self.style.flag_clearance + text.height
        outer = [
            self.band(side, bar.lane)[1] - self.style.bar_inset
            for bar in self.bars.values()
            if bar.side is side and bar.entity.priority > e.priority and bar.occupied[0] <= x <= bar.occupied[1]
        ]
        return (max(outer) if outer else self.geom[side].inner) + clearance

    def place_event(self, e: Entity) -> None:
        (x,) = self.extent[e.order]
        side = self.inherited_side(e)
        text = self.flag(e)
        candidates = [side] if side is not None else [Side.ABOVE, Side.BELOW]
        bases = {s: self.base_pole(e, s, x, text) for s in candidates}
        fitting = {s: b for s, b in bases.items() if b <= self.geom[s].space}
        if not fitting:
            where = f"on the {side.value} side" if side else "on either side"
            needs = ", ".join(f"{format_number(b, 1)}mm {s.value}" for s, b in bases.items())
            room = ", ".join(f"{format_number(self.geom[s].space, 1)}mm {s.value}" for s in bases)
            self.sink.error(
                "pole-does-not-fit",
                f'the pole of event "{e.label}" doesn\'t fit {where}: it needs {needs} but there is {room}',
                e.location,
            )
            return
        side = self.choose_side(fitting)
        direction = self.default_direction(e, x, text)
        ev = _Event(e, side, x, text, bases[side], bases[side], direction, direction)
        self.events.append(ev)
        if e.illustration is not None:
            ev.illustration = self.place_event_illustration(ev)

    def flag_fits(self, x: float, text: _Flag, direction: FlagDirection) -> bool:
        x0 = x + self.style.flag_gap if direction is FlagDirection.RIGHT else x - self.style.flag_gap - text.width
        return x0 >= 0 and x0 + text.width <= self.length

    def default_direction(self, e: Entity, x: float, text: _Flag) -> FlagDirection:
        """Towards later dates, unless that runs off the far end of the paper (§8.2, §4.1)."""
        for direction in (FlagDirection.RIGHT, FlagDirection.LEFT):
            if self.flag_fits(x, text, direction):
                return direction
        self.sink.warning(
            "off-paper", f'the flag of event "{e.label}" is too long to fit on the paper either way', e.location
        )
        room_right, room_left = self.length - x, x
        return FlagDirection.RIGHT if room_right >= room_left else FlagDirection.LEFT

    def place_event_illustration(self, ev: _Event) -> _Illustration | None:
        """Beside the pole, on whichever side its band can sit lower; a tie goes left, clear of the flag."""
        e = ev.entity
        width, height, lanes = self.illustration_size(e.illustration, ev.side)
        gap = self.style.illustration_gap
        found = {}
        for x0 in (ev.x - gap - width, ev.x + gap):  # left, then right
            if x0 >= 0 and x0 + width <= self.length:
                lane = self.lanes[ev.side].find(x0, x0 + width, self.style.lane_gap, lanes)
                if lane is not None:
                    found[x0] = lane
        if not found:
            self.no_room_for_illustration(e, ev.side, lanes)
            return None
        x0 = min(found, key=lambda k: (found[k], k > ev.x))
        return self.reserve_illustration(e, ev.side, found[x0], lanes, x0, width, height)

    # -- illustrations in a pole's path ---------------------------------------------------------------------

    def nudge(self, warn: bool) -> None:
        """Move each illustration a pole would cross the least distance sideways to a free spot (§3.5, §8.1)."""
        gap, lane_gap = self.style.illustration_gap, self.style.lane_gap
        for ill in self.ills:
            poles = [
                ev.x for ev in self.events if ev.side is ill.side and ev.entity is not ill.owner and ev.length > ill.d_in
            ]

            def blocked(x0: float, width: float = ill.width, poles: list[float] = poles) -> bool:
                return any(x0 - gap < px < x0 + width + gap for px in poles)

            if not blocked(ill.x0):
                continue
            lanes = self.lanes[ill.side]
            band = [item for i in range(ill.lane, ill.lane + ill.lanes) for item in lanes.items[i] if item[2] != ill.key]
            candidates = {px + gap for px in poles} | {px - gap - ill.width for px in poles}
            candidates |= {b + lane_gap for _, b, _ in band} | {a - lane_gap - ill.width for a, _, _ in band}
            valid = [
                c
                for c in sorted(candidates)
                if c >= 0
                and c + ill.width <= self.length
                and not blocked(c)
                and all(lanes.free(i, c, c + ill.width, lane_gap, ill.key) for i in range(ill.lane, ill.lane + ill.lanes))
            ]
            left = max((c for c in valid if c < ill.x0), default=None)
            right = min((c for c in valid if c > ill.x0), default=None)
            if left is None and right is None:
                if warn:
                    self.sink.warning(
                        "illustration-crossed",
                        f'an event pole crosses the illustration of {ill.owner.kind.value} "{ill.owner.label}" '
                        "and there is no free place to move it, so the pole is broken where it passes",
                        ill.owner.location,
                    )
                continue
            if left is None or right is None:
                target = left if right is None else right
            else:
                room_left = ill.x0 - max([b for _, b, _ in band if b <= ill.x0] + [0.0])
                room_right = min([a for a, _, _ in band if a >= ill.x1] + [self.length]) - ill.x1
                # The direction with more free space; then the smaller move; then left.
                target = min(
                    (left, right),
                    key=lambda c: (-(room_left if c < ill.x0 else room_right), abs(c - ill.x0), c > ill.x0),
                )
            lanes.remove(ill.key)
            lanes.add(ill.lane, ill.lanes, target, target + ill.width, ill.key)
            ill.x0 = target
            self.obstacle_cache.clear()

    # -- phase C: flags --------------------------------------------------------------------------------------

    def flag_box(self, ev: _Event, length: float | None = None, direction: FlagDirection | None = None) -> Box:
        length = ev.length if length is None else length
        direction = direction or ev.direction
        w, h = ev.text.width, ev.text.height
        x0 = ev.x + self.style.flag_gap if direction is FlagDirection.RIGHT else ev.x - self.style.flag_gap - w
        top = self.baseline - length if ev.side is Side.ABOVE else self.baseline + length - h
        return Box(x0, top, x0 + w, top + h)

    def distance_range(self, side: Side, box: Box) -> tuple[float, float]:
        if side is Side.ABOVE:
            return self.baseline - box.y1, self.baseline - box.y0
        return box.y0 - self.baseline, box.y1 - self.baseline

    def obstacles(self, side: Side) -> list[tuple[Box, str]]:
        """Bars, bar labels and illustrations: fixed obstacles that event flags must clear (§8.2)."""
        if side in self.obstacle_cache:
            return self.obstacle_cache[side]
        out = self.obstacle_cache[side] = []
        for bar in self.bars.values():
            if bar.side is side:
                name = f'{bar.entity.kind.value} "{bar.entity.label}"'
                out.append((self.bar_box(bar), name))
                out.append((self.bar_label(bar).box, f"the label of {name}"))
        for ill in self.ills:
            if ill.side is side:
                out.append((self.illustration_box(ill), f'the illustration of {ill.owner.kind.value} "{ill.owner.label}"'))
        return out

    def conflicts(self) -> list[tuple[_Event, _Event | str, float]]:
        """Every collision involving a flag: with another flag, another event's pole, or a fixed obstacle."""
        pad = self.style.collision_pad
        found = []
        for side in (Side.ABOVE, Side.BELOW):
            evs = [ev for ev in self.events if ev.side is side]
            boxes = {id(ev): self.flag_box(ev).padded(pad) for ev in evs}
            obstacles = self.obstacles(side)
            for i, a in enumerate(evs):
                box = boxes[id(a)]
                for b in evs[i + 1 :]:
                    area = box.overlap_area(boxes[id(b)])
                    if area > 0:
                        found.append((a, b, area))
                for b in evs:
                    # b's pole runs through a's flag: a vertical line through text is an ink collision too
                    if b is not a and box.x0 < b.x < box.x1 and b.length > self.distance_range(side, box)[0]:
                        found.append((a, b, box.height))
                for obstacle, name in obstacles:
                    area = box.overlap_area(obstacle)
                    if area > 0:
                        found.append((a, name, area))
        return found

    def phase_c(self) -> None:
        """§8.2: stagger by priority, then flip, then accept the best separation found."""
        order = {id(ev): ev.entity.order for ev in self.events}
        parent = {id(ev): id(ev) for ev in self.events}

        def find(k: int) -> int:
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        done: dict[int, frozenset[int]] = {}
        for _ in range(len(self.events) + 1):
            conflicts = self.conflicts()
            for a, b, _ in conflicts:
                if isinstance(b, _Event):
                    ra, rb = find(id(a)), find(id(b))
                    if ra != rb:
                        parent[max(ra, rb, key=order.get)] = min(ra, rb, key=order.get)
            involved = {find(id(a)) for a, _, _ in conflicts}
            clusters = {}
            for ev in self.events:
                root = find(id(ev))
                if root in involved:
                    clusters.setdefault(root, []).append(ev)
            todo = [
                members
                for root, members in clusters.items()
                if done.get(root) != frozenset(id(ev) for ev in members)
            ]
            if not todo:
                return
            for members in sorted(todo, key=lambda m: min(ev.entity.order for ev in m)):
                self.resolve_cluster(members)
                done[find(id(members[0]))] = frozenset(id(ev) for ev in members)

    def resolve_cluster(self, members: list[_Event]) -> None:
        members = sorted(members, key=lambda ev: self.key(ev.entity))  # highest priority first
        ids = {id(ev) for ev in members}
        for ev in members:
            ev.length, ev.direction = ev.floor, ev.default_direction
        self.stagger(members)

        def score() -> tuple[int, float]:
            mine = [c for c in self.conflicts() if id(c[0]) in ids or (isinstance(c[1], _Event) and id(c[1]) in ids)]
            return len(mine), sum(c[2] for c in mine)

        best = (score(), [(ev.length, ev.direction) for ev in members])
        if best[0][0] == 0:
            return
        for ev in reversed(members):  # lowest priority first
            flipped = FlagDirection.LEFT if ev.direction is FlagDirection.RIGHT else FlagDirection.RIGHT
            if not self.flag_fits(ev.x, ev.text, flipped):
                continue  # never point a flag off the paper (§4.1)
            ev.direction = flipped
            for other in members:
                other.length = other.floor
            self.stagger(members)
            current = score()
            if current < best[0]:
                best = (current, [(m.length, m.direction) for m in members])
            if current[0] == 0:
                return
        for ev, (length, direction) in zip(members, best[1], strict=True):
            ev.length, ev.direction = length, direction

    def stagger(self, members: list[_Event]) -> None:
        """Highest priority tallest; each step down at least one flag height; never below its own floor; lifted
        clear of fixed obstacles; never beyond the paper's edge."""
        st = self.style
        clear = st.stagger_gap + 2 * st.collision_pad  # so stacked flags don't count as touching
        for _ in range(4 * len(members) + 4):
            changed = False
            below: _Event | None = None
            for ev in reversed(members):  # from the lowest priority outward
                need = ev.length
                if below is not None:
                    need = max(need, below.length + ev.text.height + clear)
                need = max(need, self.obstacle_lift(ev, need))
                need = min(need, self.geom[ev.side].space)
                if need > ev.length + 1e-9:
                    ev.length = need
                    changed = True
                below = ev
            if not changed:
                return

    def obstacle_lift(self, ev: _Event, length: float) -> float:
        """The pole length that lifts this flag clear of any fixed obstacle it overlaps."""
        pad = self.style.collision_pad
        box = self.flag_box(ev, length).padded(pad)
        lift = length
        for obstacle, _ in self.obstacles(ev.side):
            if box.overlaps(obstacle):
                outer = self.distance_range(ev.side, obstacle)[1]
                lift = max(lift, outer + 2 * pad + ev.text.height)
        return lift

    def report_collisions(self) -> None:
        conflicts = self.conflicts()
        groups: dict[int, set[str]] = {}
        names = {id(ev): f'"{ev.entity.label}"' for ev in self.events}
        parent = {id(ev): id(ev) for ev in self.events}

        def find(k: int) -> int:
            while parent[k] != k:
                k = parent[k]
            return k

        for a, b, _ in conflicts:
            if isinstance(b, _Event):
                parent[find(id(b))] = find(id(a))
        for a, b, _ in conflicts:
            groups.setdefault(find(id(a)), set()).add(names[id(a)])
            groups[find(id(a))].add(names[id(b)] if isinstance(b, _Event) else b)
        for ev in self.events:
            if id(ev) in groups:
                parts = sorted(groups[id(ev)])
                self.sink.warning(
                    "label-collision",
                    "couldn't fully separate the event labels around " + ", ".join(parts) + "; drawing them as close "
                    "as they will go",
                    ev.entity.location,
                )

    # -- ticks -------------------------------------------------------------------------------------------------

    def ticks(self) -> tuple[Tick, ...]:
        self.tick_interval = self.tick_label_interval = None
        if self.t.ticks_mm is None:
            return ()
        st = self.style
        measure_cache: dict[str, _Text] = {}

        def text_for(label: str) -> _Text:
            if label not in measure_cache:
                measure_cache[label] = self.text(self.t.font, self.tick_size, label)
            return measure_cache[label]

        plan = plan_ticks(
            self.t0, self.t1, self.x, self.length, self.mm_per_second, self.t.ticks_mm, self.t.tick_label_every,
            lambda s: text_for(s).width, st.tick_label_spacing,
        )
        self.tick_interval = str(plan.rung)
        self.tick_label_interval = str(plan.label_rung) if plan.label_rung else None
        if plan.coarsened:
            self.sink.warning(
                "tick-labels-coarsened",
                f"tick labels are every {plan.label_rung or 'none'} so their text doesn't overlap "
                f"(ticks every {plan.rung})",
                self.t.location,
            )
        if plan.crowded:
            self.sink.warning(
                "tick-labels-overlap",
                f"with tick_label_every={self.t.tick_label_every}, neighbouring tick labels overlap",
                self.t.location,
            )
        out = []
        for mark in plan.marks:
            label = None
            if mark.label is not None:
                text = text_for(mark.label)
                top = self.baseline + st.major_tick + st.tick_label_gap
                label = text.placed(mark.label, mark.label_x0 - text.x0, top - text.y0)
            out.append(Tick(mark.seconds, mark.x, st.major_tick if mark.major else st.minor_tick, label))
        return tuple(out)

    # -- assembling the result -------------------------------------------------------------------------------

    def bar_box(self, bar: _Bar) -> Box:
        """The bar's rectangle: its lane, less the inset top and bottom."""
        d_in, d_out = self.band(bar.side, bar.lane)
        ys = sorted((self.y(bar.side, d_in + self.style.bar_inset), self.y(bar.side, d_out - self.style.bar_inset)))
        return Box(bar.x0, ys[0], bar.x1, ys[1])

    def bar_label(self, bar: _Bar) -> PlacedText:
        d_in, d_out = self.band(bar.side, bar.lane)
        y_mid = self.y(bar.side, (d_in + d_out) / 2)
        y = y_mid + bar.text.shaped.cap_height / 2  # the capitals are centred in the lane
        return bar.text.placed(bar.entity.label, bar.label_x, y)

    def illustration_box(self, ill: _Illustration) -> Box:
        ys = sorted((self.y(ill.side, ill.d_in), self.y(ill.side, ill.d_in + ill.height)))
        return Box(ill.x0, ys[0], ill.x1, ys[1])

    def placed_illustration(self, ill: _Illustration | None) -> PlacedIllustration | None:
        if ill is None:
            return None
        return PlacedIllustration(ill.illustration, ill.owner, ill.side, ill.lane, ill.lanes, self.illustration_box(ill))

    def pole_segments(
        self, ev: _Event, flag_boxes: dict[int, Box], bars: list[PlacedBar], ticks: tuple[Tick, ...]
    ) -> tuple[tuple[float, float], ...]:
        """The pole, broken wherever it would cross other ink: bars, bar labels, illustrations, tick labels and
        other flags (§8). The stretch beside its own flag is never broken, so the flag stays attached."""
        st = self.style
        keep_from = max(ev.length - ev.text.height, 0.0)
        blocks = []

        def block(box: Box) -> None:
            if box.x0 - st.pole_gap < ev.x < box.x1 + st.pole_gap:
                d0, d1 = self.distance_range(ev.side, box)
                blocks.append((d0 - st.pole_gap, d1 + st.pole_gap))

        for bar in bars:
            if bar.side is ev.side:
                block(Box(bar.x0, bar.y0, bar.x1, bar.y1))
                block(bar.label.box)
        for ill in self.ills:
            if ill.side is ev.side:
                block(self.illustration_box(ill))
        if ev.side is Side.BELOW:
            for tick in ticks:
                if tick.label:
                    block(tick.label.box)
        for other in self.events:
            if other is not ev and other.side is ev.side:
                block(flag_boxes[id(other)])
        pieces = []
        pos = 0.0
        for d0, d1 in sorted(blocks):
            if pos >= keep_from:
                break
            if d0 > pos:
                pieces.append((pos, min(d0, keep_from)))
            pos = max(pos, d1)
        if pos < keep_from:
            pieces.append((pos, keep_from))
        pieces = [(a, b) for a, b in pieces if b - a >= st.min_pole_segment]
        if pieces and pieces[-1][1] == keep_from:
            pieces[-1] = (pieces[-1][0], ev.length)
        else:
            pieces.append((keep_from, ev.length))
        return tuple((self.y(ev.side, a), self.y(ev.side, b)) for a, b in pieces)

    def result(self, ticks: tuple[Tick, ...]) -> ResolvedLayout:
        bars = []
        for order in sorted(self.bars):
            bar = self.bars[order]
            box = self.bar_box(bar)
            bars.append(
                PlacedBar(
                    bar.entity, bar.side, bar.lane, bar.x0, bar.x1, box.y0, box.y1, bar.open_end, bar.clipped_start,
                    bar.clipped_end, self.bar_label(bar), self.placed_illustration(bar.illustration),
                )
            )
        events = []
        flag_boxes = {id(ev): self.flag_box(ev) for ev in self.events}
        for ev in self.events:
            box = flag_boxes[id(ev)]
            flag, time_label = ev.text.placed(ev.entity.label, box, ev.direction)
            events.append(
                PlacedEvent(
                    ev.entity, ev.side, ev.x, ev.length, ev.floor, self.y(ev.side, ev.length),
                    self.pole_segments(ev, flag_boxes, bars, ticks), ev.direction, flag, time_label, box,
                    self.placed_illustration(ev.illustration),
                )
            )
        used = {e.entity.pen for e in bars} | {e.entity.pen for e in events} | {AXIS_PEN}
        pens = (AXIS_PEN,) + tuple(p for p in PENS if p in used and p != AXIS_PEN)
        summaries = {
            side: SideSummary(side, g.space, g.inner, g.lane_height, g.capacity, self.lanes[side].used())
            for side, g in self.geom.items()
        }
        return ResolvedLayout(
            document=self.doc,
            width_mm=self.t.width_mm,
            length_mm=self.length,
            baseline_y=self.baseline,
            start_seconds=self.t0,
            end_seconds=self.t1,
            scale=self.scale,
            scale_derived=self.scale_derived,
            now=self.now,
            above=summaries[Side.ABOVE],
            below=summaries[Side.BELOW],
            bars=tuple(bars),
            events=tuple(events),
            ticks=ticks,
            tick_interval=self.tick_interval,
            tick_label_interval=self.tick_label_interval,
            axis_pen=AXIS_PEN,
            pens=pens,
            omitted=tuple(self.omitted),
            diagnostics=tuple(self.sink.items),
        )


def _readable_scale(mm_per_second: float, span_seconds: int) -> Scale:
    """A derived scale in the largest unit that the timeline spans at least two of."""
    for unit in ("year", "day", "hour", "minute"):
        if span_seconds >= 2 * SECONDS_PER_UNIT[unit]:
            return Scale(mm_per_second * SECONDS_PER_UNIT[unit], unit)
    return Scale(mm_per_second, "second")
