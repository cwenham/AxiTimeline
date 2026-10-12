"""The text pass that runs before the grammar: comments, multi-line declarations and include flattening.

Produces the canonical *flattened text* the grammar parses and the job hash covers (interpreter spec, "Public
shape"): comments removed, continuation lines joined onto their declaration with one space, whitespace
trimmed and (outside quoted strings) collapsed to single spaces, blank lines dropped, and every ``include`` replaced by the included file's own flattened text with
the include's ``priority=`` offset and ``side=`` override written into each entity line's prefix.

This pass has to understand comments (a commented-out include must not be followed, §3.9) and continuation
lines (an include's ``priority=`` may be on an indented line of its own, §3.10), so it tracks string state
rather than splitting naively on ``//``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .diagnostics import Diagnostics, SourceLocation
from .fetch import Fetcher, relative_name
from .model import Side

_KEY_START = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_ENTITY_HEAD = re.compile(r"^([\^v]?)([!\-]*)(person|event|span|group)(?![\w])")
_INCLUDE = re.compile(r"^include(?![\w])(.*)$")
_TIMELINE = re.compile(r"^timeline(?![\w])")
_QUOTED = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"(.*)$')


@dataclass(frozen=True)
class LogicalLine:
    """One declaration line of the flattened text, and where it came from."""

    text: str
    location: SourceLocation
    glued_comment: bool  # a // came straight after a word or number (the "1963//1964" typo hazard, §3.9)


def unescape(body: str) -> str:
    """The content of a quoted string: ``\\"`` is a quote, ``\\\\`` a backslash; other backslashes are literal."""
    return re.sub(r'\\(["\\])', r"\1", body)


def _split_comment(line: str) -> tuple[str, bool, bool, bool]:
    """Split off a ``//`` comment, ignoring ``//`` inside quotes.

    Returns (code, had_comment, glued, unterminated_string).
    """
    in_string = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "/" and line.startswith("//", i):
            return line[:i], True, i > 0 and line[i - 1].isalnum(), False
        i += 1
    return line, False, False, in_string


def _collapse_whitespace(code: str) -> str:
    """Trim, and collapse each run of spaces/tabs outside quoted strings to one space."""
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(code):
        c = code[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < len(code):
                out.append(code[i + 1])
                i += 1
            elif c == '"':
                in_string = False
        elif c in " \t":
            if out and out[-1] != " ":
                out.append(" ")
        else:
            out.append(c)
            in_string = c == '"'
        i += 1
    return "".join(out).rstrip(" ")


def apply_include_modifiers(text: str, priority_offset: int, side: Side | None) -> str:
    """Rewrite an entity line's prefix to carry an include's priority offset and side override (§5)."""
    m = _ENTITY_HEAD.match(text)
    if not m:
        return text
    side_mark, run, keyword = m.groups()
    if "!" in run and "-" in run:
        return text  # mixed priority symbols: left for the parser to report
    total = (len(run) if run.startswith("!") else -len(run)) + priority_offset
    run = "!" * total if total > 0 else "-" * -total
    if side is not None:
        side_mark = "^" if side is Side.ABOVE else "v"
    return f"{side_mark}{run}{keyword}{text[m.end():]}"


class Flattener:
    def __init__(self, fetcher: Fetcher, sink: Diagnostics):
        self._fetcher = fetcher
        self._sink = sink
        self.lines: list[LogicalLine] = []

    def flatten(self, text: str, name: str) -> list[LogicalLine]:
        self._file(text, name, (name,), 0, None)
        return self.lines

    def _file(self, text: str, name: str, chain: tuple[str, ...], offset: int, side: Side | None) -> None:
        text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
        decl: list[str] = []
        decl_line = 0
        decl_glued = False

        def flush() -> None:
            nonlocal decl
            if decl:
                self._declaration(" ".join(decl), SourceLocation(name, decl_line), decl_glued, chain, offset, side)
            decl = []

        for lineno, raw in enumerate(text.split("\n"), 1):
            code, had_comment, glued, unterminated = _split_comment(raw)
            location = SourceLocation(name, lineno)
            if unterminated:
                flush()
                self._sink.error("unterminated-string", 'this line opens a " that is never closed', location)
                continue
            stripped = _collapse_whitespace(code)
            if not stripped:
                if not had_comment:
                    flush()  # a blank line ends a declaration; a comment-only line doesn't (§3.10)
                continue
            if _KEY_START.match(stripped):
                if raw[:1] not in (" ", "\t"):
                    flush()
                    self._sink.error(
                        "unindented-parameter",
                        "a key=value line continuing a declaration must be indented",
                        location,
                    )
                elif not decl:
                    self._sink.error(
                        "orphan-parameter",
                        "this indented key=value line has no declaration to continue (a blank line ends one)",
                        location,
                    )
                else:
                    decl.append(stripped)
                    decl_glued = decl_glued or glued
                continue
            flush()
            decl, decl_line, decl_glued = [stripped], lineno, glued
        flush()

    def _declaration(
        self,
        text: str,
        location: SourceLocation,
        glued: bool,
        chain: tuple[str, ...],
        offset: int,
        side: Side | None,
    ) -> None:
        m = _INCLUDE.match(text)
        if m:
            self._include(m.group(1), location, chain, offset, side)
            return
        if len(chain) > 1 and _TIMELINE.match(text):
            self._sink.error(
                "timeline-in-include", "an included file can't contain a timeline declaration", location
            )
            return
        if offset or side is not None:
            text = apply_include_modifiers(text, offset, side)
        self.lines.append(LogicalLine(text, location, glued))

    def _include(
        self, rest: str, location: SourceLocation, chain: tuple[str, ...], offset: int, side: Side | None
    ) -> None:
        m = _QUOTED.match(rest)
        if not m:
            self._sink.error(
                "include-syntax", 'include needs a quoted file name, e.g. include "common/wars.axitl"', location
            )
            return
        path = unescape(m.group(1))
        include_priority, include_side, seen = 0, None, set()
        for item in m.group(2).split():
            key, eq, value = item.partition("=")
            if not eq:
                self._sink.error(
                    "include-syntax",
                    f"unexpected '{item}' after the include's file name; only priority= and side= can follow it",
                    location,
                )
                return
            if key in seen:
                self._sink.error("duplicate-parameter", f"{key}= is given more than once", location)
                return
            seen.add(key)
            if key == "priority":
                if not re.fullmatch(r"[+-]?\d+", value):
                    self._sink.error(
                        "bad-value", f"priority= takes a whole number such as -5 or 2, not '{value}'", location
                    )
                    return
                include_priority = int(value)
            elif key == "side":
                if value not in ("above", "below"):
                    self._sink.error("bad-value", f"side= takes above or below, not '{value}'", location)
                    return
                include_side = Side(value)
            else:
                self._sink.error(
                    "unknown-parameter", f"include has no {key}= parameter; it takes priority= and side=", location
                )
                return
        target = relative_name(chain[-1], path)
        if target in chain:
            cycle = " → ".join(chain[chain.index(target):] + (target,))
            self._sink.error("include-cycle", f"include cycle: {cycle}", location)
            return
        content = self._fetcher.fetch("include", target, location)
        if content is None:
            return
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            self._sink.error("include-encoding", f"include '{target}' is not UTF-8 text ({exc.reason})", location)
            return
        # Offsets add up through nested includes; the outermost side= override wins.
        self._file(text, target, chain + (target,), offset + include_priority, side or include_side)
