"""Reading a graph's points (language spec §§15.2–15.4): from a CSV file read as the source has it, or from lines
written inline in the graph's ``{ }`` body.

A point is a moment (the start of its date, §3.3) and a value, or a gap. Points must come in time order. Errors
name the CSV row (numbered the way an editor numbers lines) or the source line, so ``check`` and the editor point
at what to fix. A file that goes wrong on many rows reports the first few and then a count, since one wrong
setting (a column, a time format) usually spoils every row.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from typing import Callable

from .dates import AGO_UNITS, PRESENT_YEAR, DateError, DateValue, parse_date
from .diagnostics import Diagnostics, SourceLocation
from .model import GraphPoint

SEPARATORS = {"comma": ",", "semicolon": ";", "tab": "\t"}
MAX_ROW_ERRORS = 5  # after this many bad rows, the rest are counted rather than listed

_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
# Longest first, so MMMM wins over MMM over MM.
_FORMAT_TOKENS = (
    ("YYYY", r"(?P<Y>\d{1,4})"),
    ("MMMM", r"(?P<month_name>[A-Za-z]+)"),
    ("MMM", r"(?P<month_abbr>[A-Za-z]{3})"),
    ("MM", r"(?P<M>\d{1,2})"),
    ("DD", r"(?P<D>\d{1,2})"),
    ("hh", r"(?P<h>\d{1,2})"),
    ("mm", r"(?P<m>\d{1,2})"),
    ("ss", r"(?P<s>\d{1,2})"),
)


class FormatError(ValueError):
    """A time_format= pattern that can't be used."""


@dataclass(frozen=True)
class CsvOptions:
    first_row: int = 1
    last_row: int | None = None
    header: bool = True
    separator: str = ","
    time_column: int | str = 1  # a position counting from 1, or a header name
    value_column: int | str = 2
    time_format: str | None = None
    missing: str | None = None


def time_reader(time_format: str | None) -> Callable[[str], int]:
    """A function reading a time cell's text as seconds on the language's axis (§3.3), raising ValueError.

    Without a format, the language's own dates, allowing a space in place of the T before a time. With one, the
    pattern of §15.2, ``decimal_year``, or ``ka``, ``Ma`` or ``Ga`` for an age before 1950. Raises :class:`FormatError` for a pattern that names no year.
    """
    if time_format is None:
        def language(text: str) -> int:
            return parse_date(re.sub(r"^(\S+) (\d)", r"\1T\2", text)).first_second()

        return language
    if time_format == "decimal_year":
        def decimal(text: str) -> int:
            if not _NUMBER.match(text):
                raise ValueError(f"'{text}' isn't a decimal year such as 1958.2027")
            value = float(text)
            year = math.floor(value)
            if year < 1:
                raise ValueError(f"'{text}' is before 1 AD, which a decimal year can't express")
            whole = parse_date(str(year))
            start, end = whole.first_second(), whole.next_period_start()
            return start + round((value - year) * (end - start))

        return decimal
    ago = {u.lower(): u for u in AGO_UNITS}.get(time_format.lower())
    if ago is not None:
        def before_present(text: str) -> int:
            if not _NUMBER.match(text):
                raise ValueError(f"'{text}' isn't a number of {ago} before 1950, such as 66.5")
            return _fractional_year(PRESENT_YEAR - float(text) * AGO_UNITS[ago])

        return before_present

    pattern, i = "", 0
    while i < len(time_format):
        for token, rx in _FORMAT_TOKENS:
            if time_format.startswith(token, i):
                if f"(?P<{rx[4:].split('>')[0]}>" in pattern:
                    raise FormatError(f"time_format=\"{time_format}\" names {token} more than once")
                pattern += rx
                i += len(token)
                break
        else:
            pattern += re.escape(time_format[i])
            i += 1
    if "(?P<Y>" not in pattern:
        raise FormatError(f'time_format="{time_format}" has no YYYY: every time needs a year')
    if "(?P<M>" in pattern and ("(?P<month_name>" in pattern or "(?P<month_abbr>" in pattern):
        raise FormatError(f'time_format="{time_format}" names the month twice')
    compiled = re.compile("^" + pattern + "$")

    def formatted(text: str) -> int:
        m = compiled.match(text)
        if not m:
            raise ValueError(f"'{text}' doesn't match time_format=\"{time_format}\"")
        parts = {k: v for k, v in m.groupdict().items() if v is not None}
        month = parts.get("M")
        name = parts.get("month_name") or parts.get("month_abbr")
        if name is not None:
            found = [n for n, full in enumerate(_MONTHS, 1) if len(name) >= 3 and full.startswith(name.lower())]
            if not found or (parts.get("month_name") and name.lower() != _MONTHS[found[0] - 1]):
                raise ValueError(f"'{name}' isn't the name of a month")
            month = found[0]
        written = str(int(parts["Y"]))
        for value, separator in ((month, "-"), (parts.get("D"), "-"), (parts.get("h"), "T"), (parts.get("m"), ":"),
                                 (parts.get("s"), ":")):
            if value is None:
                break
            written += f"{separator}{int(value):02d}"
        try:
            return parse_date(written).first_second()
        except DateError as exc:
            raise ValueError(f"'{text}' read with time_format=\"{time_format}\" isn't a real date ({exc})") from None

    return formatted


def _fractional_year(value: float) -> int:
    """The moment ``value`` (an astronomical year with a fraction, 1958.5) falls on, to the second."""
    year = math.floor(value)
    whole = DateValue(year)
    start, end = whole.first_second(), whole.next_period_start()
    return start + round((value - year) * (end - start))


def number(text: str) -> float | None:
    """A value cell's number, or None if it isn't one."""
    return float(text) if _NUMBER.match(text) else None


