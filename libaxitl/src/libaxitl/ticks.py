"""Baseline tick marks: choosing the interval, generating ticks, choosing which ones carry labels (§10).

Ticks sit at round *time* intervals whose physical spacing lands near a target, taken from a ladder of rungs
a reader recognises. Labels go on the smallest larger rung whose ticks are all ticks of the tick rung, and move
further up the ladder if the label text would overlap at that spacing.

All moments are whole seconds on the axis (see :mod:`libaxitl.dates`); the axis origin, 1970-01-01, is a
midnight, so second, minute and hour ticks are simply multiples of their step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from .dates import DateValue, Precision, civil_from_days, days_from_civil, days_in_month

_FIXED_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
_NOMINAL_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "month": 2629746, "year": 31556952}
_PRECISION = {
    "second": Precision.SECOND,
    "minute": Precision.MINUTE,
    "hour": Precision.HOUR,
    "day": Precision.DAY,
    "month": Precision.MONTH,
    "year": Precision.YEAR,
}


@dataclass(frozen=True)
class Rung:
    unit: str  # second, minute, hour, day, month or year
    n: int

    def __str__(self) -> str:
        return f"{self.n} {self.unit}{'' if self.n == 1 else 's'}"

    @property
    def nominal_seconds(self) -> float:
        return self.n * _NOMINAL_SECONDS[self.unit]

    @property
    def precision(self) -> Precision:
        return _PRECISION[self.unit]

    def contains_all_ticks_of(self, coarser: Rung) -> bool:
        """True if every tick of ``coarser`` is also a tick of this rung (so it can label this rung's ticks)."""
        if self.unit in _FIXED_SECONDS:
            step = self.n * _FIXED_SECONDS[self.unit]
            if coarser.unit in _FIXED_SECONDS:
                return (coarser.n * _FIXED_SECONDS[coarser.unit]) % step == 0
            return 86400 % step == 0  # day, month and year ticks all fall on midnights
        if self.unit == "day":
            return coarser.n % self.n == 0 if coarser.unit == "day" else coarser.unit in ("month", "year")
        if self.unit == "month":
            return coarser.n % self.n == 0 if coarser.unit == "month" else coarser.unit == "year"
        return coarser.unit == "year" and coarser.n % self.n == 0

    # -- the ticks themselves -------------------------------------------------------------------------------

    def ticks(self, t0: int, t1: int) -> list[int]:
        """Every tick of this rung in [t0, t1], in time order."""
        if self.unit in _FIXED_SECONDS:
            step = self.n * _FIXED_SECONDS[self.unit]
            return list(range(-(-t0 // step) * step, t1 + 1, step))
        if self.unit == "year":
            return [t for t in (days_from_civil(y, 1, 1) * 86400 for y in self._years(t0, t1)) if t0 <= t <= t1]
        out = []
        for y, m in _months(t0, t1):
            if self.unit == "month":
                days = [1] if (m - 1) % self.n == 0 else []
            else:
                days = _days_of_month(y, m, self.n)
            for d in days:
                t = days_from_civil(y, m, d) * 86400
                if t0 <= t <= t1:
                    out.append(t)
        return out

    def _years(self, t0: int, t1: int) -> list[int]:
        """Astronomical years whose *written* number (500BC, 1600) is a multiple of n.

        Written numbering keeps labels round on both sides of the BC/AD boundary. Since there is no year zero,
        the gap across that boundary is one year short of the others (100BC to 100 is 199 years).
        """
        y0 = civil_from_days(t0 // 86400)[0]
        y1 = civil_from_days(t1 // 86400)[0]
        years = []
        if y0 <= 0:  # BC: written w = 1 - y, so later years have smaller w
            w = (1 - y0) // self.n * self.n
            while w >= max(1 - min(y1, 0), 1):
                years.append(1 - w)
                w -= self.n
        if y1 >= 1:
            w = -(-max(y0, 1) // self.n) * self.n
            while w <= y1:
                years.append(w)
                w += self.n
        return years

    def has_tick(self, t: int) -> bool:
        if self.unit in _FIXED_SECONDS:
            return t % (self.n * _FIXED_SECONDS[self.unit]) == 0
        days, rem = divmod(t, 86400)
        if rem:
            return False
        y, m, d = civil_from_days(days)
        if self.unit == "day":
            return d in _days_of_month(y, m, self.n)
        if d != 1:
            return False
        if self.unit == "month":
            return (m - 1) % self.n == 0
        return m == 1 and _written_year(y) % self.n == 0

    def ordinal(self, t: int) -> int:
        """A count of this rung's ticks, for ``tick_label_every``: a tick is labelled when ordinal % n == 0."""
        if self.unit in _FIXED_SECONDS:
            return t // (self.n * _FIXED_SECONDS[self.unit])
        y, m, d = civil_from_days(t // 86400)
        if self.unit == "day":
            return (d - 1) // self.n  # counts restart each month, so the 1st is always labelled
        if self.unit == "month":
            return (12 * y + m - 1) // self.n
        return _written_year(y) // self.n


def _written_year(y: int) -> int:
    return y if y > 0 else 1 - y


def _months(t0: int, t1: int) -> list[tuple[int, int]]:
    y, m, _ = civil_from_days(t0 // 86400)
    end = civil_from_days(t1 // 86400)[:2]
    out = []
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _days_of_month(y: int, m: int, n: int) -> list[int]:
    """Day-of-month ticks: the 1st and every n days after, dropping a last tick that would sit closer than
    half a step to next month's 1st (so 10-day ticks fall on the 1st, 11th and 21st)."""
    limit = days_in_month(y, m) + 1 - n / 2
    return [d for d in range(1, days_in_month(y, m) + 1, n) if d <= limit]


def _ladder() -> tuple[Rung, ...]:
    rungs = [Rung("second", n) for n in (1, 2, 5, 10, 15, 30)]
    rungs += [Rung("minute", n) for n in (1, 2, 5, 10, 15, 30)]
    rungs += [Rung("hour", n) for n in (1, 2, 3, 6, 12)]
    rungs += [Rung("day", n) for n in (1, 2, 5, 10, 15)]
    rungs += [Rung("month", n) for n in (1, 3, 6)]
    rungs += [Rung("year", n) for n in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500)]
    rungs += [Rung("year", m * 10**k) for k in range(3, 10) for m in (1, 2, 5)]
    return tuple(rungs)


LADDER: tuple[Rung, ...] = _ladder()


def nearest_rung(ideal_seconds: float) -> Rung:
    """The rung nearest the ideal interval, by ratio; an exact tie goes to the smaller rung."""
    return min(LADDER, key=lambda r: abs(math.log(r.nominal_seconds / ideal_seconds)))


def label_text(t: int, precision: Precision) -> str:
    """A tick label at the precision of its rung (§10.2): 1610, 1986-04, 1986-04-26, 14:00, 01:23, 01:23:44."""
    value = DateValue.from_seconds(t, precision)
    if precision <= Precision.DAY:
        return str(value)
    clock = f"{value.hour:02d}:{value.minute:02d}"
    return clock + (f":{value.second:02d}" if precision is Precision.SECOND else "")


@dataclass(frozen=True)
class TickMark:
    seconds: int
    x: float
    major: bool  # on the label rung, so drawn longer (§10.2)
    label: str | None  # None for a minor tick, or a major tick whose text gave way at a paper edge
    label_x0: float = 0.0  # left edge of the label, kept inside the paper
    label_width: float = 0.0


@dataclass(frozen=True)
class TickPlan:
    rung: Rung
    label_rung: Rung | None  # None when tick_label_every overrides the ladder
    marks: tuple[TickMark, ...]
    coarsened: bool  # labels moved further up the ladder to clear their text
    crowded: bool  # labels still overlap (only possible with a tick_label_every override)


def plan_ticks(
    t0: int,
    t1: int,
    x_of: Callable[[int], float],
    length_mm: float,
    mm_per_second: float,
    target_mm: float,
    label_every: int | None,
    measure: Callable[[str], float],
    min_gap_mm: float,
) -> TickPlan:
    rung = nearest_rung(target_mm / mm_per_second)
    times = rung.ticks(t0, t1)

    def marks_for(is_labelled: Callable[[int], bool], precision: Precision) -> list[TickMark]:
        out = []
        for t in times:
            x = x_of(t)
            if not is_labelled(t):
                out.append(TickMark(t, x, False, None))
                continue
            text = label_text(t, precision)
            width = measure(text)
            out.append(TickMark(t, x, True, text, x - width / 2, width))  # centred on its tick
        return out

    def overlaps(marks: list[TickMark]) -> bool:
        labelled = [m for m in marks if m.label is not None]
        return any(b.label_x0 < a.label_x0 + a.label_width + min_gap_mm for a, b in zip(labelled, labelled[1:], strict=False))

    def keep_on_paper(marks: list[TickMark]) -> tuple[TickMark, ...]:
        """Shift the end labels inward onto the paper (§4.1). The spacing decision above was made on centred
        labels, so if a shifted end label now runs into its neighbour, the neighbour's text gives way."""
        labelled = [i for i, m in enumerate(marks) if m.label is not None]
        for end, inner in ((labelled[:1], labelled[1:2]), (labelled[-1:], labelled[-2:-1])):
            if not end:
                continue
            m = marks[end[0]]
            x0 = min(max(m.label_x0, 0.0), max(length_mm - m.label_width, 0.0))
            marks[end[0]] = TickMark(m.seconds, m.x, True, m.label, x0, m.label_width)
            if inner and inner[0] != end[0]:
                a, b = sorted((marks[end[0]], marks[inner[0]]), key=lambda k: k.x)
                if b.label_x0 < a.label_x0 + a.label_width + min_gap_mm:
                    n = marks[inner[0]]
                    marks[inner[0]] = TickMark(n.seconds, n.x, True, None)
        return tuple(marks)

    if label_every is not None:
        marks = marks_for(lambda t: rung.ordinal(t) % label_every == 0, rung.precision)
        return TickPlan(rung, None, keep_on_paper(marks), coarsened=False, crowded=overlaps(marks))

    candidates = [r for r in LADDER if r.nominal_seconds > rung.nominal_seconds and rung.contains_all_ticks_of(r)]
    for i, label_rung in enumerate(candidates):
        marks = marks_for(label_rung.has_tick, label_rung.precision)
        if not overlaps(marks):
            return TickPlan(rung, label_rung, keep_on_paper(marks), coarsened=i > 0, crowded=False)
    return TickPlan(rung, None, tuple(marks_for(lambda t: False, rung.precision)), coarsened=True, crowded=False)
