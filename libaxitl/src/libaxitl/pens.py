"""The closed pen vocabulary (language spec §3.4)."""

from __future__ import annotations

import difflib

BASE_COLOURS: tuple[str, ...] = ("red", "orange", "yellow", "green", "blue", "indigo", "violet", "black", "grey")
PENCIL_GRADES: tuple[str, ...] = ("6B", "5B", "4B", "3B", "2B", "B", "HB", "F", "H", "2H", "3H", "4H", "5H", "6H")

PENS: tuple[str, ...] = (
    BASE_COLOURS
    + tuple(f"{grade}-pencil" for grade in PENCIL_GRADES)
    + tuple(f"fountain-{colour}" for colour in BASE_COLOURS)
)
DEFAULT_PEN = "black"
_PEN_SET = frozenset(PENS)


def is_pen(word: str) -> bool:
    return word in _PEN_SET


def suggest_pen(word: str) -> str | None:
    """The pen the author most likely meant, for an error message."""
    for pen in PENS:
        if pen.lower() == word.lower():
            return pen
    close = difflib.get_close_matches(word, PENS, n=1, cutoff=0.7)
    return close[0] if close else None
