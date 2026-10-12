"""Text shaping: the one function both layout (to measure) and render (to draw) use for every label.

Because layout and render share :func:`shape`, the extent layout measured for a label is exactly the extent
render draws. A label's width is the sum of its glyphs' advance widths (no kerning: none of the bundled fonts
has any). ``font_size`` is the em size (language spec §3.8).

Characters the font lacks are replaced, trying in order: typographic punctuation by its plain equivalent; a
letter by its unaccented base letter; ``?``. Each replacement is reported so the caller can warn.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .fonts import Font
from .svgpath import Segment, transform

# Step 1: typographic punctuation and spacing → plain equivalents.
_PUNCTUATION = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "ʼ": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"', "»": '"',
    "‹": "'", "›": "'",
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    "…": "...", "•": "-", "·": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ",
}
# Step 2a: letters with no Unicode decomposition to a base letter.
_LETTERS = {
    "ł": "l", "Ł": "L", "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE",
    "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ħ": "h", "Ħ": "H",
    "ı": "i", "ß": "ss", "þ": "th", "Þ": "Th", "ð": "d", "Ð": "D",
}


@dataclass(frozen=True)
class Replacement:
    original: str
    replacement: str


def _candidates(char: str) -> list[str]:
    out = []
    if char in _PUNCTUATION:
        out.append(_PUNCTUATION[char])
    if char in _LETTERS:
        out.append(_LETTERS[char])
    # Step 2b: decompose (NFKD also unpacks ligatures like ﬁ) and drop the combining accents.
    stripped = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
    if stripped and stripped != char:
        out.append(stripped)
    out.append("?")
    return out


def drawable_text(font: Font, text: str) -> tuple[str, tuple[Replacement, ...]]:
    """The text as it will be drawn in ``font``, plus every replacement made (one per distinct character)."""
    out: list[str] = []
    replaced: dict[str, str] = {}
    for char in text:
        if font.has(char) or (char == " "):
            out.append(char)
            continue
        if char not in replaced:
            replaced[char] = next((c for c in _candidates(char) if all(font.has(x) for x in c)), "")
        out.append(replaced[char])
    return "".join(out), tuple(Replacement(k, v) for k, v in replaced.items())


@dataclass(frozen=True)
class ShapedText:
    """A label laid out in one font at one size, with its pen origin at the left end of the baseline.

    Physical values are millimetres in SVG orientation (y down), so ink above the baseline has negative y.
    """

    font: Font
    size_mm: float
    text: str
    offsets: tuple[float, ...]  # x of each character's origin, in font units
    advance_units: float
    replacements: tuple[Replacement, ...]

    @property
    def scale(self) -> float:
        return self.size_mm / self.font.units_per_em

    @property
    def width(self) -> float:
        """Advance width in mm: how far the next label could start."""
        return self.advance_units * self.scale

    @property
    def cap_height(self) -> float:
        return self.font.cap_height * self.scale

    @property
    def descender(self) -> float:
        """Depth below the baseline in mm (positive)."""
        return -self.font.descender * self.scale

    def ink_box(self) -> tuple[float, float, float, float] | None:
        """Ink extents (left, top, right, bottom) in mm relative to the pen origin, or None if nothing is drawn."""
        boxes = []
        for char, x in zip(self.text, self.offsets, strict=True):
            glyph = self.font.glyphs.get(char)
            if glyph and glyph.ink:
                x0, y0, x1, y1 = glyph.ink
                boxes.append((x + x0, y0, x + x1, y1))
        if not boxes:
            return None
        s = self.scale
        return (
            min(b[0] for b in boxes) * s,
            -max(b[3] for b in boxes) * s,
            max(b[2] for b in boxes) * s,
            -min(b[1] for b in boxes) * s,
        )

    def segments(self, x: float, y: float) -> tuple[Segment, ...]:
        """The label's strokes with its pen origin (left end of the baseline) at (x, y) mm, y down."""
        out: list[Segment] = []
        for char, offset in zip(self.text, self.offsets, strict=True):
            glyph = self.font.glyphs.get(char)
            if glyph and glyph.segments:
                out.extend(transform(glyph.segments, self.scale, x + offset * self.scale, y))
        return tuple(out)


def shape(font: Font, text: str, size_mm: float) -> ShapedText:
    """Lay out ``text`` in ``font`` at ``size_mm`` (the em size)."""
    drawn, replacements = drawable_text(font, text)
    offsets = []
    pen = 0.0
    for char in drawn:
        offsets.append(pen)
        glyph = font.glyphs.get(char)
        pen += glyph.advance if glyph else font.default_advance
    return ShapedText(font, size_mm, drawn, tuple(offsets), pen, replacements)
