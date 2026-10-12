"""``parse(source, resolve) -> ParseResult``: the first stage, and the only one that calls host I/O.

Flattens includes (preprocess), runs the grammar once over the flattened text, then builds the AST: checking
dates, pens and parameters, resolving inheritance that is purely textual (pen, font, font size), dropping
duplicate entities (last definition wins, §5), and loading every font and illustration the document uses.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace

from lark import Token, Tree
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken

from . import grammar
from .dates import DateError, DateRange, DateValue, parse_date, parse_when
from .diagnostics import AxitlError, Diagnostic, Diagnostics, SourceLocation
from .fetch import Fetcher, Resolver, Resource, no_resolver, relative_name
from .fonts import BUILTIN_FONTS, DEFAULT_FONT, Font, FontError, load_builtin_font, parse_svg_font
from .illustration import IllustrationError, intrinsic_size
from .model import (
    Baseline,
    Entity,
    Fill,
    Illustration,
    Kind,
    OpenEndStyle,
    Side,
    TimelineDocument,
    TimelineSettings,
)
from .pens import DEFAULT_PEN, is_pen, suggest_pen
from .preprocess import Flattener, LogicalLine, unescape
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
    "ticks", "tick_label_every", "open_end_style", "font", "font_size",
)
_ENTITY_KEYS = ("fill", "font", "font_size")
_UNCLOSED_GROUP = "this group's { body is never closed with }"


@dataclass(frozen=True)
class ParseResult:
    document: TimelineDocument
    flattened_text: str  # exactly what the grammar parsed; the job hash covers this
    resources: tuple[Resource, ...]  # everything fetched through resolve, in first-use order
    diagnostics: tuple[Diagnostic, ...]  # warnings (a parse with errors raises AxitlError instead)


def parse(source: str, resolve: Resolver | None = None, source_name: str = "main.axitl") -> ParseResult:
    """Parse ``.axitl`` source.

    ``resolve(name)`` fetches includes, illustrations and custom fonts; names are relative to the same root as
    ``source_name``. Raises :class:`AxitlError`, carrying every diagnostic found, if the source has errors.
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
            location = _unclosed_group(lines) or location
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
    if "HEAD" in expected or "TIMELINE" in expected:
        if found == "'}'":
            return "this } has no group { to close"
        return (
            f"{found} doesn't start a declaration; a line starts with timeline, person, event, span or group "
            "(with optional ^/v side and !/- priority marks before the keyword)"
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

    def params(self, nodes: list[Tree], allowed: tuple[str, ...], where: str) -> dict[str, tuple[str, SourceLocation]]:
        found: dict[str, tuple[str, SourceLocation]] = {}
        for node in nodes:
            key_token, value_token = node.children
            key, location = str(key_token), self.loc(node)
            if key not in allowed:
                hint = difflib.get_close_matches(key, allowed, n=1)
                extra = f"; did you mean {hint[0]}=?" if hint else ""
                if where != "timeline" and key in ("side", "priority"):
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
        )
        entities = [
            e for c in tree.children if c.data == "entity" if (e := self.entity(c, context, None)) is not None
        ]
        entities = self.drop_duplicates(entities)
        self.check_glyphs(entities)
        if settings is None or self.sink.has_errors:
            return None
        return TimelineDocument(settings, tuple(entities), dict(sorted(self.fonts.items())))

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
            location=location,
        )

    # -- entities -----------------------------------------------------------------------------------------

    def entity(self, node: Tree, context: tuple[str, str, float], group: str | None) -> Entity | None:
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
        inherited_pen, inherited_font, inherited_size = context
        font = self.font(*p["font"]) if "font" in p else inherited_font
        font_size = self.length("font_size", *p["font_size"]) if "font_size" in p else inherited_size
        pen = pen or inherited_pen

        children: list[Entity] = []
        if body is not None:
            if kind is not Kind.GROUP:
                self.sink.error("unexpected-body", f"only a group can have a {{ }} body, not {_a(kind.value)}", location)
                ok = False
            for child in body.children:
                if child.data == "timeline":
                    self.sink.error("nested-timeline", "a timeline declaration can't be inside a group", self.loc(child))
                    continue
                built = self.entity(child, (pen, font or inherited_font, font_size or inherited_size), label)
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
            font=font,
            font_size_mm=font_size,
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
        location = self.loc(node)
        _, file_token, *param_nodes = node.children
        p = self.params(param_nodes, ("height",), "illustration")
        height = self.length("height", *p["height"]) if "height" in p else None
        if "height" in p and height is None:
            return None
        name = relative_name(location.source, self.value(file_token))
        content = self.fetcher.fetch("illustration", name, location)
        if content is None:
            return None
        try:
            width, intrinsic_height = intrinsic_size(content, name)
        except IllustrationError as exc:
            self.sink.error("bad-illustration", str(exc), location)
            return None
        return Illustration(name, content, width, intrinsic_height, height)

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
                for r in drawable_text(font, e.label)[1]:
                    code = f"U+{ord(r.original):04X}"
                    char = code if r.original.isspace() or not r.original.isprintable() else f"{r.original} ({code})"
                    if r.replacement == "":
                        drawn = "leaving it out"
                    elif r.replacement.isspace():
                        drawn = "drawing a space instead"
                    else:
                        drawn = f"drawing {r.replacement} instead"
                    self.sink.warning(
                        "missing-glyph",
                        f'font {e.font} has no {char} for {e.kind.value} "{e.label}"; {drawn}',
                        e.location,
                    )


def _identity(e: Entity) -> tuple:
    """What makes two definitions the same entity (§5): type and label, and for an event its date as well.

    An event's date matches only at the same moment and the same precision: 1939-09 and 1939-09-01 differ.
    """
    if e.kind is Kind.EVENT:
        return (e.kind, e.label, e.when.first_second(), e.when.precision)
    return (e.kind, e.label)


def _a(word: str) -> str:
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"


def _unclosed_group(lines: list[LogicalLine]) -> SourceLocation | None:
    """The innermost group whose { is never closed, for pointing the error at the group's own line."""
    open_lines: list[LogicalLine] = []
    for line in lines:
        if line.text == "}":
            if open_lines:
                open_lines.pop()
        elif line.text.endswith("{"):
            open_lines.append(line)
    return open_lines[-1].location if open_lines else None


def _looks_like_date(word: str) -> bool:
    try:
        parse_when(word)
        return True
    except DateError:
        return False
