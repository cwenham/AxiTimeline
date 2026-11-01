"""A title's letters in an outline font, hatched inside with font_fill= (§16.1)."""

import pytest

from libaxitl import AxitlError, Fill, Stage, draw, layout, parse
from libaxitl.fonts import BUILTIN_FONTS, load_builtin_font, parse_svg_font

T = "timeline start=1900 end=1999 length=1000 width=210 ticks=off\n"


def font(*glyphs):
    body = "".join(glyphs)
    return f"""<svg xmlns="http://www.w3.org/2000/svg"><defs><font horiz-adv-x="500">
  <font-face units-per-em="1000" font-family="Blocks"/>{body}</font></defs></svg>"""


# An O (a square ring, its counter wound the other way) and an I (a bar): closed outlines, as convert-font writes.
O = '<glyph unicode="O" horiz-adv-x="700" d="M100 0 L600 0 L600 700 L100 700 Z M250 200 L250 500 L450 500 L450 200 Z"/>'
I = '<glyph unicode="I" horiz-adv-x="350" d="M100 0 L250 0 L250 700 L100 700 Z"/>'
SPACE = '<glyph unicode=" " horiz-adv-x="300"/>'
FILES = {"blocks.svg": font(O, I, SPACE)}


def title(source):
    return parse(T + source, FILES.__getitem__).document.title


def error_codes(source):
    with pytest.raises(AxitlError) as info:
        parse(T + source, FILES.__getitem__)
    return [d.code for d in info.value.errors]


def drawn(source):
    L = layout(parse(T + source, FILES.__getitem__).document)
    strokes = [s for s in draw(L).strokes if s.stage is Stage.TITLES]
    return L.title, strokes


def in_font_units(text, point):
    """A page point as font units of the placed text: x from its origin, y up from its baseline."""
    scale = text.shaped.scale
    return (point[0] - text.x) / scale, (text.y - point[1]) / scale


# -- outline fonts -----------------------------------------------------------------------------------------------


def test_a_font_of_closed_outlines_is_an_outline_font():
    assert parse_svg_font(FILES["blocks.svg"], "blocks.svg").outline
    # A subpath back where it started is closed, with or without Z.
    assert parse_svg_font(font('<glyph unicode="L" d="M0 0 L100 0 L100 700 L0 0"/>'), "x").outline


def test_one_open_stroke_makes_it_a_single_line_font():
    assert not parse_svg_font(font(O, '<glyph unicode="-" d="M0 300 L400 300"/>'), "x").outline


@pytest.mark.parametrize("name", BUILTIN_FONTS)
def test_the_built_in_fonts_are_single_line_fonts(name):
    assert not load_builtin_font(name).outline


# -- the language ------------------------------------------------------------------------------------------------


def test_font_fill_defaults_to_none():
    t = title('title "OI" font="blocks.svg"\n')
    assert (t.font_fill, t.subtitle_font_fill) == (Fill.NONE, Fill.NONE)


def test_a_subtitle_in_an_outline_font_is_filled_like_the_title():
    t = title('title "OI" font="blocks.svg" font_fill=solid subtitle="IO"\n')
    assert (t.font_fill, t.subtitle_font_fill) == (Fill.SOLID, Fill.SOLID)
    t = title('title "OI" font="blocks.svg" font_fill=solid subtitle="IO" subtitle_font_fill=none\n')
    assert t.subtitle_font_fill is Fill.NONE
    t = title('title "OI" font="blocks.svg" subtitle="IO" subtitle_font_fill=diagonal\n')
    assert (t.font_fill, t.subtitle_font_fill) == (Fill.NONE, Fill.DIAGONAL)


def test_a_subtitle_in_a_single_line_font_or_none_at_all_isnt_filled():
    t = title('title "OI" font="blocks.svg" font_fill=solid subtitle="Sub" subtitle_font=HersheySans1\n')
    assert t.subtitle_font_fill is Fill.NONE
    assert title('title "OI" font="blocks.svg" font_fill=solid\n').subtitle_font_fill is Fill.NONE


