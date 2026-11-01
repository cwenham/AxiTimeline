"""convert-font: TrueType, OpenType and Type 1 fonts as SVG fonts that libaxitl reads and draws."""

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.misc import eexec
from fontTools.misc.psCharStrings import T1CharString
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont

from axitime.cli import EXIT_ERRORS, EXIT_OK, EXIT_USAGE, main
from axitime.fontconvert import FontConvertError, convert_font
from libaxitl import Stage, draw, layout, parse
from libaxitl.fonts import parse_svg_font

TRIANGLE = [(0, 0), (300, 700), (600, 0)]  # the letter A, in font units: 600 wide, 700 tall


def _draw_triangle(pen):
    pen.moveTo(TRIANGLE[0])
    for point in TRIANGLE[1:]:
        pen.lineTo(point)
    pen.closePath()


def build_sfnt(path: Path, family: str = "Test Sans", cff: bool = False) -> Path:
    """A two-character font: A (a triangle) and space, at 1000 units to the em."""
    fb = FontBuilder(1000, isTTF=not cff)
    fb.setupGlyphOrder([".notdef", "A", "space"])
    fb.setupCharacterMap({ord("A"): "A", ord(" "): "space"})
    if cff:
        pens = {}
        for name in (".notdef", "A", "space"):
            pens[name] = T2CharStringPen(600 if name == "A" else 250, None)
        _draw_triangle(pens["A"])
        fb.setupCFF(family.replace(" ", ""), {"FullName": family}, {n: p.getCharString() for n, p in pens.items()}, {})
    else:
        glyphs = {}
        for name in (".notdef", "A", "space"):
            pen = TTGlyphPen(None)
            if name == "A":
                _draw_triangle(pen)
            glyphs[name] = pen.glyph()
        fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (600, 0), "space": (250, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular", "copyright": "Made for a test -- not for use"})
    fb.setupOS2()
    fb.setupPost()
    fb.save(str(path))
    return path


def build_type1(path: Path) -> Path:
    """A Type 1 font (.pfa) with A, space and é, written out by hand as the format is: a clear-text header and
    an eexec-encrypted private part holding encrypted charstrings."""

    def charstring(program):
        cs = T1CharString(program=program)
        cs.compile()
        return eexec.encrypt(b"\0\0\0\0" + cs.bytecode, 4330)[0]

    glyphs = {
        ".notdef": [0, 500, "hsbw", "endchar"],
        "space": [0, 250, "hsbw", "endchar"],
        "A": [0, 600, "hsbw", 0, 0, "rmoveto", 300, 700, "rlineto", 300, -700, "rlineto", "closepath", "endchar"],
        "eacute": [0, 500, "hsbw", 50, 0, "rmoveto", 400, 0, "rlineto", "closepath", "endchar"],
        "A.alt": [0, 900, "hsbw", "endchar"],  # a variant, which must not take A's place
    }
    private = [
        b"dup /Private 8 dict dup begin", b"/RD{string currentfile exch readstring pop}executeonly def",
        b"/ND{noaccess def}executeonly def", b"/NP{noaccess put}executeonly def", b"/lenIV 4 def",
        b"/BlueValues [] def", b"/password 5839 def", b"/Subrs 0 array ND",
        b"2 index /CharStrings %d dict dup begin" % len(glyphs),
    ]
    for name, program in glyphs.items():
        encrypted = charstring(program)
        private.append(b"/%s %d RD " % (name.encode(), len(encrypted)) + encrypted + b" ND")
    private += [b"end", b"end", b"readonly put", b"noaccess put", b"dup /FontName get exch definefont pop",
                b"mark currentfile closefile"]
    clear = (
        b"%!PS-AdobeFont-1.0: TestOne 001.000\n11 dict begin\n/FontInfo 3 dict dup begin\n"
        b"/FamilyName (Test One) readonly def\n/Notice (Made for a test) readonly def\nend readonly def\n"
        b"/FontName /TestOne def\n/Encoding StandardEncoding def\n/PaintType 0 def\n/FontType 1 def\n"
        b"/FontMatrix [0.001 0 0 0.001 0 0] readonly def\n/FontBBox {0 -200 600 800} readonly def\n"
        b"currentdict end\ncurrentfile eexec\n"
    )
    body = eexec.encrypt(b"\0\0\0\0" + b"\n".join(private) + b"\n", 55665)[0]
    path.write_bytes(clear + body.hex().encode() + b"\n" + (b"0" * 64 + b"\n") * 8 + b"cleartomark\n")
    return path


@pytest.mark.parametrize("kind", ["truetype", "opentype", "type1"])
def test_a_font_converts_to_an_svg_font_libaxitl_reads(tmp_path, kind):
    if kind == "type1":
        path = build_type1(tmp_path / "test.pfa")
    else:
        path = build_sfnt(tmp_path / f"test.{'otf' if kind == 'opentype' else 'ttf'}", cff=kind == "opentype")
    converted = convert_font(path)
    font = parse_svg_font(converted.svg, "test.svg")
    assert font.units_per_em == 1000
    a = font.glyphs["A"]
    assert a.advance == 600 and a.ink == (0, 0, 600, 700)  # the outline, unchanged and y-up
    assert font.glyphs[" "].advance == 250 and font.glyphs[" "].ink is None
    assert font.cap_height == 700
    expected = {"A", " "} | ({"é"} if kind == "type1" else set())
    assert set(font.glyphs) == expected and converted.characters == len(expected)
    assert converted.skipped == []
    assert "-->" not in converted.svg.split("<svg", 1)[1]  # the notices are in comments before the font
    assert "Made for a test" in converted.svg


def test_the_converted_font_draws_a_title(tmp_path):
    svg = convert_font(build_sfnt(tmp_path / "test.ttf")).svg
    source = 'timeline start=1900 end=1999 length=1m width=210\ntitle "AAA" font="title.svg" font_size=10mm\n'
    result = parse(source, {"title.svg": svg}.__getitem__)
    strokes = [s for s in draw(layout(result.document)).strokes if s.stage is Stage.TITLES]
    assert len(strokes) == 3  # each A is one closed outline: a pen draws it hollow
    assert all(s.points[0] == s.points[-1] for s in strokes)
    assert [r.kind for r in result.resources] == ["font"]  # fetched through resolve, so in the job hash


def test_only_the_characters_asked_for(tmp_path):
    converted = convert_font(build_sfnt(tmp_path / "test.ttf"), characters="AAz")
    assert converted.characters == 1 and converted.missing == ["z"]
    with pytest.raises(FontConvertError, match="none of the characters"):
        convert_font(tmp_path / "test.ttf", characters="xyz")


def test_a_font_from_a_collection(tmp_path):
    collection = TTCollection()
    collection.fonts = [
        TTFont(str(build_sfnt(tmp_path / f"{n}.ttf", family=f"Test {n}"))) for n in ("Light", "Heavy")
    ]
    collection.save(str(tmp_path / "both.ttc"))
    assert convert_font(tmp_path / "both.ttc", index=1).family == "Test Heavy"
    with pytest.raises(FontConvertError, match="holds 2 fonts"):
        convert_font(tmp_path / "both.ttc", index=2)
    with pytest.raises(FontConvertError, match="collection"):
        convert_font(tmp_path / "Light.ttf", index=1)


def test_not_a_font(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    with pytest.raises(FontConvertError, match="TrueType or OpenType"):
        convert_font(tmp_path / "notes.txt")


def test_the_command(tmp_path, capsys, monkeypatch):
    build_sfnt(tmp_path / "Test.ttf")
    monkeypatch.chdir(tmp_path)
    assert main(["convert-font", "Test.ttf"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "wrote Test.svg: 2 characters of Test Sans, 1000 units to the em" in out
    assert 'font="Test.svg"' in out
    assert parse_svg_font((tmp_path / "Test.svg").read_bytes(), "Test.svg").has("A")
    assert main(["convert-font", "Test.ttf", "-o", "out/title.svg", "--characters", "Az"]) == EXIT_ERRORS
    assert "can't write it" in capsys.readouterr().err
    (tmp_path / "out").mkdir()
    assert main(["convert-font", "Test.ttf", "-o", "out/title.svg", "--characters", "Az"]) == EXIT_OK
    assert "not in the font, so left out: z" in capsys.readouterr().out
    assert main(["convert-font", "Test.ttf", "-o", "title.ttf"]) == EXIT_USAGE
    assert main(["convert-font", "missing.ttf"]) == EXIT_ERRORS
