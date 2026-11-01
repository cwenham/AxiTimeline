"""``parse(source, resolve) -> ParseResult``: the first stage, and the only one that calls host I/O.

Flattens includes (preprocess), runs the grammar once over the flattened text, then builds the AST: checking
dates, pens and parameters, resolving inheritance that is purely textual (pen, font, font size), dropping
duplicate entities (last definition wins, §5), and loading every font, illustration and graph data file the
document uses, so a graph's points are read and checked here (§15).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace

from lark import Token, Tree
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken

from . import grammar, graphdata
from .colours import WHITE, ColourError, nearest_pen, parse_colour
from .dates import DateError, DateRange, DateValue, parse_date, parse_when, time_label_text
from .diagnostics import AxitlError, Diagnostic, Diagnostics, SourceLocation
from .fetch import Fetcher, Resolver, Resource, no_resolver, relative_name
from .fonts import BUILTIN_FONTS, DEFAULT_FONT, Font, FontError, font_variant, load_builtin_font, parse_svg_font
from .illustrate import illustration_colours
from .illustration import IllustrationError, intrinsic_size
from .model import (
    Baseline,
    CreditLine,
    Credits,
    Edge,
    Entity,
    Fill,
    Graph,
    Horizontal,
    Illustration,
    Kind,
    LineMode,
    Note,
    NoteAnchor,
    NoteParagraph,
    OpenEndStyle,
    Side,
    TimeLabel,
    TimelineDocument,
    TimelineSettings,
    Title,
    ValueScaleMode,
    YScale,
)
from .pens import DEFAULT_PEN, is_pen, suggest_pen
from .preprocess import Flattener, LogicalLine, unescape
from .markup import parse_inline, plain_text
from .text import drawable_text
from .units import UnitError, parse_length, parse_scale

_HEAD = re.compile(r"^([\^v]?)([!\-]*)(person|event|span|group)$")

DEFAULT_FONT_SIZE_MM = 4.0
DEFAULT_LANE_HEIGHT_MM = 8.0
DEFAULT_BASELINE_OFFSET_MM = 3.0
DEFAULT_TICKS_MM = 3.5

_TIMELINE_KEYS = (
    "start", "end", "length", "scale", "width", "baseline",
    "lane_height", "above_lane_height", "below_lane_height",
    "baseline_offset", "above_baseline_offset", "below_baseline_offset",
    "ticks", "tick_label_every", "open_end_style", "font", "font_size", "time_label",
)
_ENTITY_KEYS = ("fill", "fill_pen", "font", "font_size", "time_label")
_GRAPH_KEYS = (
    "data", "first_row", "last_row", "header", "separator", "time_column", "value_column", "time_format", "missing",
    "origin", "y_scale", "height", "range", "line", "fill", "fill_pen", "fill_depth", "shadow", "value_scale",
    "value_marks", "unit", "font", "font_size",
)
_CSV_KEYS = ("first_row", "last_row", "header", "separator", "time_column", "value_column", "time_format")
_TITLE_KEYS = (
    "font", "font_size", "font_fill", "subtitle", "subtitle_font", "subtitle_font_size", "subtitle_font_fill", "align",
    "margin", "gap",
)
_CREDITS_KEYS = ("font", "font_size", "heading_font", "heading_font_size", "max_height", "align", "margin", "gap")
_NOTE_KEYS = (
    "anchor", "edge", "width", "align", "font", "font_size", "heading_font", "heading_font_size", "margin",
    "clearance", "gap",
)
_ILLUSTRATION_KEYS = ("height", "fill", "pens")  # inside an entity's illustration( ... )
_TITLE_ILLUSTRATION_KEYS = ("height", "at", "fill", "pens")
_CREDITS_ILLUSTRATION_KEYS = ("at", "fill", "pens")  # as tall as the credits' lines, always
_NOTE_ILLUSTRATION_KEYS = ("at", "fill", "pens")  # as tall as the note's text, always
_UNCLOSED_GROUP = "this group's { body is never closed with }"
_UNCLOSED_GRAPH = "this graph's { body of points is never closed with }"
_UNCLOSED_CREDITS = "the credits' { body of lines is never closed with }"
_UNCLOSED_NOTE = "this note's { body of paragraphs is never closed with }"
DEFAULT_GRAPH_PEN = "HB-pencil"
# The title and credits (§16).
DEFAULT_TITLE_SIZE_MM = 12.0
SUBTITLE_SCALE = 0.5  # a subtitle's size, as a fraction of the title's
HEADING_SCALE = 1.25  # a credits heading's size, as a multiple of the credits' font_size
DEFAULT_CORNER_MARGIN_MM = 5.0  # from the finished edges, clear of the crop mark in the corner
DEFAULT_CORNER_GAP_MM = 4.0  # between an illustration and the text beside it
# Notes (§17).
DEFAULT_NOTE_MARGIN_MM = 5.0  # from the finished edge and the ends of the paper, clear of the crop marks
DEFAULT_NOTE_CLEARANCE_MM = 25.0  # along the roll, from the title, the credits and other notes


@dataclass(frozen=True)
class ParseResult:
    document: TimelineDocument
    flattened_text: str  # exactly what the grammar parsed; the job hash covers this
    resources: tuple[Resource, ...]  # everything fetched through resolve, in first-use order
    diagnostics: tuple[Diagnostic, ...]  # warnings (a parse with errors raises AxitlError instead)


def parse(source: str, resolve: Resolver | None = None, source_name: str = "main.axitl") -> ParseResult:
    """Parse ``.axitl`` source.

    ``resolve(name)`` fetches includes, illustrations, custom fonts and graph data; names are relative to the
    same root as ``source_name``. Raises :class:`AxitlError`, carrying every diagnostic found, if the source has errors.
    """
    sink = Diagnostics()
    fetcher = Fetcher(resolve or no_resolver, sink)
    lines = Flattener(fetcher, sink).flatten(source, source_name)
    sink.raise_if_errors()
    text = "".join(line.text + "\n" for line in lines)
    try:
        tree = grammar.parser().parse(text)
    except UnexpectedInput as exc:
        line = exc.line if isinstance(exc.line, int) and 1 <= exc.line <= len(lines) else len(lines)
        location = lines[line - 1].location if lines else SourceLocation(source_name, 1)
        message = _syntax_message(exc, text)
        if message == _UNCLOSED_GROUP:
            opener = _unclosed_body(lines)
            if opener is not None:
                location = opener.location
                if opener.text.startswith("graph"):
                    message = _UNCLOSED_GRAPH
                elif opener.text.startswith("credits"):
                    message = _UNCLOSED_CREDITS
                elif opener.text.startswith("note"):
                    message = _UNCLOSED_NOTE
        elif message.startswith("a timeline declaration can't") and 1 <= line <= len(lines):
            if lines[line - 1].text.startswith("title"):
                message = "a title can't have a { } body; give its second line as subtitle=\"...\""
        sink.error("syntax", message, location)
        raise AxitlError(sink.items) from None
    document = _Builder(lines, fetcher, sink, source_name).build(tree)
    sink.raise_if_errors()
    assert document is not None
    return ParseResult(document, text, tuple(fetcher.resources), tuple(sink.items))


def _syntax_message(exc: UnexpectedInput, text: str) -> str:
    expected = set(getattr(exc, "expected", None) or getattr(exc, "allowed", None) or ())
    if isinstance(exc, UnexpectedToken):
        token = exc.token
        found = "the end of the file" if token.type == "$END" else f"'{token}'"
        if token.type == "$END" and "RBRACE" in expected:
            return _UNCLOSED_GROUP
    elif isinstance(exc, UnexpectedCharacters):
        found = f"'{exc.char}'"
    else:
        found = "something unexpected"
    if "HEADING" in expected:
        return (
            f"{found} can't start a line of the credits or a note; each line is a quoted string, or heading and a "
            'quoted string: heading "Sources"'
        )
    if "HEAD" in expected or "TIMELINE" in expected:
        if found == "'}'":
            return "this } has no group { to close"
        return (
            f"{found} doesn't start a declaration; a line starts with timeline, person, event, span, group, "
            "graph, title, credits or note (with optional ^/v side and !/- priority marks before an entity's keyword)"
        )
    if expected == {"STRING"}:
        return f'expected a quoted label, e.g. "Isaac Newton", but found {found}'
    if "RPAR" in expected:
        return "illustration( is missing its closing )"
    if found == "'='":
        return "found '=' with no parameter name before it"
    if found == "'{'":
        return "a timeline declaration can't have a { } body"
    return f"unexpected {found}"


class _Builder:
    def __init__(self, lines: list[LogicalLine], fetcher: Fetcher, sink: Diagnostics, source_name: str):
        self.lines = lines
        self.fetcher = fetcher
        self.sink = sink
        self.source_name = source_name
        self.fonts: dict[str, Font] = {}
        self.order = 0
        self.graph_count = 0

    # -- helpers ------------------------------------------------------------------------------------------

    def loc(self, node: Tree | Token) -> SourceLocation:
        line = node.line if isinstance(node, Token) else node.meta.line
        return self.lines[line - 1].location

    def glued(self, node: Tree) -> bool:
        return self.lines[node.meta.line - 1].glued_comment

    @staticmethod
    def value(token: Token) -> str:
        return unescape(token[1:-1]) if token.type == "STRING" else str(token)

    def length(self, key: str, text: str, location: SourceLocation, positive: bool = True) -> float | None:
        try:
            mm = parse_length(text)
        except UnitError as exc:
            self.sink.error("bad-value", f"{key}=: {exc}", location)
            return None
        if positive and mm <= 0:
            self.sink.error("bad-value", f"{key}= must be more than zero", location)
            return None
        return mm

    def params(
        self, nodes: list[Tree], allowed: tuple[str, ...], where: str, hints: dict[str, str] | None = None
    ) -> dict[str, tuple[str, SourceLocation]]:
        found: dict[str, tuple[str, SourceLocation]] = {}
        for node in nodes:
            key_token, value_token = node.children
            key, location = str(key_token), self.loc(node)
            if key not in allowed:
                hint = difflib.get_close_matches(key, allowed, n=1)
                extra = f"; did you mean {hint[0]}=?" if hint else ""
                if hints and key in hints:
                    extra = f"; {hints[key]}"
                elif where != "timeline" and key in ("side", "priority"):
                    extra = "; set an entity's side with a ^ or v prefix and its priority with ! or - marks"
                self.sink.error("unknown-parameter", f"{where} has no {key}= parameter{extra}", location)
                continue
            if key in found:
                self.sink.error("duplicate-parameter", f"{key}= is given more than once", location)
                continue
            found[key] = (self.value(value_token), location)
        return found

    def font(self, name: str, location: SourceLocation) -> str | None:
        """Load a font reference and return its key in the font table, or None after reporting an error."""
        if name.lower().endswith(".svg"):
            key = relative_name(location.source, name)
            if key not in self.fonts:
                content = self.fetcher.fetch("font", key, location)
                if content is None:
                    return None
                try:
                    self.fonts[key] = parse_svg_font(content, key)
                except FontError as exc:
                    self.sink.error("bad-font", str(exc), location)
                    return None
            return key
        if name not in BUILTIN_FONTS:
            hint = next((f for f in BUILTIN_FONTS if f.lower() == name.lower()), None) or next(
                iter(difflib.get_close_matches(name, BUILTIN_FONTS, n=1)), None
            )
            extra = f"; did you mean {hint}?" if hint else ""
            self.sink.error(
                "unknown-font",
                f"'{name}' is not a built-in font{extra} (a custom font is a file name ending .svg)",
                location,
            )
            return None
        if name not in self.fonts:
            self.fonts[name] = load_builtin_font(name)
        return name

    # -- document -----------------------------------------------------------------------------------------

    def build(self, tree: Tree) -> TimelineDocument | None:
        timelines = [c for c in tree.children if c.data == "timeline"]
        if not timelines:
            first = self.lines[0].location if self.lines else SourceLocation(self.source_name, 1)
            self.sink.error("missing-timeline", "the document has no timeline declaration", first)
        for extra in timelines[1:]:
            self.sink.error("duplicate-timeline", "only one timeline declaration is allowed", self.loc(extra))
        settings = self.timeline(timelines[0]) if timelines else None
        context = (
            DEFAULT_PEN,
            settings.font if settings else DEFAULT_FONT,
            settings.font_size_mm if settings else DEFAULT_FONT_SIZE_MM,
            settings.time_label if settings else TimeLabel.NONE,
            None,  # no fill pen to inherit: a bar's fill is in its own pen unless it says otherwise
        )
        entities = [
            e for c in tree.children if c.data == "entity" if (e := self.entity(c, context, None)) is not None
        ]
        entities = self.drop_duplicates(entities)
        self.check_glyphs(entities)
        graph_context = (
            settings.font if settings else DEFAULT_FONT,
            settings.font_size_mm if settings else DEFAULT_FONT_SIZE_MM,
        )
        graphs = [g for c in tree.children if c.data == "graph" if (g := self.graph(c, graph_context)) is not None]
        graphs = self.drop_duplicate_graphs(graphs)
        for g in graphs:
            if g.font in self.fonts:
                self.warn_missing_glyphs(self.fonts[g.font], g.font, g.title, f'graph "{g.title}"', g.location)
                self.warn_missing_glyphs(self.fonts[g.font], g.font, g.unit, f'the unit of graph "{g.title}"',
                                         g.location)
        title = credits = None
        for kind in ("title", "credits"):
            nodes = [c for c in tree.children if c.data == kind]
            for extra in nodes[1:]:
                self.sink.error(
                    f"duplicate-{kind}",
                    f"only one {kind} declaration is allowed; the first is at {self.loc(nodes[0])}",
                    self.loc(extra),
                )
            if nodes:
                if kind == "title":
                    title = self.title(nodes[0], graph_context)
                else:
                    credits = self.credits(nodes[0], graph_context)
        self.check_corner_glyphs(title, credits)
        notes = []
        for node in (c for c in tree.children if c.data == "note"):
            note = self.note(node, graph_context, len(notes))
            if note is not None:
                notes.append(note)
        if settings is None or self.sink.has_errors:
            return None
        return TimelineDocument(
            settings, tuple(entities), dict(sorted(self.fonts.items())), tuple(graphs), title, credits, tuple(notes)
        )

    def timeline(self, node: Tree) -> TimelineSettings | None:
        location = self.loc(node)
        items = node.children[1:]
        for item in items:
            if item.data != "param":
                what = f"'{item.children[0]}'" if item.data == "bare" else "an illustration"
                self.sink.error(
                    "unexpected-item", f"unexpected {what} in timeline; its settings are all key=value", location
                )
        p = self.params([i for i in items if i.data == "param"], _TIMELINE_KEYS, "timeline")

        def date(key: str) -> DateValue | None:
            text, where = p[key]
            try:
                return parse_date(text)
            except DateError as exc:
                self.sink.error("bad-date", f"{key}=: {exc}", where)
                return None

        for key, reason in (("start", "the first date the timeline shows"), ("end", "a date, or now"),
                            ("width", "the finished width across the roll, e.g. width=210")):
            if key not in p:
                self.sink.error("missing-parameter", f"timeline needs {key}= ({reason})", location)
        start = date("start") if "start" in p else None
        end = None
        if "end" in p and p["end"][0] != "now":
            end = date("end")
            if start and end and end.last_second() < start.first_second():
                self.sink.error("bad-value", "end= is before start=", p["end"][1])
        width = self.length("width", *p["width"]) if "width" in p else None

        length = scale = None
        if "length" in p and "scale" in p:
            self.sink.error("bad-value", "give either length= or scale=, not both", p["scale"][1])
        elif "length" in p:
            length = self.length("length", *p["length"])
        elif "scale" in p:
            try:
                scale = parse_scale(p["scale"][0])
                if scale.mm <= 0:
                    self.sink.error("bad-value", "scale= must be more than zero", p["scale"][1])
            except UnitError as exc:
                self.sink.error("bad-value", f"scale=: {exc}", p["scale"][1])
        else:
            self.sink.error(
                "missing-parameter",
                "timeline needs either length= (the finished length, e.g. length=15m) or scale= (e.g. scale=5mm/year)",
                location,
            )

        def choice(key: str, enum, default):
            if key not in p:
                return default
            text, where = p[key]
            try:
                return enum(text)
            except ValueError:
                options = " or ".join(m.value for m in enum)
                self.sink.error("bad-value", f"{key}= takes {options}, not '{text}'", where)
                return default

        def side_length(key: str, default: float, positive: bool) -> tuple[float, float]:
            shared = self.length(key, *p[key], positive=positive) if key in p else None
            shared = default if shared is None else shared
            above = self.length(f"above_{key}", *p[f"above_{key}"], positive=positive) if f"above_{key}" in p else None
            below = self.length(f"below_{key}", *p[f"below_{key}"], positive=positive) if f"below_{key}" in p else None
            return (shared if above is None else above), (shared if below is None else below)

        lane_above, lane_below = side_length("lane_height", DEFAULT_LANE_HEIGHT_MM, True)
        offset_above, offset_below = side_length("baseline_offset", DEFAULT_BASELINE_OFFSET_MM, False)

        ticks: float | None = DEFAULT_TICKS_MM
        if "ticks" in p:
            ticks = None if p["ticks"][0] == "off" else self.length("ticks", *p["ticks"])
        label_every = None
        if "tick_label_every" in p:
            text, where = p["tick_label_every"]
            if text.isdigit() and int(text) > 0:
                label_every = int(text)
            else:
                self.sink.error("bad-value", f"tick_label_every= takes a whole number above zero, not '{text}'", where)

        font = self.font(*p["font"]) if "font" in p else self.font(DEFAULT_FONT, location)
        font_size = self.length("font_size", *p["font_size"]) if "font_size" in p else DEFAULT_FONT_SIZE_MM
        baseline = choice("baseline", Baseline, Baseline.MIDDLE)
        open_end_style = choice("open_end_style", OpenEndStyle, OpenEndStyle.SAWTOOTH)
        time_label = choice("time_label", TimeLabel, TimeLabel.NONE)

        if start is None or width is None or (length is None and scale is None) or font is None or font_size is None:
            return None
        return TimelineSettings(
            start=start,
            end=end,
            width_mm=width,
            length_mm=length,
            scale=scale,
            baseline=baseline,
            above_lane_height_mm=lane_above,
            below_lane_height_mm=lane_below,
            above_baseline_offset_mm=offset_above,
            below_baseline_offset_mm=offset_below,
            ticks_mm=ticks,
            tick_label_every=label_every,
            open_end_style=open_end_style,
            font=font,
            font_size_mm=font_size,
            time_label=time_label,
            location=location,
        )

    # -- entities -----------------------------------------------------------------------------------------

    def entity(self, node: Tree, context: tuple[str, str, float, TimeLabel, str | None], group: str | None) -> Entity | None:
        location = self.loc(node)
        head, label_token, *items = node.children
        body = items.pop() if items and isinstance(items[-1], Tree) and items[-1].data == "body" else None
        side_mark, run, keyword = _HEAD.match(str(head)).groups()
        kind = Kind(keyword)
        ok = True
        if "!" in run and "-" in run:
            self.sink.error(
                "mixed-priority",
                f"'{run}' mixes ! and - in one priority run; use only ! (towards the baseline) or only - (away from it)",
                location,
            )
            ok = False
        priority = len(run) if run.startswith("!") else -len(run)
        side = {"^": Side.ABOVE, "v": Side.BELOW}.get(side_mark)
        label = self.value(label_token)
        order = self.order
        self.order += 1

        when = None
        if not items or items[0].data != "bare":
            self.sink.error("missing-date", f'{kind.value} "{label}" needs a date straight after its label', location)
            ok = False
        else:
            when = self.when(kind, label, str(items[0].children[0]), node, location)
            ok = ok and when is not None
            items = items[1:]

        pen = None
        illustration = None
        param_nodes = []
        for item in items:
            if item.data == "bare":
                word = str(item.children[0])
                if pen is None and is_pen(word):
                    pen = word
                    continue
                ok = False
                if pen is not None and is_pen(word):
                    self.sink.error("duplicate-pen", f"{kind.value} \"{label}\" has more than one pen", location)
                elif _looks_like_date(word):
                    self.sink.error(
                        "unexpected-item",
                        f"unexpected second date '{word}'; write a range as one item, e.g. 1642-1727",
                        location,
                    )
                else:
                    hint = suggest_pen(word)
                    extra = f"; did you mean {hint}?" if hint else ""
                    self.sink.error("unknown-pen", f"'{word}' is not a pen{extra}", location)
            elif item.data == "param":
                param_nodes.append(item)
            elif illustration is not None:
                self.sink.error("duplicate-illustration", "only one illustration can be attached", location)
                ok = False
            else:
                illustration = self.illustration(item)
                ok = ok and illustration is not None

        p = self.params(param_nodes, _ENTITY_KEYS, kind.value)
        fill = Fill.NONE
        if "fill" in p:
            text, where = p["fill"]
            if not kind.is_banded:
                self.sink.error("bad-value", "fill= applies to person, span and group bars, not events", where)
            else:
                try:
                    fill = Fill(text)
                except ValueError:
                    options = ", ".join(f.value for f in Fill)
                    self.sink.error("bad-value", f"fill= takes one of {options}, not '{text}'", where)
        inherited_pen, inherited_font, inherited_size, inherited_time_label, inherited_fill_pen = context
        fill_pen = None
        if "fill_pen" in p:
            text, where = p["fill_pen"]
            if not kind.is_banded:
                self.sink.error("bad-value", "fill_pen= applies to person, span and group bars, not events", where)
            elif not is_pen(text):
                hint = suggest_pen(text)
                self.sink.error("unknown-pen", f"fill_pen=: '{text}' is not a pen{f'; did you mean {hint}?' if hint else ''}",
                                where)
            elif fill is Fill.NONE and kind is not Kind.GROUP:  # a group may only be passing it on to its members
                self.sink.error("bad-value", "fill_pen= needs a fill= pattern to draw", where)
            else:
                fill_pen = text
        font = self.font(*p["font"]) if "font" in p else inherited_font
        font_size = self.length("font_size", *p["font_size"]) if "font_size" in p else inherited_size
        pen = pen or inherited_pen
        time_label = inherited_time_label
        if "time_label" in p:
            text, where = p["time_label"]
            if kind in (Kind.PERSON, Kind.SPAN):
                self.sink.error(
                    "bad-value",
                    f"time_label= applies to events (set it on a group to give the events inside it one), "
                    f"not {_a(kind.value)}",
                    where,
                )
            else:
                try:
                    time_label = TimeLabel(text)
                except ValueError:
                    options = ", ".join(t.value for t in TimeLabel)
                    self.sink.error("bad-value", f"time_label= takes one of {options}, not '{text}'", where)
        if kind in (Kind.PERSON, Kind.SPAN):
            time_label = TimeLabel.NONE  # bars have no flag, and pass nothing on

        children: list[Entity] = []
        if body is not None:
            if kind is not Kind.GROUP:
                self.sink.error("unexpected-body", f"only a group can have a {{ }} body, not {_a(kind.value)}", location)
                ok = False
            for child in body.children:
                if child.data == "timeline":
                    self.sink.error("nested-timeline", "a timeline declaration can't be inside a group", self.loc(child))
                    continue
                if child.data == "graph":
                    self.sink.error(
                        "nested-graph",
                        "a graph can't be inside a group; declare it at the top level of a file (it can be an "
                        "included file)",
                        self.loc(child),
                    )
                    continue
                if child.data in ("title", "credits", "note"):
                    what = "a note" if child.data == "note" else f"the {child.data}"
                    self.sink.error(
                        f"nested-{child.data}",
                        f"{what} can't be inside a group; declare it at the top level of a file (it can "
                        "be an included file)",
                        self.loc(child),
                    )
                    continue
                inherited = (pen, font or inherited_font, font_size or inherited_size, time_label,
                             fill_pen or inherited_fill_pen)
                built = self.entity(child, inherited, label)
                if built is not None:
                    children.append(built)

        if not ok or font is None or font_size is None:
            return None
        return Entity(
            kind=kind,
            label=label,
            when=when,
            priority=priority,
            side=side,
            pen=pen,
            fill=fill,
            fill_pen=fill_pen or inherited_fill_pen or pen,
            font=font,
            font_size_mm=font_size,
            time_label=time_label,
            illustration=illustration,
            children=tuple(children),
            member_of=group,
            order=order,
            location=location,
        )

    def when(self, kind: Kind, label: str, text: str, node: Tree, location: SourceLocation):
        try:
            when = parse_when(text)
        except DateError as exc:
            self.sink.error("bad-date", str(exc), location)
            return None
        if kind is Kind.EVENT and isinstance(when, DateRange):
            self.sink.error(
                "event-range", f'event "{label}" takes one date, not a range (use a span for a period)', location
            )
            return None
        if kind.is_banded and isinstance(when, DateValue):
            if self.glued(node):
                message = "'//' found where a date range separator was expected; did you mean a single '/'?"
            else:
                message = (
                    f"{_a(kind.value)} needs a date range such as 1642-1727, or an open start such as 1953-, "
                    f"but '{text}' is the single date {when.describe()}"
                )
                if re.fullmatch(r"\d+(?i:bce?)?-\d{2}", text):
                    message += "; for a range of years, write both years in full, e.g. 1910-1912"
            self.sink.error("needs-range", message, location)
            return None
        return when

    def illustration(self, node: Tree) -> Illustration | None:
        """An entity's illustration (§3.5)."""
        hints = {
            "at": "at= places the illustration of a title or the credits; an entity's illustration is placed "
            "automatically (§3.5)",
        }
        return self.attached_illustration(node, _ILLUSTRATION_KEYS, hints, Horizontal.LEFT)[0]

    def horizontal(self, p: dict, key: str, default: Horizontal) -> Horizontal | None:
        """A left or right parameter (at= or align=, §16), or ``default``; None after an error."""
        if key not in p:
            return default
        text, where = p[key]
        try:
            return Horizontal(text)
        except ValueError:
            self.sink.error("bad-value", f"{key}= takes left or right, not '{text}'", where)
            return None

    def attached_illustration(
        self, node: Tree, allowed: tuple[str, ...], hints: dict[str, str], default_at: Horizontal
    ) -> tuple[Illustration | None, Horizontal]:
        """An illustration and which side of its text it goes (at=, for a title or the credits, §16)."""
        location = self.loc(node)
        _, file_token, *param_nodes = node.children
        p = self.params(param_nodes, allowed, "illustration", hints)
        at = self.horizontal(p, "at", default_at)
        if at is None:
            return None, default_at
        height = self.length("height", *p["height"]) if "height" in p else None
        if "height" in p and height is None:
            return None, at
        name = relative_name(location.source, self.value(file_token))
        content = self.fetcher.fetch("illustration", name, location)
        if content is None:
            return None, at
        try:
            width, intrinsic_height = intrinsic_size(content, name)
        except IllustrationError as exc:
            self.sink.error("bad-illustration", str(exc), location)
            return None, at
        fill = Fill.NONE
        if "fill" in p:
            text, where = p["fill"]
            try:
                fill = Fill(text)
            except ValueError:
                options = ", ".join(f.value for f in Fill)
                self.sink.error("bad-value", f"fill= takes one of {options}, not '{text}'", where)
                return None, at
        pens = None
        if "pens" in p:
            pens = self.illustration_pens(name, content, *p["pens"])
            if pens is None:
                return None, at
        return Illustration(name, content, width, intrinsic_height, height, fill, pens), at

    def illustration_pens(self, name: str, content: bytes, text: str, where: SourceLocation):
        """pens= on an illustration (§3.5): auto, or colour:pen pairs. Returns the mapping for every colour it
        settles, sorted by colour; None after an error."""
        colours, unreadable = illustration_colours(content)
        if unreadable:
            self.sink.warning(
                "illustration-colour",
                f"illustration '{name}' has paint that isn't a plain colour (a gradient or pattern), which is drawn "
                "in its owner's pen",
                where,
            )
        if text == "auto":
            return tuple(sorted((c, nearest_pen(c)) for c in colours if c != WHITE))
        mapping: dict[str, str] = {}
        for item in re.split(r"[\s,]+", text.strip()):
            colour_text, colon, pen = item.rpartition(":")
            if not colon or not colour_text:
                self.sink.error(
                    "bad-value",
                    f"pens= takes auto, or colours and pens such as \"#ff6600:orange #000000:black\", not '{item}'",
                    where,
                )
                return None
            try:
                colour = parse_colour(colour_text)
            except ColourError:
                colour = None
            if colour is None:
                self.sink.error("bad-value", f"pens=: '{colour_text}' isn't a colour, such as #ff6600 or black", where)
                return None
            if not is_pen(pen):
                hint = suggest_pen(pen)
                self.sink.error("unknown-pen", f"pens=: '{pen}' is not a pen{f'; did you mean {hint}?' if hint else ''}",
                                where)
                return None
            if colour not in colours:
                self.sink.warning(
                    "illustration-colour", f"pens=: illustration '{name}' doesn't use the colour {colour_text}", where
                )
            mapping[colour] = pen
        return tuple(sorted(mapping.items()))

    # -- title and credits (§16) ----------------------------------------------------------------------------

    def corner_items(self, items: list[Tree], what: str, location: SourceLocation, allowed: tuple[str, ...],
                     hints: dict[str, str], corner: Horizontal):
        """A title's or the credits' items: a pen, an illustration and key=value parameters. ``corner`` is the
        side its corner is on, where its illustration goes unless at= says otherwise."""
        pen = None
        illustration = None
        at = corner
        param_nodes = []
        ok = True
        for item in items:
            if item.data == "param":
                param_nodes.append(item)
            elif item.data == "illustration":
                if illustration is not None:
                    self.sink.error("duplicate-illustration", "only one illustration can be attached", location)
                    ok = False
                    continue
                illustration, at = self.attached_illustration(item, allowed, hints, corner)
                ok = ok and illustration is not None
            else:
                word = str(item.children[0])
                if pen is None and is_pen(word):
                    pen = word
                    continue
                ok = False
                if is_pen(word):
                    self.sink.error("duplicate-pen", f"the {what} has more than one pen", location)
                else:
                    hint = suggest_pen(word)
                    extra = f"; did you mean {hint}?" if hint else ""
                    self.sink.error("unknown-pen", f"'{word}' is not a pen{extra}", location)
        return pen or DEFAULT_PEN, illustration, at, param_nodes, ok

    def corner_length(self, p: dict, key: str, default: float | None, *, positive: bool = True) -> float | None:
        """A length parameter, or ``default``; None after an error (reported) when it was given."""
        if key not in p:
            return default
        mm = self.length(key, *p[key], positive=positive)
        if mm is not None and mm < 0:
            self.sink.error("bad-value", f"{key}= can't be negative", p[key][1])
            return None
        return mm

    def title(self, node: Tree, context: tuple[str, float]) -> Title | None:
        location = self.loc(node)
        _, text_token, *items = node.children
        text = self.value(text_token)
        ok = True
        if not text.strip():
            self.sink.error("bad-value", "the title has no text", location)
            ok = False
        pen, illustration, at, param_nodes, good = self.corner_items(
            items, "title", location, _TITLE_ILLUSTRATION_KEYS,
            {"side": "put it left or right of the text with at=left or at=right"}, Horizontal.LEFT,
        )
        p = self.params(param_nodes, _TITLE_KEYS, "title")
        align = self.horizontal(p, "align", Horizontal.LEFT)
        inherited_font, _ = context
        font = self.font(*p["font"]) if "font" in p else inherited_font
        size = self.corner_length(p, "font_size", DEFAULT_TITLE_SIZE_MM)
        subtitle = p["subtitle"][0] if "subtitle" in p else ""
        for key in ("subtitle_font", "subtitle_font_size", "subtitle_font_fill"):
            if key in p and not subtitle:
                self.sink.error("bad-value", f"{key}= needs a subtitle= to apply to", p[key][1])
                ok = False
        subtitle_font = self.font(*p["subtitle_font"]) if "subtitle_font" in p else font
        subtitle_size = self.corner_length(p, "subtitle_font_size", size * SUBTITLE_SCALE if size else None)
        font_fill = self.letter_fill(p, "font_fill", font, Fill.NONE)
        # A subtitle in an outline font is filled like the title unless it says otherwise; one in a single-line
        # font has nothing to fill.
        outline = bool(subtitle) and subtitle_font is not None and self.fonts[subtitle_font].outline
        subtitle_fill = self.letter_fill(p, "subtitle_font_fill", subtitle_font,
                                         font_fill if outline and font_fill else Fill.NONE)
        margin = self.corner_length(p, "margin", DEFAULT_CORNER_MARGIN_MM, positive=False)
        gap = self.corner_length(p, "gap", DEFAULT_CORNER_GAP_MM, positive=False)
        if not (ok and good) or None in (font, size, subtitle_font, subtitle_size, font_fill, subtitle_fill, align,
                                         margin, gap):
            return None
        return Title(text, subtitle, pen, font, size, subtitle_font, subtitle_size, illustration, at, align, margin,
                     gap, location, font_fill, subtitle_fill)

    def letter_fill(self, p: dict, key: str, font: str | None, default: Fill) -> Fill | None:
        """How the insides of a font's letters are hatched (font_fill=, §16.1), or ``default``; None after an
        error. Only an outline font's letters have insides."""
        if key not in p:
            return default
        text, where = p[key]
        try:
            fill = Fill(text)
        except ValueError:
            options = ", ".join(f.value for f in Fill)
            self.sink.error("bad-value", f"{key}= takes one of {options}, not '{text}'", where)
            return None
        if fill is not Fill.NONE and font is not None and not self.fonts[font].outline:
            self.sink.error(
                "not-an-outline-font",
                f"{key}=: '{font}' draws its letters as single lines, so they have no insides to fill; it needs an "
                "outline font, such as one made with axitime convert-font",
                where,
            )
            return None
        return fill

    def credits(self, node: Tree, context: tuple[str, float]) -> Credits | None:
        location = self.loc(node)
        _, *items = node.children
        body = items.pop() if items and isinstance(items[-1], Tree) and items[-1].data == "credit_lines" else None
        ok = True
        lines = []
        if body is None or not body.children:
            self.sink.error(
                "bad-value",
                'the credits need a { } body of lines: each a quoted string, or heading and a quoted string '
                '(heading "Sources")',
                location,
            )
            ok = False
        else:
            for line in body.children:
                *heading, text_token = line.children
                lines.append(CreditLine(self.value(text_token), bool(heading), self.loc(line)))
        pen, illustration, at, param_nodes, good = self.corner_items(
            items, "credits", location, _CREDITS_ILLUSTRATION_KEYS,
            {
                "height": "the credits' illustration is as tall as their lines; limit both with max_height= on "
                "credits",
                "side": "put it left or right of the lines with at=left or at=right",
            },
            Horizontal.RIGHT,
        )
        p = self.params(param_nodes, _CREDITS_KEYS, "credits")
        align = self.horizontal(p, "align", Horizontal.RIGHT)
        inherited_font, inherited_size = context
        font = self.font(*p["font"]) if "font" in p else inherited_font
        size = self.corner_length(p, "font_size", inherited_size)
        heading_font = self.font(*p["heading_font"]) if "heading_font" in p else font
        heading_size = self.corner_length(p, "heading_font_size", size * HEADING_SCALE if size else None)
        max_height = self.corner_length(p, "max_height", None)
        margin = self.corner_length(p, "margin", DEFAULT_CORNER_MARGIN_MM, positive=False)
        gap = self.corner_length(p, "gap", DEFAULT_CORNER_GAP_MM, positive=False)
        if "max_height" in p and max_height is None:
            ok = False
        if not (ok and good) or None in (font, size, heading_font, heading_size, align, margin, gap):
            return None
        return Credits(tuple(lines), pen, font, size, heading_font, heading_size, max_height, illustration, at,
                       align, margin, gap, location)

    def check_corner_glyphs(self, title: Title | None, credits: Credits | None) -> None:
        if title is not None:
            self.warn_missing_glyphs(self.fonts[title.font], title.font, title.text, "the title", title.location,
                                     markup=True)
            self.warn_missing_glyphs(self.fonts[title.subtitle_font], title.subtitle_font, title.subtitle,
                                     "the subtitle", title.location, markup=True)
        if credits is not None:
            for line in credits.lines:
                key = credits.heading_font if line.heading else credits.font
                what = "a heading of the credits" if line.heading else "a line of the credits"
                self.warn_missing_glyphs(self.fonts[key], key, line.text, what, line.location, markup=True)

    # -- notes (§17) ----------------------------------------------------------------------------------------

    def note(self, node: Tree, context: tuple[str, float], order: int) -> Note | None:
        location = self.loc(node)
        _, *items = node.children
        body = items.pop() if items and isinstance(items[-1], Tree) and items[-1].data == "credit_lines" else None
        text_token = items.pop(0) if items and isinstance(items[0], Token) and items[0].type == "STRING" else None
        ok = True
        paragraphs = []
        if text_token is not None and body is not None:
            self.sink.error(
                "bad-value",
                "a note has either its text in quotes or a { } body of paragraphs, not both; put a heading in the "
                'body as heading "..."',
                location,
            )
            ok = False
        elif text_token is not None:
            paragraphs.append(NoteParagraph(self.value(text_token), False, location))
        elif body is not None:
            for line in body.children:
                *heading, token = line.children
                paragraphs.append(NoteParagraph(self.value(token), bool(heading), self.loc(line)))
        paragraphs = [NoteParagraph(" ".join(p.text.split()), p.heading, p.location) for p in paragraphs]
        if ok and not any(p.text for p in paragraphs):
            self.sink.error(
                "bad-value",
                'a note needs some text: note "..." or a { } body of paragraphs, each one or more lines of quoted '
                "text, with a blank line between paragraphs",
                location,
            )
            ok = False
        paragraphs = [p for p in paragraphs if p.text]
        pen, illustration, at, param_nodes, good = self.corner_items(
            items, "note", location, _NOTE_ILLUSTRATION_KEYS,
            {
                "height": "a note's illustration is as tall as its text; change that with the note's width= or "
                "font_size=",
                "side": "put it left or right of the text with at=left or at=right",
            },
            Horizontal.RIGHT,
        )
        ok = ok and good
        p = self.params(
            param_nodes, _NOTE_KEYS, "a note",
            {"at": "anchor it with anchor=start, middle, end or a date", "side": "fix it to edge=top or edge=bottom",
             "priority": "a note isn't an entity, so it has no priority"},
        )
        anchor: NoteAnchor | DateValue | None = NoteAnchor.START
        if "anchor" in p:
            text, where = p["anchor"]
            try:
                anchor = NoteAnchor(text)
            except ValueError:
                try:
                    anchor = parse_date(text)
                except DateError as exc:
                    self.sink.error(
                        "bad-value", f"anchor= takes start, middle, end or one date, not '{text}': {exc}", where
                    )
                    anchor = None
        edge: Edge | None = Edge.TOP
        if "edge" in p:
            text, where = p["edge"]
            try:
                edge = Edge(text)
            except ValueError:
                self.sink.error("bad-value", f"edge= takes top or bottom, not '{text}'", where)
                edge = None
        align = self.horizontal(p, "align", Horizontal.LEFT)
        inherited_font, inherited_size = context
        font = self.font(*p["font"]) if "font" in p else inherited_font
        size = self.corner_length(p, "font_size", inherited_size)
        heading_font = self.font(*p["heading_font"]) if "heading_font" in p else font
        heading_size = self.corner_length(p, "heading_font_size", size * HEADING_SCALE if size else None)
        width = self.corner_length(p, "width", None)
        margin = self.corner_length(p, "margin", DEFAULT_NOTE_MARGIN_MM, positive=False)
        clearance = self.corner_length(p, "clearance", DEFAULT_NOTE_CLEARANCE_MM, positive=False)
        gap = self.corner_length(p, "gap", DEFAULT_CORNER_GAP_MM, positive=False)
        if "width" in p and width is None:
            ok = False
        if not ok or None in (anchor, edge, font, size, heading_font, heading_size, align, margin, clearance, gap):
            return None
        for para in paragraphs:
            key = heading_font if para.heading else font
            what = "a heading of a note" if para.heading else "a note"
            self.warn_missing_glyphs(self.fonts[key], key, para.text, what, para.location, markup=True)
        return Note(tuple(paragraphs), pen, font, size, heading_font, heading_size, anchor, edge, width,
                    align, margin, clearance, order, location, illustration, at, gap)

    # -- graphs (§15) ---------------------------------------------------------------------------------------

    def graph(self, node: Tree, context: tuple[str, float]) -> Graph | None:
        location = self.loc(node)
        head, title_token, *items = node.children
        points_node = items.pop() if items and isinstance(items[-1], Tree) and items[-1].data == "points" else None
        title = self.value(title_token)
        ok = True
        if str(head) != "graph":
            self.sink.error(
                "graph-marks",
                "a graph takes no ^/v side or !/- priority marks: it is a background, drawn on both sides of the "
                "baseline, and takes no lane",
                location,
            )
            ok = False
        pen = None
        param_nodes = []
        for item in items:
            if item.data == "param":
                param_nodes.append(item)
            elif item.data == "illustration":
                self.sink.error("unexpected-item", "a graph can't have an illustration", location)
                ok = False
            else:
                word = str(item.children[0])
                ok = False
                if pen is None and is_pen(word):
                    pen, ok = word, True
                elif pen is not None and is_pen(word):
                    self.sink.error("duplicate-pen", f'graph "{title}" has more than one pen', location)
                else:
                    hint = suggest_pen(word)
                    extra = f"; did you mean {hint}?" if hint else ""
                    self.sink.error("unknown-pen", f"'{word}' is not a pen{extra}", location)
        p = self.params(param_nodes, _GRAPH_KEYS, "graph")

        def number(key: str, *, positive: bool = False) -> float | None:
            text, where = p[key]
            value = graphdata.number(text)
            if value is None or (positive and value <= 0):
                need = "a number above zero" if positive else "a number"
                self.sink.error("bad-value", f"{key}= takes {need}, such as 2.5, not '{text}'", where)
                return None
            return value

        def whole(key: str) -> int | None:
            text, where = p[key]
            if text.isdigit() and int(text) > 0:
                return int(text)
            self.sink.error("bad-value", f"{key}= takes a row number, counting from 1, not '{text}'", where)
            return None

        def choice(key: str, enum, default):
            if key not in p:
                return default
            text, where = p[key]
            try:
                return enum(text)
            except ValueError:
                options = ", ".join(m.value for m in enum)
                self.sink.error("bad-value", f"{key}= takes one of {options}, not '{text}'", where)
                return None

        def length(key: str) -> float | None:
            return self.length(key, *p[key]) if key in p else None

        y_scale = choice("y_scale", YScale, YScale.LINEAR)
        line = choice("line", LineMode, LineMode.STRAIGHT)
        fill = choice("fill", Fill, Fill.NONE)
        missing = p["missing"][0] if "missing" in p else None
        unit = p["unit"][0] if "unit" in p else ""
        fill_pen = None
        if "fill_pen" in p:
            text, where = p["fill_pen"]
            if not is_pen(text):
                hint = suggest_pen(text)
                self.sink.error("unknown-pen", f"fill_pen=: '{text}' is not a pen{f'; did you mean {hint}?' if hint else ''}",
                                where)
                ok = False
            elif fill is Fill.NONE:
                self.sink.error("bad-value", "fill_pen= needs a fill= pattern to draw", where)
                ok = False
            else:
                fill_pen = text

        origin: float | None = 0.0
        if "origin" in p and p["origin"][0] != "first":
            origin = number("origin")
            ok = ok and origin is not None
        elif "origin" in p:
            origin = None
        if y_scale is YScale.LOG and origin is not None and origin <= 0:
            where = p["origin"][1] if "origin" in p else location
            self.sink.error(
                "bad-value",
                "y_scale=log measures each value as a ratio of the origin, so it needs origin= above zero "
                "(the default is 0), or origin=first",
                where,
            )
            ok = False

        height = length("height")
        value_range = number("range", positive=True) if "range" in p else None
        if "range" in p and "height" not in p:
            self.sink.error("bad-value", "range= needs height= as well: together they fix the scale", p["range"][1])
            ok = False
        if y_scale is YScale.LOG and value_range is not None and value_range <= 1:
            self.sink.error(
                "bad-value", "with y_scale=log, range= is a ratio and must be above 1 (range=10 is a power of ten)",
                p["range"][1],
            )
            ok = False

        fill_depth = length("fill_depth")
        shadow = length("shadow")
        for key in ("fill_depth", "shadow"):
            if key in p and fill is Fill.NONE:
                self.sink.error("bad-value", f"{key}= needs a fill= pattern to shade with", p[key][1])
                ok = False
        if "shadow" in p and "fill_depth" not in p:
            self.sink.error("bad-value", "shadow= needs fill_depth=, the shadow's thickness", p["shadow"][1])
            ok = False

        value_scale, value_scale_mm = ValueScaleMode.EVERY, 1000.0
        if "value_scale" in p:
            text, where = p["value_scale"]
            if text in ("off", "start"):
                value_scale, value_scale_mm = ValueScaleMode(text), None
            else:
                value_scale_mm = self.length("value_scale", text, where)
                if value_scale_mm is None:
                    ok = False
        value_marks = None
        if "value_marks" in p and p["value_marks"][0] != "auto":
            text, where = p["value_marks"]
            marks = [graphdata.number(part.strip()) for part in text.split(",")]
            if any(m is None for m in marks):
                self.sink.error(
                    "bad-value", f"value_marks= takes auto or numbers separated by commas, such as 0,100,200, not '{text}'",
                    where,
                )
                ok = False
            elif y_scale is YScale.LOG and any(m <= 0 for m in marks):
                self.sink.error("bad-value", "with y_scale=log, every value mark must be above zero", where)
                ok = False
            else:
                value_marks = tuple(sorted(set(marks)))

        inherited_font, inherited_size = context
        font = self.font(*p["font"]) if "font" in p else inherited_font
        font_size = self.length("font_size", *p["font_size"]) if "font_size" in p else inherited_size
        for value in (y_scale, line, fill, height if "height" in p else 0, fill_depth if "fill_depth" in p else 0,
                      shadow if "shadow" in p else 0, font, font_size):
            if value is None:
                ok = False

        points = None
        data = None
        if ("data" in p) == (points_node is not None):
            self.sink.error(
                "graph-data",
                "a graph takes its points from either data= (a CSV file) or a { } body of points, not both"
                if points_node is not None else
                "a graph needs points: data= naming a CSV file, or a { } body with a date and a value on each line",
                location,
            )
            ok = False
        elif points_node is not None:
            for key in _CSV_KEYS:
                if key in p:
                    self.sink.error("bad-value", f"{key}= applies to data= files, not points written inline", p[key][1])
                    ok = False
            lines = [([str(w) for w in point.children], self.loc(point)) for point in points_node.children]
            points = graphdata.read_inline(lines, missing, self.sink, location)
        else:
            options = self.csv_options(p)
            data = relative_name(location.source, p["data"][0])
            content = self.fetcher.fetch("data", data, p["data"][1])
            if options is not None and content is not None:
                points = graphdata.read_csv(content, data, options, self.sink, location)
        if points is None:
            return None
        if y_scale is YScale.LOG:
            bad = [pt for pt in points if pt.value is not None and pt.value <= 0]
            for pt in bad[: graphdata.MAX_ROW_ERRORS]:
                self.sink.error(
                    "bad-value", f"y_scale=log can't draw {pt.value:g}: every value must be above zero", pt.location
                )
            ok = ok and not bad
        if not ok:
            return None
        order = self.graph_count
        self.graph_count += 1
        return Graph(
            title=title,
            pen=pen or DEFAULT_GRAPH_PEN,
            fill_pen=fill_pen or pen or DEFAULT_GRAPH_PEN,
            points=tuple(points),
            data=data,
            origin=origin,
            y_scale=y_scale,
            height_mm=height,
            range=value_range,
            line=line,
            fill=fill,
            fill_depth_mm=fill_depth,
            shadow_mm=shadow,
            value_scale=value_scale,
            value_scale_mm=value_scale_mm,
            value_marks=value_marks,
            unit=unit,
            font=font,
            font_size_mm=font_size,
            order=order,
            location=location,
        )

    def csv_options(self, p: dict[str, tuple[str, SourceLocation]]) -> graphdata.CsvOptions | None:
        ok = True
        values: dict = {}
        for key in ("first_row", "last_row"):
            if key in p:
                text, where = p[key]
                if text.isdigit() and int(text) > 0:
                    values[key] = int(text)
                else:
                    self.sink.error("bad-value", f"{key}= takes a row number, counting from 1, not '{text}'", where)
                    ok = False
        if "first_row" in values and "last_row" in values and values["last_row"] < values["first_row"]:
            self.sink.error("bad-value", "last_row= is before first_row=", p["last_row"][1])
            ok = False
        if "header" in p:
            text, where = p["header"]
            if text not in ("yes", "no"):
                self.sink.error("bad-value", f"header= takes yes or no, not '{text}'", where)
                ok = False
            values["header"] = text == "yes"
        if "separator" in p:
            text, where = p["separator"]
            if text not in graphdata.SEPARATORS:
                options = ", ".join(graphdata.SEPARATORS)
                self.sink.error("bad-value", f"separator= takes one of {options}, not '{text}'", where)
                ok = False
            else:
                values["separator"] = graphdata.SEPARATORS[text]
        for key in ("time_column", "value_column"):
            if key in p:
                text, where = p[key]
                if text.isdigit():
                    if int(text) < 1:
                        self.sink.error("bad-value", f"{key}= counts columns from 1", where)
                        ok = False
                    values[key] = int(text)
                else:
                    values[key] = text.strip()
        if "time_format" in p:
            values["time_format"] = p["time_format"][0]
        if "missing" in p:
            values["missing"] = p["missing"][0].strip()
        return graphdata.CsvOptions(**values) if ok else None

    def drop_duplicate_graphs(self, graphs: list[Graph]) -> list[Graph]:
        """A graph defined again (§15.1): its identity is its title, and the last definition wins, as for
        entities (§5). Untitled graphs are never duplicates."""
        last = {g.title: g for g in graphs if g.title}
        kept = []
        for g in graphs:
            winner = last.get(g.title)
            if winner is not None and winner is not g and (
                g.location.source != winner.location.source or g.location.line == winner.location.line
            ):
                self.sink.warning(
                    "duplicate-graph",
                    f'graph "{g.title}" is defined again at {winner.location}; the later definition wins and this '
                    "one is dropped",
                    g.location,
                )
                continue
            kept.append(g)
        return kept

    # -- whole-document checks ----------------------------------------------------------------------------

    def drop_duplicates(self, entities: list[Entity]) -> list[Entity]:
        """The same entity defined again: the last definition wins, with a warning (§5).

        An entity's identity is its type and label, plus its date for an event, so two "General election"
        events in different years are different events. Repeating an identity within one file is deliberate
        and kept; the same line arriving twice (one file included by two routes) is a duplicate.
        """
        everything = [e for top in entities for e in top.walk()]
        last: dict[tuple, Entity] = {}
        for e in everything:
            last[_identity(e)] = e
        dropped: set[int] = set()
        for e in everything:
            winner = last[_identity(e)]
            if winner is e:
                continue
            if e.location.source != winner.location.source or e.location.line == winner.location.line:
                dropped.add(e.order)
                self.sink.warning(
                    "duplicate-entity",
                    f'{e.kind.value} "{e.label}" is defined again at {winner.location}; '
                    "the later definition wins and this one is dropped",
                    e.location,
                )
        if not dropped:
            return entities

        def prune(items: tuple[Entity, ...] | list[Entity]) -> tuple[Entity, ...]:
            return tuple(replace(e, children=prune(e.children)) for e in items if e.order not in dropped)

        return list(prune(entities))

    def check_glyphs(self, entities: list[Entity]) -> None:
        for top in entities:
            for e in top.walk():
                font = self.fonts.get(e.font)
                if font is None:
                    continue
                what = f'{e.kind.value} "{e.label}"'
                self.warn_missing_glyphs(font, e.font, e.label, what, e.location, markup=True)
                if e.kind is Kind.EVENT and e.time_label is not TimeLabel.NONE:
                    self.warn_missing_glyphs(font, e.font, time_label_text(e.when, e.time_label.value),
                                             f"the time label of {what}", e.location)

    def warn_missing_glyphs(self, font: Font, font_key: str, text: str, what: str, location: SourceLocation,
                            markup: bool = False) -> None:
        """Warn of each character the font can't draw. With ``markup``, the text's inline formatting (§3.11) is
        read first: each stretch is checked in the cut it is drawn in, and bold or italic that the font's family
        has no cut for is a warning too."""
        runs = [(font, font_key, text)]
        if markup:
            runs = []
            missing: list[str] = []
            for span in parse_inline(text):
                cut, bold, italic = font_variant(font, span.bold, span.italic)
                for wanted, got, name in ((span.bold, bold, "bold"), (span.italic, italic, "italic")):
                    if wanted and not got and name not in missing:
                        missing.append(name)
                key = font_key if cut is font else cut.name
                runs.append((cut, key, span.text))
            for name in missing:
                self.sink.warning(
                    "missing-style",
                    f"font {font_key} has no {name} cut for {what}, so that text is drawn "
                    f"{'in its normal weight' if name == 'bold' else 'upright'}",
                    location,
                )
        seen: set[tuple[str, str]] = set()
        for cut, key, run in runs:
            for r in drawable_text(cut, run)[1]:
                if (key, r.original) in seen:
                    continue
                seen.add((key, r.original))
                code = f"U+{ord(r.original):04X}"
                char = code if r.original.isspace() or not r.original.isprintable() else f"{r.original} ({code})"
                if r.replacement == "":
                    drawn = "leaving it out"
                elif r.replacement.isspace():
                    drawn = "drawing a space instead"
                else:
                    drawn = f"drawing {r.replacement} instead"
                self.sink.warning("missing-glyph", f"font {key} has no {char} for {what}; {drawn}", location)


def _identity(e: Entity) -> tuple:
    """What makes two definitions the same entity (§5): type and label, and for an event its date as well.

    An event's date matches only at the same moment and the same precision: 1939-09 and 1939-09-01 differ.
    """
    label = plain_text(e.label)  # formatting doesn't make it another entity (§3.11)
    if e.kind is Kind.EVENT:
        return (e.kind, label, e.when.first_second(), e.when.precision)
    return (e.kind, label)


def _a(word: str) -> str:
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"


def _unclosed_body(lines: list[LogicalLine]) -> LogicalLine | None:
    """The innermost group or graph whose { is never closed, for pointing the error at its own line."""
    open_lines: list[LogicalLine] = []
    for line in lines:
        if line.text == "}":
            if open_lines:
                open_lines.pop()
        elif line.text.endswith("{"):
            open_lines.append(line)
    return open_lines[-1] if open_lines else None


def _looks_like_date(word: str) -> bool:
    try:
        parse_when(word)
        return True
    except DateError:
        return False