def test_font_fill_none_is_allowed_on_any_font():
    assert title('title "T" font_fill=none\n').font_fill is Fill.NONE


@pytest.mark.parametrize("source, code", [
    ('title "T" font_fill=solid\n', "not-an-outline-font"),
    ('title "OI" font="blocks.svg" subtitle="S" subtitle_font=HersheySans1 subtitle_font_fill=solid\n',
     "not-an-outline-font"),
    ('title "OI" font="blocks.svg" font_fill=stripes\n', "bad-value"),
    ('title "OI" font="blocks.svg" subtitle_font_fill=solid\n', "bad-value"),
])
def test_errors(source, code):
    assert error_codes(source) == [code]


def test_the_error_says_why_and_what_to_use_instead():
    with pytest.raises(AxitlError) as info:
        parse(T + 'title "T" font=HersheySerifMed font_fill=solid\n')
    message = info.value.errors[0].message
    assert "'HersheySerifMed' draws its letters as single lines" in message and "convert-font" in message


# -- drawing -----------------------------------------------------------------------------------------------------


def test_without_font_fill_only_the_outlines_are_drawn():
    _, strokes = drawn('title "OI" font="blocks.svg"\n')
    assert len(strokes) == 3  # the O's two outlines and the I's one


def test_font_fill_hatches_inside_the_letters_and_leaves_the_counter_empty():
    block, strokes = drawn('title "OI" blue font="blocks.svg" font_fill=solid\n')
    (text,) = block.texts
    hatch = [s for s in strokes if len(s.points) == 2]
    assert len(strokes) - len(hatch) == 3 and len(hatch) > 20
    assert {s.pen for s in strokes} == {"blue"}
    for s in hatch:
        (x0, y0), (x1, y1) = (in_font_units(text, p) for p in s.points)
        assert y0 == pytest.approx(y1)  # solid: level lines
        assert 0 - 1e-6 <= y0 <= 700 + 1e-6
        mid = (x0 + x1) / 2
        assert not (250 < mid < 450 and 200 < y0 < 500)  # not across the O's counter
        assert 100 - 1e-6 <= min(x0, x1) and max(x0, x1) <= 1050 + 1e-6  # within the O and the I (700 + 350)
    rows = sorted({round(s.points[0][1], 6) for s in hatch})
    assert min(b - a for a, b in zip(rows, rows[1:])) == pytest.approx(0.4)
    # Across the counter's height, a row is cut into three: either side of the counter, and the I.
    middle = [s for s in hatch if 250 < in_font_units(text, s.points[0])[1] < 450]
    assert len(middle) == 3 * len({round(s.points[0][1], 6) for s in middle})


def test_the_subtitle_follows_its_own_fill():
    def subtitle_strokes(source):
        block, strokes = drawn(source)
        return [s.points for s in strokes if min(y for _, y in s.points) > block.texts[0].y + 1e-6]

    single = ' subtitle="Sub" subtitle_font=HersheySans1\n'
    assert subtitle_strokes('title "OI" font="blocks.svg" font_fill=solid' + single) == subtitle_strokes(
        'title "OI" font="blocks.svg"' + single
    )
    filled = subtitle_strokes('title "OI" font="blocks.svg" font_fill=solid subtitle="IO"\n')
    hollow = subtitle_strokes('title "OI" font="blocks.svg" font_fill=solid subtitle="IO" subtitle_font_fill=none\n')
    assert len(hollow) == 3 and len(filled) > 10


def test_font_fill_doesnt_move_anything():
    plain, _ = drawn('title "OI" font="blocks.svg" subtitle="IO"\n')
    filled, _ = drawn('title "OI" font="blocks.svg" font_fill=crosshatch subtitle="IO"\n')
    assert filled.box == plain.box
    assert [(t.x, t.y) for t in filled.texts] == [(t.x, t.y) for t in plain.texts]
