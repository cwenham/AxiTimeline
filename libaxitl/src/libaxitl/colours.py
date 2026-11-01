"""Colours in an illustration's SVG, and the pens they are drawn in (language spec §3.5).

A plotter has no colours, only pens, so an illustration's colours become pens: all of them its owner's pen
unless ``pens=`` says otherwise. ``pens=auto`` gives each colour the base pen (red to grey, not pencils or
fountain pens) with the nearest reference colour, measured in CIELAB so that "nearest" is roughly what the eye
sees. Each pen's references are its preview colour and the plain colours its name usually means: a pen's
preview colour alone won't do, since the previews are muted shades and pure red would come out nearer orange.
"""

from __future__ import annotations

import math
import re

from .pens import BASE_COLOURS, pen_colour

WHITE = "#ffffff"  # the colour of the paper: nothing white is hatched, and with pens= nothing white is drawn

# The CSS colour keywords an SVG editor is likely to write; anything else is written as a number.
_NAMED = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080", "grey": "#808080", "gray": "#808080",
    "silver": "#c0c0c0", "maroon": "#800000", "olive": "#808000", "lime": "#00ff00", "aqua": "#00ffff",
    "cyan": "#00ffff", "teal": "#008080", "navy": "#000080", "fuchsia": "#ff00ff", "magenta": "#ff00ff",
    "brown": "#a52a2a", "pink": "#ffc0cb", "gold": "#ffd700", "indigo": "#4b0082", "violet": "#ee82ee",
    "darkgrey": "#a9a9a9", "darkgray": "#a9a9a9", "lightgrey": "#d3d3d3", "lightgray": "#d3d3d3",
}
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(r"^rgb\(\s*([^,\s]+)\s*,?\s*([^,\s]+)\s*,?\s*([^,\s)]+)\s*\)$")


class ColourError(ValueError):
    pass


def parse_colour(text: str | None) -> str | None:
    """An SVG paint as #rrggbb, or None for none. Raises ColourError for paint that isn't a plain colour
    (a gradient, a pattern, currentColor)."""
    if text is None:
        return None
    value = text.strip().lower()
    if value in ("none", "transparent", ""):
        return None
    if value in _NAMED:
        return _NAMED[value]
    m = _HEX.match(value)
    if m:
        digits = m.group(1)
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return f"#{digits}"
    m = _RGB.match(value)
    if m:
        channels = []
        for part in m.groups():
            try:
                number = float(part[:-1]) * 2.55 if part.endswith("%") else float(part)
            except ValueError:
                raise ColourError(text) from None
            channels.append(max(0, min(255, round(number))))
        return "#" + "".join(f"{c:02x}" for c in channels)
    raise ColourError(text)


def _lab(colour: str) -> tuple[float, float, float]:
    """#rrggbb (sRGB) in CIELAB, D65."""

    def linear(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(int(colour[i : i + 2], 16)) for i in (1, 3, 5))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


# What each base pen stands for, besides its preview colour (language spec §3.5 lists the same).
REFERENCES: dict[str, tuple[str, ...]] = {
    "red": ("#ff0000", "#b22222"),
    "orange": ("#ff8000", "#ffa500"),
    "yellow": ("#ffff00", "#ffd700"),
    "green": ("#00ff00", "#008000"),
    "blue": ("#0000ff", "#000080"),
    "indigo": ("#4b0082",),
    "violet": ("#8000ff", "#800080", "#ee82ee"),
    "black": ("#000000",),
    "grey": ("#808080", "#c0c0c0"),
}


def nearest_pen(colour: str) -> str:
    """The base pen with the reference colour nearest to ``colour``; a tie goes to the earlier pen in §3.4's
    order."""
    target = _lab(colour)
    return min(
        BASE_COLOURS,
        key=lambda pen: min(math.dist(target, _lab(c)) for c in (pen_colour(pen), *REFERENCES[pen])),
    )
