"""``axitime convert-font``: an outline font (TrueType, OpenType or Adobe Type 1) as an SVG font that a timeline
can name with ``font="….svg"`` (language spec §3.8).

The SVG font format libaxitl reads is the one Hershey Text uses: a ``<font>`` with one ``<glyph>`` per character,
each holding its advance width and its shape as path data, in font units with y pointing up and the baseline
at y = 0. That is the coordinate system TrueType and Type 1 glyphs are already drawn in, so each glyph's
outline converts straight across.

The result is an *outline* font: a pen plotter draws each letter as its outline, so letters come out hollow.
That suits large text such as a title (§16). Small text is clearer in a single-stroke font like the built-in
Hershey fonts.

Reading the font file is host I/O, which is why this lives in axitime rather than libaxitl: the converted SVG is
an ordinary custom font, fetched through ``resolve`` like any other.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from fontTools import agl
from fontTools.pens.svgPathPen import SVGPathPen

from libaxitl.units import format_number


class FontConvertError(ValueError):
    """A font file that can't be converted. The message is written for the author."""


@dataclass
class Converted:
    svg: str
    family: str
    units_per_em: float
    characters: int  # how many characters the SVG font has
    missing: list[str] = field(default_factory=list)  # asked for with characters=, but not in the font
    skipped: list[str] = field(default_factory=list)  # in the font, but whose glyph couldn't be drawn


@dataclass
class _Source:
    family: str
    units_per_em: float
    ascent: float
    descent: float  # negative: below the baseline
    glyphs: object  # glyph name -> a glyph that draws to a pen and has a width (after drawing, for Type 1)
    cmap: dict[int, str]  # code point -> glyph name
    notices: list[str]


def _kind(data: bytes) -> str:
    if data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"ttcf", b"wOFF", b"wOF2"):
        return "sfnt"
    if data[:2] == b"\x80\x01" or data[:2] == b"%!":
        return "type1"
    raise FontConvertError(
        "this isn't a font axitime can read: give it a TrueType or OpenType font (.ttf, .otf, .ttc, .woff) or an "
        "Adobe Type 1 font (.pfa, .pfb)"
    )


def _sfnt(path: Path, index: int) -> _Source:
    from fontTools.ttLib import TTFont, TTLibError

    try:
        with path.open("rb") as f:
            collection = f.read(4) == b"ttcf"
        if collection:
            from fontTools.ttLib import TTCollection

            count = len(TTCollection(str(path), lazy=True).fonts)
            if not 0 <= index < count:
                raise FontConvertError(f"this collection holds {count} fonts, numbered 0 to {count - 1}; pick one with --index")
            font = TTFont(str(path), fontNumber=index, lazy=True)
        else:
            if index:
                raise FontConvertError("--index picks a font from a collection (.ttc), and this file holds just one font")
            font = TTFont(str(path), lazy=True)
    except TTLibError as exc:
        raise FontConvertError(f"can't read this font: {exc}") from None
    except ImportError as exc:  # WOFF2 needs brotli
        raise FontConvertError(f"can't read this font without an extra library ({exc}); convert it to .ttf first") from None
    cmap = font.getBestCmap()
    if not cmap:
        raise FontConvertError("this font has no Unicode character map, so its glyphs can't be matched to letters")
    names = font["name"]
    notices = [str(r) for i in (0, 13, 14) if (r := names.getDebugName(i))]
    ascent, descent = (font["hhea"].ascent, font["hhea"].descent) if "hhea" in font else (0.8, -0.2)
    return _Source(
        family=names.getBestFullName() or names.getBestFamilyName() or path.stem,
        units_per_em=float(font["head"].unitsPerEm),
        ascent=float(ascent),
        descent=float(descent),
        glyphs=font.getGlyphSet(),
        cmap=dict(cmap),
        notices=notices,
    )


