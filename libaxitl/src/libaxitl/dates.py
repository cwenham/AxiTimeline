"""Dates and date ranges (language spec §3.3, §3.6).

Every date normalises to whole seconds on one continuous axis: a proleptic Gregorian calendar with no year
zero, so 1 BC is immediately followed by 1 AD. Internally years are astronomical (1 BC = 0, 2 BC = -1), which
makes the calendar arithmetic uniform; the written form always uses the BC suffix.

A date keeps the precision it was written at, because that precision decides what moment it stands for: the
beginning of the period as a range start or a single point, the end of the period as a range end.

Timezones: a timestamp without one is a literal value on the axis. A timestamp with ``Z`` or an offset is
converted to UTC, so ``14:00+03:00`` and ``11:00`` are the same moment. (Interpretation; see known-gaps.)
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, replace
from enum import IntEnum

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

_DATE = re.compile(
    r"^(?P<year>\d+)(?P<bc>(?i:bce?))?"
    r"(?:-(?P<month>\d{2})"
    r"(?:-(?P<day>\d{2})"
    r"(?:[Tt](?P<hour>\d{2})(?::(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?"
    r"(?P<tz>[Zz]|[+-]\d{2}:\d{2})?)?)?)?$"
)
_BARE_YEAR = r"\d+(?i:bce?)?"
_YEAR_RANGE = re.compile(rf"^({_BARE_YEAR})-({_BARE_YEAR})?$")

DATE_FORMS = "1963, 1963-11, 1963-11-22, 1963-11-22T12:30:00 or 44BC-03-15"


class DateError(ValueError):
    """A date that doesn't follow the date grammar. The message is written for the author."""


class Precision(IntEnum):
    YEAR = 1
    MONTH = 2
    DAY = 3
    HOUR = 4
    MINUTE = 5
    SECOND = 6


