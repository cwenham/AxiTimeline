import pytest

from libaxitl.fonts import BUILTIN_FONTS, FontError, load_builtin_font, parse_svg_font
from libaxitl.svgpath import to_path_data
from libaxitl.text import drawable_text, shape

CUSTOM_FONT = """<svg xmlns="http://www.w3.org/2000/svg"><defs>
<font id="Hand" horiz-adv-x="500">
<font-face font-family="Robin's Hand" units-per-em="1000"/>
<glyph unicode="H" horiz-adv-x="600" d="M 100 0 L 100 700 M 500 0 L 500 700 M 100 350 L 500 350"/>
<glyph unicode="H" horiz-adv-x="999" d="M 0 0 L 0 1"/>
<glyph unicode="i" d="M 100 0 L 100 400"/>
<glyph unicode="ffi" d="M 0 0 L 1 1"/>
</font></defs></svg>"""


@pytest.mark.parametrize("name", BUILTIN_FONTS)
def test_every_builtin_font_loads_with_the_basics(name):
    font = load_builtin_font(name)
    assert font.units_per_em == 1000
    for char in "0123456789-:?' ":
        assert font.has(char), f"{name} lacks {char!r}"
    assert 0 < font.x_height < font.cap_height < font.units_per_em
    assert font.descender < 0


def test_hershey_sans_metrics_come_from_the_glyphs_not_the_header():
    font = load_builtin_font("HersheySans1")
    assert font.cap_height == 662  # the header claims 500
    assert font.x_height == 441  # the header claims 300
    assert font.glyphs["A"].advance == 567


def test_unknown_builtin_name():
    with pytest.raises(FontError):
        load_builtin_font("Comic Sans")


def test_width_is_the_sum_of_advances_at_em_size():
    font = load_builtin_font("HersheySans1")
    shaped = shape(font, "AA", 4.0)
    assert shaped.width == pytest.approx(2 * 567 / 1000 * 4.0)
    assert shaped.cap_height == pytest.approx(0.662 * 4.0)


def test_ink_box_is_in_mm_with_y_down():
    font = load_builtin_font("HersheySans1")
    left, top, right, bottom = shape(font, "A", 10.0).ink_box()
    assert (left, top, right, bottom) == pytest.approx((1.26, -6.62, 6.30, 0.0))
    assert shape(font, " ", 10.0).ink_box() is None


def test_strokes_are_placed_at_the_pen_origin():
    font = load_builtin_font("HersheySans1")
    path = to_path_data(shape(font, "A", 10.0).segments(100, 50))
    assert path.startswith("M 103.78 43.38 L 101.26 50")


@pytest.mark.parametrize(
    "text, drawn",
    [
        ("Newton’s", "Newton's"),  # curly apostrophe: punctuation table
        ("Tōkyō", "Tokyo"),  # macrons: accent stripped
        ("wait…", "wait..."),  # ellipsis
        ("Łódź", "Lódz"),  # ł has no decomposition (table); ó is in the font; ź is stripped
        ("1 BC", "1 BC"),  # non-breaking space is in this font, so it is kept
        ("ﬁne", "fine"),  # ﬁ ligature via NFKD
        ("Ω", "?"),  # Greek: nothing better than ?
    ],
)
def test_missing_characters_are_replaced(text, drawn):
    font = load_builtin_font("HersheySans1")
    assert drawable_text(font, text)[0] == drawn


def test_each_distinct_replacement_is_reported_once():
    font = load_builtin_font("HersheySans1")
    _, replacements = drawable_text(font, "’a’bō")
    assert [(r.original, r.replacement) for r in replacements] == [("’", "'"), ("ō", "o")]


def test_custom_svg_font():
    font = parse_svg_font(CUSTOM_FONT, "fonts/hand.svg")
    assert font.family == "Robin's Hand"
    assert font.glyphs["H"].advance == 600  # first definition wins, as in Hershey Text
    assert font.glyphs["i"].advance == 500  # falls back to the font's default advance
    assert "ffi" not in font.glyphs  # ligatures are not used
    assert font.cap_height == 700
    # a space the font lacks takes the default advance, silently
    assert shape(font, "H i", 10.0).width == pytest.approx((600 + 500 + 500) / 100)
    assert drawable_text(font, "H i")[1] == ()


@pytest.mark.parametrize(
    "content, fragment",
    [
        ("<svg", "not readable"),
        ('<svg xmlns="http://www.w3.org/2000/svg"/>', "no SVG <font>"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><font><glyph unicode="a"/></font></svg>', "no drawable"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><font><glyph unicode="a" d="M0 0 L x"/></font></svg>', "unreadable"),
    ],
)
def test_unusable_custom_fonts(content, fragment):
    with pytest.raises(FontError, match=fragment):
        parse_svg_font(content, "bad.svg")
