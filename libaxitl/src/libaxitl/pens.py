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

# Screen colours for previews; on paper the pen decides. They are also what an illustration's colours are
# matched against with pens=auto (§3.5).
_COLOURS = {
    "red": "#c62828", "orange": "#ef6c00", "yellow": "#f9a825", "green": "#2e7d32", "blue": "#1565c0",
    "indigo": "#3949ab", "violet": "#6a1b9a", "black": "#212121", "grey": "#757575",
}


def pen_colour(pen: str) -> str:
    """The colour a pen is previewed in, as #rrggbb."""
    if pen in _COLOURS:
        return _COLOURS[pen]
    if pen.startswith("fountain-"):
        return _COLOURS.get(pen.removeprefix("fountain-"), "#212121")
    grade = pen.removesuffix("-pencil")
    if grade in PENCIL_GRADES:  # soft grades darker, hard grades lighter
        shade = 0x55 + PENCIL_GRADES.index(grade) * 6
        return f"#{shade:02x}{shade:02x}{shade + 8:02x}"
    return "#212121"


def is_pen(word: str) -> bool:
    return word in _PEN_SET


def suggest_pen(word: str) -> str | None:
    """The pen the author most likely meant, for an error message."""
    for pen in PENS:
        if pen.lower() == word.lower():
            return pen
    close = difflib.get_close_matches(word, PENS, n=1, cutoff=0.7)
    return close[0] if close else None
