"""Physical lengths and scale rates (language spec §14, §4).

One rule for every physical length: a bare number is millimetres; ``mm``, ``cm`` and ``m`` suffixes are
accepted with no space before them; decimals are fine. Millimetres are the canonical internal unit.
Conversion goes through ``Decimal`` so that ``0.21m`` is exactly 210.0, not 210.00000000000003.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_LENGTH = re.compile(r"^(\d+(?:\.\d*)?|\.\d+)(mm|cm|m)?$")
_FACTORS = {None: Decimal(1), "mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000)}

_SCALE = re.compile(r"^(\d+(?:\.\d*)?|\.\d+)mm/(year|day|hour|minute|second)$")
SCALE_UNITS = ("year", "day", "hour", "minute", "second")


class UnitError(ValueError):
    """A length or rate that doesn't follow the units rule. The message is written for the author."""


def parse_length(text: str) -> float:
    """Parse a physical length and return it in millimetres."""
    m = _LENGTH.match(text)
    if not m:
        if re.match(r"^-", text):
            raise UnitError(f"'{text}' is negative; lengths must be zero or more")
        if re.match(r"^[\d.]+\s+(mm|cm|m)$", text):
            raise UnitError(f"'{text}' has a space before its unit; write it without one")
        raise UnitError(
            f"'{text}' is not a length; use a number of millimetres, or add a cm or m suffix (e.g. 210, 21cm, 0.21m)"
        )
    return float(Decimal(m.group(1)) * _FACTORS[m.group(2)])


@dataclass(frozen=True)
class Scale:
    """An explicit rate such as ``5mm/year``. Conversion to mm per second happens in layout."""

    mm: float
    unit: str

    def __str__(self) -> str:
        return f"{format_number(self.mm)}mm/{self.unit}"


def parse_scale(text: str) -> Scale:
    m = _SCALE.match(text)
    if not m:
        units = ", ".join(f"mm/{u}" for u in SCALE_UNITS)
        raise UnitError(f"'{text}' is not a scale; write a rate in millimetres per time unit ({units}), e.g. 5mm/year")
    return Scale(float(Decimal(m.group(1))), m.group(2))


def format_number(value: float, places: int = 3) -> str:
    """Format a number compactly and deterministically: fixed decimal places, trailing zeros removed, no -0."""
    rounded = round(value, places)
    if rounded == 0:
        rounded = 0.0
    text = f"{rounded:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"
