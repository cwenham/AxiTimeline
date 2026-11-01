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

from .fonts import Font, font_variant
from .markup import Span, Spans, parse_inline
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
    """A label laid out at one size, with its pen origin at the left end of the baseline.

    ``font`` is the label's own font. With inline formatting (§3.11) some characters may be drawn in a bold or
    italic cut of it (``fonts`` says which, one per character), and stretches may be struck through. Physical
    values are millimetres in SVG orientation (y down), so ink above the baseline has negative y.
    """

    font: Font
    size_mm: float
    text: str
    offsets: tuple[float, ...]  # x of each character's origin, in ``font``'s units
    advance_units: float
    replacements: tuple[Replacement, ...]
    fonts: tuple[Font, ...] = ()  # each character's font; empty when they are all in ``font``
    strikes: tuple[tuple[float, float, float], ...] = ()  # (from x, to x, y up), in ``font``'s units

    @property
    def scale(self) -> float:
        return self.size_mm / self.font.units_per_em

    def char_fonts(self) -> tuple[Font, ...]:
        return self.fonts or (self.font,) * len(self.text)

    def used_fonts(self) -> list[Font]:
        """The label's font, then any other cut it uses, each once, in order of first use."""
        out = [self.font]
        for f in self.fonts:
            if f not in out:
                out.append(f)
        return out

    @property
    def width(self) -> float:
        """Advance width in mm: how far the next label could start."""
        return self.advance_units * self.scale

    @property
    def cap_height(self) -> float:
        return max(f.cap_height * self.size_mm / f.units_per_em for f in self.used_fonts())

    @property
    def ascender(self) -> float:
        """Height above the baseline in mm (positive) that the fonts allow."""
        return max(f.ascender * self.size_mm / f.units_per_em for f in self.used_fonts())

    @property
    def descender(self) -> float:
        """Depth below the baseline in mm (positive) that the fonts allow."""
        return max(-f.descender * self.size_mm / f.units_per_em for f in self.used_fonts())

    def ink_box(self) -> tuple[float, float, float, float] | None:
        """Ink extents (left, top, right, bottom) in mm relative to the pen origin, or None if nothing is drawn."""
        boxes = []
        s = self.scale
        for char, x, f in zip(self.text, self.offsets, self.char_fonts(), strict=True):
            glyph = f.glyphs.get(char)
            if glyph and glyph.ink:
                k = self.size_mm / f.units_per_em
                x0, y0, x1, y1 = glyph.ink
                boxes.append((x * s + x0 * k, -y1 * k, x * s + x1 * k, -y0 * k))
        for x0, x1, y in self.strikes:
            boxes.append((x0 * s, -y * s, x1 * s, -y * s))
        if not boxes:
            return None
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )

    def segments(self, x: float, y: float, strikes: bool = True) -> tuple[Segment, ...]:
        """The label's strokes with its pen origin (left end of the baseline) at (x, y) mm, y down. Without
        ``strikes``, only its letters."""
        out: list[Segment] = []
        s = self.scale
        for char, offset, f in zip(self.text, self.offsets, self.char_fonts(), strict=True):
            glyph = f.glyphs.get(char)
            if glyph and glyph.segments:
                out.extend(transform(glyph.segments, self.size_mm / f.units_per_em, x + offset * s, y))
        if strikes:
            for x0, x1, h in self.strikes:
                out.extend((("M", x + x0 * s, y - h * s), ("L", x + x1 * s, y - h * s)))
        return tuple(out)


STRIKE_HEIGHT = 0.5  # a strikethrough's height above the baseline, as a fraction of the font's x-height


def shape(font: Font, text: str | Spans, size_mm: float, markup: bool = False) -> ShapedText:
    """Lay out ``text`` in ``font`` at ``size_mm`` (the em size). With ``markup``, a string's inline formatting
    (§3.11) is read first; ``text`` may also be spans already read."""
    if isinstance(text, tuple):
        spans = text
    elif markup:
        spans = parse_inline(text)
    else:
        spans = (Span(text),) if text else ()
    chars: list[str] = []
    fonts: list[Font] = []
    offsets: list[float] = []
    strikes: list[tuple[float, float, float]] = []
    replaced: dict[str, str] = {}
    pen = 0.0
    strike_from = None
    for span in spans:
        f = font_variant(font, span.bold, span.italic)[0] if span.bold or span.italic else font
        drawn, replacements = drawable_text(f, span.text)
        for r in replacements:
            replaced.setdefault(r.original, r.replacement)
        if span.strike and strike_from is None:
            strike_from = pen
        elif not span.strike and strike_from is not None:
            strikes.append((strike_from, pen, font.x_height * STRIKE_HEIGHT))
            strike_from = None
        k = font.units_per_em / f.units_per_em  # f's units to font's
        for char in drawn:
            chars.append(char)
            fonts.append(f)
            offsets.append(pen)
            glyph = f.glyphs.get(char)
            pen += (glyph.advance if glyph else f.default_advance) * k
    if strike_from is not None:
        strikes.append((strike_from, pen, font.x_height * STRIKE_HEIGHT))
    return ShapedText(
        font, size_mm, "".join(chars), tuple(offsets), pen, tuple(Replacement(k, v) for k, v in replaced.items()),
        tuple(fonts) if any(f is not font for f in fonts) else (), tuple(strikes),
    )