class _Reader:
    """Turns (time text, value text, location) rows into points, collecting problems as it goes."""

    def __init__(self, read_time: Callable[[str], int], missing: str | None, time_format: str | None,
                 sink: Diagnostics):
        self.read_time = read_time
        self.missing = missing
        self.time_format = time_format
        self.sink = sink
        self.points: list[GraphPoint] = []
        self.problems: list[tuple[str, str, SourceLocation]] = []

    def problem(self, code: str, message: str, location: SourceLocation) -> None:
        self.problems.append((code, message, location))

    def add(self, time_text: str, value_text: str, location: SourceLocation) -> None:
        time_text, value_text = time_text.strip(), value_text.strip()
        if not time_text:
            self.problem("bad-data", "this row has a value but no time", location)
            return
        try:
            seconds = self.read_time(time_text)
        except (DateError, ValueError) as exc:
            if self.time_format is None:
                message = (f"'{time_text}' isn't a date the language can read ({exc}); if the file writes its dates "
                           "another way, give time_format=")
            else:
                message = str(exc)
            self.problem("bad-time", message, location)
            return
        value: float | None = None
        if value_text and value_text != self.missing:
            value = number(value_text)
            if value is None:
                hint = ""
                if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", value_text):
                    hint = " (write it without thousands separators)"
                elif re.fullmatch(r"[+-]?\d+,\d+", value_text):
                    hint = " (write it with a decimal point, not a comma)"
                elif self.missing is None:
                    hint = "; if it marks a gap in the data, give missing="
                self.problem("bad-value", f"'{value_text}' isn't a number{hint}", location)
                return
        if self.points and seconds <= self.points[-1].seconds:
            previous = self.points[-1]
            self.problem(
                "points-out-of-order",
                f"'{time_text}' isn't later than the point before it ({previous.location}); points must be in "
                "time order",
                location,
            )
            return
        self.points.append(GraphPoint(seconds, value, location))

    def finish(self, what: str, location: SourceLocation) -> list[GraphPoint] | None:
        for code, message, where in self.problems[:MAX_ROW_ERRORS]:
            self.sink.error(code, message, where)
        if len(self.problems) > MAX_ROW_ERRORS:
            extra = len(self.problems) - MAX_ROW_ERRORS
            self.sink.error("bad-data", f"and {extra} more row{'s' if extra != 1 else ''} with problems in {what}",
                            location)
        if self.problems:
            return None
        if not any(p.value is not None for p in self.points):
            self.sink.error("no-points", f"{what} gave the graph no points", location)
            return None
        return self.points


def read_inline(lines: list[tuple[list[str], SourceLocation]], missing: str | None, sink: Diagnostics,
                location: SourceLocation) -> list[GraphPoint] | None:
    """Points written in a graph's ``{ }`` body: a date (§3.3) and a value on each line (§15.3)."""
    reader = _Reader(lambda text: parse_date(text).first_second(), missing, None, sink)
    for words, where in lines:
        if len(words) != 2:
            reader.problem("bad-point", "each line of a graph's { } body is a date and a value, e.g. 1929-10-29 230.07",
                           where)
            continue
        reader.add(words[0], words[1], where)
    return reader.finish("the graph's { } body", location)


def read_csv(content: bytes, name: str, options: CsvOptions, sink: Diagnostics,
             location: SourceLocation) -> list[GraphPoint] | None:
    """Points read from a CSV file as it comes (§15.2). ``location`` is the graph's declaration."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        sink.error("bad-data", f"'{name}' is not UTF-8 text ({exc.reason})", location)
        return None
    try:
        read_time = time_reader(options.time_format)
    except FormatError as exc:
        sink.error("bad-value", str(exc), location)
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=options.separator, strict=True)
    rows: list[tuple[int, list[str]]] = []
    line_end = 0
    try:
        for fields in reader:
            line = line_end + 1  # a row is numbered by the line it starts on
            line_end = reader.line_num
            if line < options.first_row:
                continue
            if options.last_row is not None and line > options.last_row:
                break
            rows.append((line, fields))
    except csv.Error as exc:
        sink.error("bad-data", f"can't read the CSV: {exc}", SourceLocation(name, line_end + 1))
        return None

    names: dict[str, int] = {}
    if options.header:
        if not rows:
            sink.error("bad-data", f"'{name}' has no row {options.first_row} to read the column names from", location)
            return None
        _, header = rows.pop(0)
        for k, cell in enumerate(header):
            names.setdefault(cell.strip(), k)

    def column(spec: int | str, key: str) -> int | None:
        if isinstance(spec, int):
            return spec - 1
        if not options.header:
            sink.error("bad-value", f"{key}={spec} names a column, but header=no: give its number instead", location)
            return None
        if spec not in names:
            have = ", ".join(n for n in names if n) or "no names"
            sink.error(
                "unknown-column",
                f"{key}={spec}: '{name}' has no column called that; its header (row {options.first_row}) has {have}. "
                "first_row= says which row the names are on",
                location,
            )
            return None
        return names[spec]

    time_index = column(options.time_column, "time_column")
    value_index = column(options.value_column, "value_column")
    if time_index is None or value_index is None:
        return None
    data = _Reader(read_time, options.missing, options.time_format, sink)
    for line, fields in rows:
        if all(not f.strip() for f in fields):
            continue  # blank rows are skipped
        where = SourceLocation(name, line)
        if len(fields) <= max(time_index, value_index):
            data.problem(
                "bad-data",
                f"this row has {len(fields)} column{'s' if len(fields) != 1 else ''}, but the graph reads column "
                f"{max(time_index, value_index) + 1}",
                where,
            )
            continue
        data.add(fields[time_index], fields[value_index], where)
    return data.finish(f"'{name}'", location)
