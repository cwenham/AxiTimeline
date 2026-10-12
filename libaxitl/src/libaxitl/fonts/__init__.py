"""SVG stroke fonts: the bundled Hershey Text set and custom ``.svg`` fonts (language spec §3.8).

An SVG font is a ``<font>`` element holding one ``<glyph>`` per character, each with an advance width and its
strokes as path data, in font units with y pointing up and the baseline at y = 0. This module reads that
format the way Hershey Text does (first definition of a character wins; a glyph without its own advance uses
the font's default), and measures vertical metrics from the glyph shapes, since the bundled fonts' declared
``cap-height``/``x-height`` are placeholders.

Reading the bundled files is the library reading its own package data, which the interpreter spec allows: it
is identical on every host and pinned by the library version.
"""

from __future__ import annotations

import functools
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Mapping

from ..svgpath import PathError, Segment, bounding_box, parse_path

BUILTIN_FONTS: tuple[str, ...] = (
    "HersheySans1",
    "HersheySansMed",
    "HersheySerifMed",
    "HersheySerifMedItalic",
    "HersheySerifBold",
    "HersheySerifBoldItalic",
    "HersheyScript1",
    "HersheyScriptMed",
    "HersheyGothEnglish",
    "EMSAllure",
    "EMSElfin",
    "EMSFelix",
    "EMSNixish",
    "EMSNixishItalic",
    "EMSOsmotron",
    "EMSReadability",
    "EMSReadabilityItalic",
    "EMSTech",
)
DEFAULT_FONT = "HersheySans1"


class FontError(ValueError):
    """A font file that can't be used. The message is written for the author."""


@dataclass(frozen=True)
class Glyph:
    advance: float
    segments: tuple[Segment, ...]
    ink: tuple[float, float, float, float] | None  # (min x, min y, max x, max y) in font units, y-up


@dataclass(frozen=True)
class Font:
    """A parsed stroke font. Lengths are in font units (``units_per_em`` to the em), y-up, baseline at 0."""

    name: str
    family: str
    units_per_em: float
    default_advance: float
    glyphs: Mapping[str, Glyph]
    cap_height: float
    x_height: float
    ascender: float
    descender: float  # negative: below the baseline

    def has(self, char: str) -> bool:
        return char in self.glyphs


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise FontError(f"'{value}' is not a number") from None


def parse_svg_font(content: str | bytes, name: str) -> Font:
    """Parse SVG font content. ``name`` is used in messages and as the font's identity."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FontError(f"font '{name}' is not readable SVG ({exc})") from None
    font_el = next((el for el in root.iter() if _local(el.tag) == "font"), None)
    if font_el is None:
        raise FontError(f"'{name}' contains no SVG <font> element, so it isn't an SVG stroke font")
    default_advance = _number(font_el.get("horiz-adv-x"), 0.0)
    units_per_em = 1000.0
    family = name
    glyphs: dict[str, Glyph] = {}
    for el in font_el:
        tag = _local(el.tag)
        if tag == "font-face":
            units_per_em = _number(el.get("units-per-em"), 1000.0)
            family = el.get("font-family") or name
        elif tag == "glyph":
            char = el.get("unicode")
            if char is None or len(char) != 1 or char in glyphs:
                continue  # ligatures are not used; the first definition of a character wins, as in Hershey Text
            try:
                segments = parse_path(el.get("d") or "")
            except PathError as exc:
                raise FontError(f"font '{name}', glyph {char!r}: {exc}") from None
            advance = _number(el.get("horiz-adv-x"), default_advance)
            glyphs[char] = Glyph(advance, segments, bounding_box(segments))
    if units_per_em <= 0:
        raise FontError(f"font '{name}' has a units-per-em of {units_per_em}")
    if not any(g.ink for g in glyphs.values()):
        raise FontError(f"font '{name}' has no drawable glyphs")

    def top(chars: str, fallback: float) -> float:
        tops = [glyphs[c].ink[3] for c in chars if c in glyphs and glyphs[c].ink]
        return max(tops) if tops else fallback * units_per_em

    def bottom(chars: str, fallback: float) -> float:
        bottoms = [glyphs[c].ink[1] for c in chars if c in glyphs and glyphs[c].ink]
        return min(bottoms) if bottoms else fallback * units_per_em

    letters_digits = "".join(chr(c) for c in range(0x21, 0x7F) if chr(c).isalnum())
    return Font(
        name=name,
        family=family,
        units_per_em=units_per_em,
        default_advance=default_advance,
        glyphs=MappingProxyType(glyphs),
        cap_height=top("H", 0.7) if "H" in glyphs else top("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 0.7),
        x_height=top("x", 0.5) if "x" in glyphs else top("acemnorsuvwxz", 0.5),
        ascender=top(letters_digits, 0.8),
        descender=min(bottom("gjpqy", -0.2), 0.0),
    )


def is_builtin_font(name: str) -> bool:
    return name in BUILTIN_FONTS


@functools.cache
def load_builtin_font(name: str) -> Font:
    """Load one of the bundled fonts by its built-in name."""
    if name not in BUILTIN_FONTS:
        raise FontError(f"'{name}' is not a built-in font")
    content = resources.files(__package__).joinpath("data", f"{name}.svg").read_bytes()
    return parse_svg_font(content, name)