def is_leap_year(year: int) -> bool:
    """Leap year in the proleptic Gregorian calendar, astronomical numbering (1 BC = 0, a leap year)."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if is_leap_year(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def days_from_civil(year: int, month: int, day: int) -> int:
    """Days since 1970-01-01 for an astronomical-year proleptic Gregorian date (H. Hinnant's algorithm)."""
    y = year - (1 if month <= 2 else 0)
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(days: int) -> tuple[int, int, int]:
    """Inverse of :func:`days_from_civil`."""
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    return yoe + era * 400 + (1 if month <= 2 else 0), month, day


def _written_year(year: int) -> str:
    return str(year) if year > 0 else f"{1 - year}BC"


@dataclass(frozen=True)
class DateValue:
    """A date as written, at its own precision. ``year`` is astronomical (1 BC = 0)."""

    year: int
    month: int = 1
    day: int = 1
    hour: int = 0
    minute: int = 0
    second: int = 0
    precision: Precision = Precision.YEAR
    offset_minutes: int | None = None

    def _local_start_seconds(self) -> int:
        return (
            days_from_civil(self.year, self.month, self.day) * 86400
            + self.hour * 3600
            + self.minute * 60
            + self.second
        )

    def _offset_seconds(self) -> int:
        return (self.offset_minutes or 0) * 60

    def first_second(self) -> int:
        """The first second of the period this date names: its value as a range start or a single point."""
        return self._local_start_seconds() - self._offset_seconds()

    def next_period_start(self) -> int:
        """The first second after the period this date names."""
        p = self.precision
        if p is Precision.YEAR:
            local = days_from_civil(self.year + 1, 1, 1) * 86400
        elif p is Precision.MONTH:
            y, m = (self.year + 1, 1) if self.month == 12 else (self.year, self.month + 1)
            local = days_from_civil(y, m, 1) * 86400
        else:
            step = {Precision.DAY: 86400, Precision.HOUR: 3600, Precision.MINUTE: 60, Precision.SECOND: 1}[p]
            local = self._local_start_seconds() + step
        return local - self._offset_seconds()

    def last_second(self) -> int:
        """The last second of the period this date names: its value as a range end (1945 → 31 Dec, 23:59:59)."""
        return self.next_period_start() - 1

    def truncate(self, precision: Precision) -> DateValue:
        """This moment reduced to a coarser precision, e.g. for resolving ``now`` against ``start`` (§3.6).

        A timestamp with an offset is first converted to UTC, since truncation is about the unified axis.
        """
        if precision > self.precision:
            raise ValueError("truncate() can only make a date coarser")
        base = self if self.offset_minutes is None else DateValue.from_seconds(self.first_second(), self.precision)
        fields = {"month": 1, "day": 1, "hour": 0, "minute": 0, "second": 0}
        keep = ("month", "day", "hour", "minute", "second")[: precision - 1]
        return replace(
            base, precision=precision, offset_minutes=None, **{k: v for k, v in fields.items() if k not in keep}
        )

    @classmethod
    def from_seconds(cls, seconds: int, precision: Precision = Precision.SECOND) -> DateValue:
        """The moment ``seconds`` on the axis (no timezone), truncated to ``precision``."""
        days, rem = divmod(seconds, 86400)
        y, m, d = civil_from_days(days)
        hh, rem = divmod(rem, 3600)
        mm, ss = divmod(rem, 60)
        return cls(y, m, d, hh, mm, ss, Precision.SECOND).truncate(precision)

    @classmethod
    def from_datetime(cls, value: _dt.datetime) -> DateValue:
        """A host clock reading (or any ``datetime``) as a second-precision date."""
        offset = value.utcoffset()
        minutes = None if offset is None else int(offset.total_seconds()) // 60
        return cls(
            value.year, value.month, value.day, value.hour, value.minute, value.second, Precision.SECOND, minutes
        )

    def __str__(self) -> str:
        """The date in the language's own syntax, at its own precision."""
        text = _written_year(self.year)
        if self.precision >= Precision.MONTH:
            text += f"-{self.month:02d}"
        if self.precision >= Precision.DAY:
            text += f"-{self.day:02d}"
        if self.precision >= Precision.HOUR:
            text += f"T{self.hour:02d}"
        if self.precision >= Precision.MINUTE:
            text += f":{self.minute:02d}"
        if self.precision >= Precision.SECOND:
            text += f":{self.second:02d}"
        if self.offset_minutes is not None:
            if self.offset_minutes == 0:
                text += "Z"
            else:
                sign = "+" if self.offset_minutes > 0 else "-"
                h, m = divmod(abs(self.offset_minutes), 60)
                text += f"{sign}{h:02d}:{m:02d}"
        return text

    def describe(self) -> str:
        """A human-readable form for messages, e.g. ``December 1910`` or ``15 March 44 BC``."""
        year = str(self.year) if self.year > 0 else f"{1 - self.year} BC"
        if self.precision is Precision.YEAR:
            return year
        if self.precision is Precision.MONTH:
            return f"{_MONTH_NAMES[self.month - 1]} {year}"
        text = f"{self.day} {_MONTH_NAMES[self.month - 1]} {year}"
        if self.precision >= Precision.HOUR:
            text += f" {str(self).split('T', 1)[1]}"
        return text


@dataclass(frozen=True)
class DateRange:
    """A ranged entity's dates. ``end`` is None for an open (ongoing) entity written ``1953-`` or ``1953-04-01/``."""

    start: DateValue
    end: DateValue | None

    @property
    def is_open(self) -> bool:
        return self.end is None

    def __str__(self) -> str:
        bare_years = self.start.precision is Precision.YEAR and (
            self.end is None or self.end.precision is Precision.YEAR
        )
        sep = "-" if bare_years else "/"
        return f"{self.start}{sep}{self.end if self.end is not None else ''}"


def parse_date(text: str) -> DateValue:
    """Parse a single date in the language's date grammar."""
    m = _DATE.match(text)
    if not m:
        raise DateError(_explain_bad_date(text))
    year = int(m.group("year"))
    if year == 0:
        raise DateError(f"'{text}': there is no year 0; the year before 1 AD is 1BC")
    if m.group("bc"):
        year = 1 - year
    precision = Precision.YEAR
    fields = {}
    for name, prec in (
        ("month", Precision.MONTH),
        ("day", Precision.DAY),
        ("hour", Precision.HOUR),
        ("minute", Precision.MINUTE),
        ("second", Precision.SECOND),
    ):
        if m.group(name) is not None:
            fields[name] = int(m.group(name))
            precision = prec
    month = fields.get("month", 1)
    if not 1 <= month <= 12:
        raise DateError(f"'{text}': month {month} doesn't exist")
    day = fields.get("day", 1)
    if not 1 <= day <= days_in_month(year, month):
        raise DateError(f"'{text}': {_MONTH_NAMES[month - 1]} {_written_year(year)} has no day {day}")
    if fields.get("hour", 0) > 23:
        raise DateError(f"'{text}': hours run from 00 to 23")
    if fields.get("minute", 0) > 59:
        raise DateError(f"'{text}': minutes run from 00 to 59")
    if fields.get("second", 0) > 59:
        raise DateError(f"'{text}': seconds run from 00 to 59 (leap seconds aren't supported)")
    offset = None
    tz = m.group("tz")
    if tz:
        if tz in ("Z", "z"):
            offset = 0
        else:
            hh, mm = int(tz[1:3]), int(tz[4:6])
            if hh > 23 or mm > 59:
                raise DateError(f"'{text}': timezone offset {tz} is out of range")
            offset = (hh * 60 + mm) * (1 if tz[0] == "+" else -1)
    return DateValue(year=year, precision=precision, offset_minutes=offset, **fields)


def _explain_bad_date(text: str) -> str:
    if re.match(r"^\d+(?i:ad|ce)\b", text):
        return f"'{text}': years are AD unless marked BC or BCE, so leave off the AD/CE suffix"
    if re.match(r"^\d+(?i:bce?)?-\d(?:\D|$)|^\d+(?i:bce?)?-\d{2}-\d(?:\D|$)", text):
        return f"'{text}': write months and days with two digits, e.g. 1963-01-05"
    if re.match(r"^-\d", text):
        return f"'{text}': write years before 1 AD with a BC suffix, e.g. 44BC, not a minus sign"
    return f"'{text}' is not a date; dates look like {DATE_FORMS}"


def parse_when(text: str) -> DateValue | DateRange:
    """Parse the date part of an entity: a single date, a range, or an open-ended range (§3.3, §3.6).

    ``-`` separates two bare years; ``/`` is needed when either side is finer than a year. Two digits after a
    year and a hyphen always read as a month, so ``1910-12`` is December 1910, not 1910 to 1912.
    """
    if "/" in text:
        parts = text.split("/")
        if len(parts) > 2:
            raise DateError(f"'{text}' has more than one / ; a range has exactly one start and one end")
        first, second = parts
        if not first:
            raise DateError(f"'{text}' has no date before the /")
        return _checked_range(text, parse_date(first), parse_date(second) if second else None)
    m = _YEAR_RANGE.match(text)
    if m:
        first, second = m.group(1), m.group(2)
        if second is None:
            return DateRange(parse_date(first), None)
        if re.fullmatch(r"\d{2}", second):
            try:
                return parse_date(text)
            except DateError as exc:
                raise DateError(f"{exc}; for a range of years, write {first}/{second}") from None
        return _checked_range(text, parse_date(first), parse_date(second))
    if text.endswith("-") and len(text) > 1:
        raise DateError(
            f"'{text}': after a date finer than a year, mark an open range with / instead (e.g. {text[:-1]}/)"
        )
    return parse_date(text)


def _checked_range(text: str, start: DateValue, end: DateValue | None) -> DateRange:
    if end is not None and end.last_second() < start.first_second():
        raise DateError(f"'{text}' ends ({end.describe()}) before it starts ({start.describe()})")
    return DateRange(start, end)
