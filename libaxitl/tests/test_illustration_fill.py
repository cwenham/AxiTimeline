"""An illustration's filled shapes hatched (fill=) and its colours drawn in pens of their own (pens=), §3.5."""

import pytest

from libaxitl import AxitlError, Fill, Stage, draw, layout, parse
from libaxitl.colours import ColourError, nearest_pen, parse_colour
from libaxitl.hatch import Outline
from libaxitl.pens import BASE_COLOURS, pen_colour

T = "timeline start=1900 end=1999 length=1000 width=210 ticks=off\n"
# A 30 x 10 logo: an orange "O" (a ring, its hole wound the other way), a black bar, a white patch and a thin
# black frame that is stroked, not filled.
LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10">
  <path fill="#ff6600" d="M1 1 H9 V9 H1 Z M3 3 V7 H7 V3 Z"/>
  <rect x="12" y="1" width="6" height="8" style="fill:#000000;stroke:none"/>
  <rect x="21" y="1" width="6" height="8" fill="white"/>
  <rect x="0.2" y="0.2" width="29.6" height="9.6" fill="none" stroke="black" stroke-width="0.1"/>
</svg>"""
GRADIENT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
  <rect width="10" height="10" fill="url(#g)"/><rect width="5" height="5" fill="#00ff00"/></svg>"""
FILES = {"logo.svg": LOGO, "gradient.svg": GRADIENT}


def ill(source):
    """The illustration of the one event in a document."""
    return parse(T + source, FILES.__getitem__).document.entities[0].illustration


def drawn(source):
    """The strokes of the one event's illustration, and the illustration's box."""
    L = layout(parse(T + source, FILES.__getitem__).document)
    d = draw(L)
    return [s for s in d.strokes if s.stage is Stage.ILLUSTRATIONS], L.events[0].illustration.box, L, d


def to_logo(box, x, y):
    """A page point as the logo's own coordinates (30 x 10 fitted into box)."""
    return (x - box.x0) * 30 / box.width, (y - box.y0) * 10 / box.height


# -- colours -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, colour", [
    ("#FF6600", "#ff6600"), ("#f60", "#ff6600"), ("rgb(255, 102, 0)", "#ff6600"), ("rgb(100%,40%,0%)", "#ff6600"),
    ("black", "#000000"), ("White", "#ffffff"), ("none", None), ("transparent", None), (None, None),
])
def test_colours_are_read_as_svg_writes_them(text, colour):
    assert parse_colour(text) == colour


@pytest.mark.parametrize("text", ["url(#g)", "currentColor", "#ff66", "chartreuse-ish"])
def test_paint_that_isnt_a_plain_colour(text):
    with pytest.raises(ColourError):
        parse_colour(text)


@pytest.mark.parametrize("colour, pen", [
    ("#ff6600", "orange"), ("#000000", "black"), ("#ff0000", "red"), ("#0000ff", "blue"), ("#808080", "grey"),
    ("#ffd700", "yellow"), ("#008000", "green"), ("#000080", "blue"), ("#4b0082", "indigo"), ("#800080", "violet"),
])
def test_auto_takes_the_pen_with_the_nearest_reference_colour(colour, pen):
    assert nearest_pen(colour) == pen


@pytest.mark.parametrize("pen", BASE_COLOURS)
def test_a_pens_own_preview_colour_comes_back_to_it(pen):
    assert nearest_pen(pen_colour(pen)) == pen


# -- hatching inside an outline ------------------------------------------------------------------------------

RING = [[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], [(3, 3), (3, 7), (7, 7), (7, 3), (3, 3)]]
SAME_WAY = [RING[0], [(3, 3), (7, 3), (7, 7), (3, 7), (3, 3)]]


def test_a_hole_wound_the_other_way_stays_empty():
    assert Outline(RING, evenodd=False).clip([[(-1, 5), (11, 5)]]) == [[(0, 5), (3, 5)], [(7, 5), (10, 5)]]


def test_the_fill_rule_decides_a_hole_wound_the_same_way():
    assert len(Outline(SAME_WAY, evenodd=True).clip([[(-1, 5), (11, 5)]])) == 2
    (line,) = Outline(SAME_WAY, evenodd=False).clip([[(-1, 5), (11, 5)]])
    assert (line[0], line[-1]) == ((0, 5), (10, 5))


def test_open_subpaths_are_closed_for_filling_and_corners_dont_confuse_it():
    triangle = Outline([[(0, 0), (10, 10), (20, 0)]], evenodd=False)  # never closed with Z
    assert triangle.clip([[(-5, 5), (25, 5)]]) == [[(5, 5), (15, 5)]]
    assert triangle.clip([[(-5, 10), (25, 10)]]) == []  # through the apex only
    diagonal = Outline(RING, evenodd=False).clip([[(-1, -1), (11, 11)]])  # through two corners and the hole
    assert [(round(a[0], 6), round(b[0], 6)) for a, b in diagonal] == [(0, 3), (7, 10)]