def _type1(path: Path) -> _Source:
    from fontTools.t1Lib import T1Error, T1Font

    try:
        font = T1Font(str(path))
        font.parse()
    except (T1Error, AssertionError, KeyError, ValueError) as exc:
        raise FontConvertError(f"can't read this Type 1 font: {exc or type(exc).__name__}") from None
    info = font["FontInfo"] if "FontInfo" in font.font else {}
    matrix = font["FontMatrix"] if "FontMatrix" in font.font else [0.001]
    charstrings = font["CharStrings"]
    encoding = font.font.get("Encoding")
    by_name = {}
    if isinstance(encoding, list):  # a font-specific encoding: codes stand for Latin-1 characters when a name says nothing
        for code, name in enumerate(encoding):
            if name != ".notdef":
                by_name.setdefault(name, code)
    cmap: dict[int, str] = {}
    for name in sorted(charstrings.keys()):
        if name == ".notdef" or "." in name:  # .notdef, and variants such as a.sc, which would claim a's place
            continue
        text = agl.toUnicode(name)
        if len(text) != 1 and name in by_name:
            text = chr(by_name[name])
        if len(text) == 1:
            cmap.setdefault(ord(text), name)
    if not cmap:
        raise FontConvertError("none of this Type 1 font's glyph names says which character it is")
    bbox = font.font.get("FontBBox") or [0, -200, 0, 800]
    notices = [str(info[k]) for k in ("Notice", "Copyright") if k in info]
    return _Source(
        family=str(info.get("FullName") or info.get("FamilyName") or font["FontName"]),
        units_per_em=float(round(1 / matrix[0])) if matrix and matrix[0] else 1000.0,
        ascent=float(bbox[3]),
        descent=float(bbox[1]),
        glyphs=charstrings,
        cmap=cmap,
        notices=notices,
    )


def _wanted(code: int) -> bool:
    """Characters an SVG font can hold: not control characters, surrogates or noncharacters (all invalid XML)."""
    if code & 0xFFFE == 0xFFFE or 0xFDD0 <= code <= 0xFDEF:
        return False
    return unicodedata.category(chr(code)) not in ("Cc", "Cs")


def _number(value: float) -> str:
    return format_number(round(value, 2))


def _comment(text: str) -> str:
    return text.replace("--", "- -").replace("\n", " ").strip()


def convert_font(path: str | Path, characters: str | None = None, index: int = 0) -> Converted:
    """Convert the font at ``path``: every character it maps, or only ``characters`` if given."""
    path = Path(path)
    try:
        with path.open("rb") as f:
            head = f.read(4)
    except OSError as exc:
        raise FontConvertError(f"can't read {path}: {exc.strerror or exc}") from None
    source = _sfnt(path, index) if _kind(head) == "sfnt" else _type1(path)

    if characters is None:
        codes = sorted(c for c in source.cmap if _wanted(c))
        missing = []
    else:
        asked = list(dict.fromkeys(c for c in characters if not c.isspace() or c == " "))
        codes = sorted(ord(c) for c in asked if ord(c) in source.cmap)
        missing = [c for c in asked if ord(c) not in source.cmap]

    glyphs = []
    skipped = []
    space_advance = None
    for code in codes:
        name = source.cmap[code]
        glyph = source.glyphs[name]
        pen = SVGPathPen(source.glyphs, ntos=_number)
        try:
            glyph.draw(pen)
        except Exception as exc:  # a glyph the outline reader can't follow is left out, not fatal
            skipped.append(f"{chr(code)} ({name}): {exc or type(exc).__name__}")
            continue
        advance = float(getattr(glyph, "width", 0) or 0)
        if code == 0x20:
            space_advance = advance
        d = pen.getCommands()
        glyphs.append(
            f"<glyph unicode={quoteattr(chr(code))} glyph-name={quoteattr(name)} horiz-adv-x=\"{_number(advance)}\""
            + (f' d="{d}"' if d else "")
            + "/>"
        )
    if not glyphs:
        raise FontConvertError("none of the characters asked for are in this font" if characters else
                               "this font has no glyphs that could be converted")

    family = source.family
    default_advance = space_advance if space_advance is not None else source.units_per_em / 2
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- {escape(_comment(f'{family}, converted from {path.name} by axitime convert-font.'))} -->",
        "<!-- Each glyph is the font's outline, so a pen plotter draws its letters hollow. -->",
    ]
    lines += [f"<!-- {escape(_comment(n))} -->" for n in source.notices]
    lines += [
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1">',
        "<defs>",
        f'<font id={quoteattr(re.sub(r"[^A-Za-z0-9_.-]+", "-", family).strip("-") or "font")} '
        f'horiz-adv-x="{_number(default_advance)}">',
        f"<font-face font-family={quoteattr(family)} units-per-em=\"{_number(source.units_per_em)}\" "
        f'ascent="{_number(source.ascent)}" descent="{_number(source.descent)}"/>',
        *glyphs,
        "</font>",
        "</defs>",
        "</svg>",
        "",
    ]
    return Converted("\n".join(lines), family, source.units_per_em, len(glyphs), missing, skipped)