def test_a_curved_line_is_cut_and_kept_in_one_piece_while_inside():
    wave = [(x / 2, 5 + (x % 2) * 0.5) for x in range(-2, 23)]
    (piece,) = Outline([RING[0]], evenodd=False).clip([wave])
    assert piece[0][0] == pytest.approx(0) and piece[-1][0] == pytest.approx(10) and len(piece) > 10


# -- the language --------------------------------------------------------------------------------------------


def test_fill_and_pens_are_set_inside_the_illustrations_parentheses():
    plain = ill('event "E" 1950 illustration(logo.svg)\n')
    assert (plain.fill, plain.pens) == (Fill.NONE, None)
    auto = ill('event "E" 1950 illustration(logo.svg fill=solid pens=auto)\n')
    # White is the paper, so it gets no pen.
    assert (auto.fill, auto.pens) == (Fill.SOLID, (("#000000", "black"), ("#ff6600", "orange")))
    chosen = ill('event "E" 1950 illustration(logo.svg pens="#ff6600:fountain-orange, black:HB-pencil")\n')
    assert chosen.pens == (("#000000", "HB-pencil"), ("#ff6600", "fountain-orange"))


def test_title_and_credits_illustrations_take_them_too():
    d = parse(T + 'title "T" illustration(logo.svg fill=diagonal pens=auto)\n'
              'credits illustration(logo.svg fill=solid) {\n  "x"\n}\n', FILES.__getitem__).document
    assert (d.title.illustration.fill, d.credits.illustration.fill) == (Fill.DIAGONAL, Fill.SOLID)


@pytest.mark.parametrize("item, code", [
    ("fill=stripes", "bad-value"),
    ("pens=orange", "bad-value"),
    ('pens="#ff6600"', "bad-value"),
    ('pens="#ff660:orange"', "bad-value"),
    ('pens="#ff6600:purple"', "unknown-pen"),
])
def test_bad_values(item, code):
    with pytest.raises(AxitlError) as info:
        parse(T + f'event "E" 1950 illustration(logo.svg {item})\n', FILES.__getitem__)
    assert [d.code for d in info.value.errors] == [code]


def test_warnings_for_a_colour_not_in_the_drawing_and_for_paint_that_isnt_a_colour():
    result = parse(T + 'event "E" 1950 illustration(logo.svg pens="#123456:red")\n', FILES.__getitem__)
    assert [d.code for d in result.diagnostics] == ["illustration-colour"]
    assert "#123456" in result.diagnostics[0].message
    result = parse(T + 'event "E" 1950 illustration(gradient.svg pens=auto)\n', FILES.__getitem__)
    assert [d.code for d in result.diagnostics] == ["illustration-colour"]
    assert result.document.entities[0].illustration.pens == (("#00ff00", "green"),)


# -- drawing -------------------------------------------------------------------------------------------------


def test_without_fill_or_pens_nothing_changes():
    strokes, box, L, d = drawn('event "E" 1950 illustration(logo.svg)\n')
    assert {s.pen for s in strokes} == {"black"} and len(strokes) == 5  # five outlines: the ring has two
    assert L.pens == ("black",)
    assert [w.message for w in d.diagnostics if w.code == "illustration-content"] == [
        "illustration 'logo.svg': filled shapes are drawn as their outlines only (fill= hatches them)"
    ]


def test_fill_hatches_inside_each_filled_shape_and_leaves_holes_and_white_alone():
    strokes, box, _, d = drawn('event "E" 1950 illustration(logo.svg fill=solid)\n')
    assert not [w for w in d.diagnostics if w.code == "illustration-content"]
    hatch = [s for s in strokes if len(s.points) == 2 and s.points[0][1] == s.points[1][1]]
    assert len(hatch) > 20
    for s in hatch:
        for x, y in s.points:
            lx, ly = to_logo(box, x, y)
            assert not (21 < lx < 27)  # the white patch isn't hatched
            assert not (3 + 1e-6 < lx < 7 - 1e-6 and 3 + 1e-6 < ly < 7 - 1e-6)  # nor the O's hole
    spacing = sorted({round(s.points[0][1], 6) for s in hatch})
    assert min(b - a for a, b in zip(spacing, spacing[1:])) == pytest.approx(0.4)  # solid: dense, 0.4mm apart


def test_pens_auto_draws_each_colour_in_its_own_pen():
    strokes, box, L, _ = drawn('event "E" 1950 illustration(logo.svg fill=solid pens=auto)\n')
    by_pen = {}
    for s in strokes:
        lx, _ = to_logo(box, *s.points[0])
        by_pen.setdefault(s.pen, []).append(lx)
    assert set(by_pen) == {"orange", "black"}
    assert all(lx < 10 for lx in by_pen["orange"])  # the O, outline and hatch
    assert not any(21 < lx < 27 for lx in by_pen["black"])  # the white patch isn't drawn at all
    assert "orange" in L.pens


def test_a_colour_pens_doesnt_name_is_in_the_owners_pen():
    strokes, *_ = drawn('event "E" 1950 blue illustration(logo.svg pens="#ff6600:red")\n')
    assert {s.pen for s in strokes} == {"red", "blue"}
