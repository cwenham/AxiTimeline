"""The title and credits (§16): what the declarations say, where they go, what keeps clear of them, and drawing."""

import pytest

from libaxitl import AxitlError, Horizontal, Side, Stage, draw, layout, parse
from libaxitl.geometry import keep_inside

T = "timeline start=1900 end=1999 length=1000 width=210 ticks=off\n"
APPLE = '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="40mm"><path d="M0 0 L 20 40"/></svg>'  # 0.5
LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10"><rect x="1" y="1" width="28" height="8"/></svg>'
FILES = {"apple.svg": APPLE, "logo.svg": LOGO}
CREDITS = """credits illustration(logo.svg) {
    heading "Design, Contraption, and Research"
    "Christopher Wenham, 2026"
    "https://github.com/cwenham/AxiTimeline"
    heading "Sources"
    "Dates checked against Wikipedia"
}
"""


def doc(source, files=FILES):
    return parse(source, files.__getitem__).document


def lay(source, files=FILES):
    return layout(doc(source, files))


def error_codes(source, files=FILES, stage=parse):
    with pytest.raises(AxitlError) as info:
        parse(source, files.__getitem__) if stage is parse else lay(source, files)
    return [d.code for d in info.value.errors]


def ink_left(placed):
    return placed.x + placed.shaped.ink_box()[0]


def ink_right(placed):
    return placed.x + placed.shaped.ink_box()[2]


def ink(block):
    """Where the block's ink reaches: (left, top, right, bottom)."""
    boxes = [(t.x + i[0], t.y + i[1], t.x + i[2], t.y + i[3]) for t in block.texts for i in [t.shaped.ink_box()]]
    if block.illustration_box:
        b = block.illustration_box
        boxes.append((b.x0, b.y0, b.x1, b.y1))
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def cap_top(placed):
    return placed.y - placed.shaped.cap_height


# -- the declarations ------------------------------------------------------------------------------------------


def test_title_defaults():
    t = doc(T + 'title "A Century"\n').title
    assert (t.text, t.subtitle, t.pen, t.font, t.font_size_mm) == ("A Century", "", "black", "HersheySans1", 12.0)
    assert (t.subtitle_font, t.subtitle_font_size_mm) == ("HersheySans1", 6.0)
    assert (t.illustration, t.illustration_at, t.align, t.margin_mm, t.gap_mm) == (
        None, Horizontal.LEFT, Horizontal.LEFT, 5.0, 4.0
    )


def test_title_settings_over_several_lines():
    t = doc(
        T + 'title "A Century" blue\n'
        '    subtitle="Lives and wars" subtitle_font=HersheySerifMed subtitle_font_size=5mm\n'
        "    font=HersheyScript1 font_size=2cm margin=8 gap=3\n"
        "    illustration(apple.svg at=right height=30mm)\n"
    ).title
    assert (t.pen, t.font, t.font_size_mm, t.subtitle) == ("blue", "HersheyScript1", 20.0, "Lives and wars")
    assert (t.subtitle_font, t.subtitle_font_size_mm, t.margin_mm, t.gap_mm) == ("HersheySerifMed", 5.0, 8.0, 3.0)
    assert (t.illustration.name, t.illustration.height_mm, t.illustration_at) == ("apple.svg", 30.0, Horizontal.RIGHT)


def test_credits_lines_and_defaults():
    c = doc("timeline start=1900 end=1999 length=1m width=210 font_size=3mm\n" + CREDITS).credits
    assert [(line.text, line.heading) for line in c.lines] == [
        ("Design, Contraption, and Research", True),
        ("Christopher Wenham, 2026", False),
        ("https://github.com/cwenham/AxiTimeline", False),  # a // inside quotes is not a comment
        ("Sources", True),
        ("Dates checked against Wikipedia", False),
    ]
    assert (c.pen, c.font, c.font_size_mm, c.heading_font, c.heading_font_size_mm) == (
        "black", "HersheySans1", 3.0, "HersheySans1", 3.75
    )
    # In the bottom-right corner, the logo goes on the right and the lines are aligned to the right.
    assert (c.max_height_mm, c.illustration.name, c.illustration_at, c.align) == (
        None, "logo.svg", Horizontal.RIGHT, Horizontal.RIGHT
    )


def test_credits_settings():
    c = doc(
        T + "credits grey font_size=3mm heading_font=HersheySansMed heading_font_size=3mm max_height=2cm\n"
        '    illustration(logo.svg at=left) margin=0 align=left {\n    "Only line"\n}\n'
    ).credits
    assert (c.pen, c.heading_font, c.heading_font_size_mm, c.max_height_mm) == ("grey", "HersheySansMed", 3.0, 20.0)
    assert (c.illustration_at, c.align, c.margin_mm) == (Horizontal.LEFT, Horizontal.LEFT, 0.0)


def test_title_and_credits_can_come_from_an_include():
    files = dict(FILES, **{"common/credits.axitl": CREDITS.replace("logo.svg", "../logo.svg")})
    d = doc(T + 'include "common/credits.axitl" priority=2 side=above\n', files)
    assert d.credits.illustration.name == "logo.svg" and len(d.credits.lines) == 5


@pytest.mark.parametrize(
    "source, code",
    [
        ('title "A"\ntitle "B"\n', "duplicate-title"),
        (CREDITS + CREDITS, "duplicate-credits"),
        ('group "G" 1900-1950 {\n  title "A"\n}\n', "nested-title"),
        ('group "G" 1900-1950 {\n  credits {\n  "x"\n  }\n}\n', "nested-credits"),
        ("credits\n", "bad-value"),
        ("credits {\n}\n", "bad-value"),
        ('title ""\n', "bad-value"),
        ('title "A" subtitle_font_size=3mm\n', "bad-value"),
        ('title "A" margin=-2\n', "bad-value"),
        ('title "A" illustration(apple.svg at=top)\n', "bad-value"),
        ('title "A" align=centre\n', "bad-value"),
        ('title "A" illustration(apple.svg side=left)\n', "unknown-parameter"),
        ('title "A" colour=red\n', "unknown-parameter"),
        ('title "A" purple\n', "unknown-pen"),
        ('title "A" red blue\n', "duplicate-pen"),
        ('credits illustration(logo.svg height=20mm) {\n"x"\n}\n', "unknown-parameter"),
        ('credits max_height=0 {\n"x"\n}\n', "bad-value"),
        ('event "E" 1950 illustration(apple.svg at=left)\n', "unknown-parameter"),
        ('credits {\n  heading Sources\n}\n', "syntax"),
        ('credits {\n  ## Sources\n}\n', "syntax"),
        ('credits {\n  "x"\n', "syntax"),
        ('title "A" {\n}\n', "syntax"),
        ('title "A" illustration(missing.svg)\n', "missing-illustration"),
    ],
)
def test_errors(source, code):
    assert code in error_codes(T + source)


def test_error_messages_point_the_author_somewhere_useful():
    def message(source):
        with pytest.raises(AxitlError) as info:
            parse(T + source, FILES.__getitem__)
        return info.value.errors[0].message

    assert "heading" in message('credits {\n  ## Sources\n}\n')
    assert "credits" in message('credits {\n  "x"\n')
    assert "max_height=" in message('credits illustration(logo.svg height=20mm) {\n"x"\n}\n')
    assert "at=left" in message('title "A" illustration(apple.svg side=left)\n')
    assert "placed automatically" in message('event "E" 1950 illustration(apple.svg at=left)\n')
    assert "subtitle=" in message('title "A" {\n}\n')


def test_an_illustration_can_continue_any_declaration_on_an_indented_line():
    d = doc(T + 'title "A"\n    illustration(apple.svg)\n\nevent "E" 1950\n    illustration(apple.svg)\n')
    assert d.title.illustration.name == "apple.svg"
    assert d.entities[0].illustration.name == "apple.svg"
    assert error_codes(T + 'title "A"\nillustration(apple.svg)\n') == ["unindented-parameter"]
    assert error_codes(T + '\n    illustration(apple.svg)\n') == ["orphan-parameter"]


def test_missing_characters_are_a_warning():
    result = parse(T + 'title "Ōsaka" subtitle="Tōkyō"\ncredits {\n  "Kyōto"\n}\n')
    assert [d.code for d in result.diagnostics] == ["missing-glyph"] * 3


# -- where they go -------------------------------------------------------------------------------------------


def test_the_title_sits_in_the_top_left_corner_inside_its_margin():
    L = lay(T + 'title "A Century" subtitle="Lives and wars" margin=6\n')
    t = L.title
    assert t.side is Side.ABOVE and t.pen == "black"
    assert ink(t)[:2] == pytest.approx((6.0, 6.0))  # margins are measured to the ink
    assert all(t.box.x0 <= x.box.x0 and x.box.y1 <= t.box.y1 for x in t.texts)  # the box holds the line boxes
    title, subtitle = t.texts
    assert ink_left(title) == pytest.approx(ink_left(subtitle))  # left-aligned on their ink
    assert subtitle.box.y0 > title.y  # the subtitle is under the title
    assert subtitle.shaped.size_mm == 6.0


def test_the_credits_sit_in_the_bottom_right_corner():
    L = lay(T + CREDITS)
    c = L.credits
    assert c.side is Side.BELOW
    assert ink(c)[2:] == pytest.approx((1000 - 5, 210 - 5))
    rights = [ink_right(t) for t in c.texts]  # aligned to the right on their ink
    assert max(rights) - min(rights) < 1e-9
    ys = [t.y for t in c.texts]
    assert ys == sorted(ys)
    # A heading after the first line gets more space above it than an ordinary line.
    assert ys[3] - ys[2] > ys[2] - ys[1]


def test_the_logo_is_as_tall_as_the_stack_a_gap_to_its_right_and_in_the_corner():
    c = lay(T + CREDITS).credits
    stack_top, stack_bottom = cap_top(c.texts[0]), c.texts[-1].y
    box = c.illustration_box
    assert box.y0 == pytest.approx(stack_top) and box.y1 == pytest.approx(stack_bottom)
    assert box.width == pytest.approx(box.height * 3)  # the logo's own aspect ratio
    assert box.x0 - ink_right(c.texts[0]) == pytest.approx(4.0)  # the right-aligned lines end a gap before it
    assert box.x1 == pytest.approx(1000 - 5)


def test_an_illustration_on_the_left_and_lines_aligned_left():
    c = lay(T + CREDITS.replace("logo.svg)", "logo.svg at=left) gap=2 align=left")).credits
    text_left = min(ink_left(t) for t in c.texts)
    assert max(ink_left(t) for t in c.texts) == pytest.approx(text_left)
    assert text_left - c.illustration_box.x1 == pytest.approx(2.0)
    assert max(ink_right(t) for t in c.texts) == pytest.approx(1000 - 5)
    # The lines can be aligned either way whichever side the logo is on.
    c = lay(T + CREDITS.replace("logo.svg)", "logo.svg at=left)")).credits
    assert max(ink_right(t) for t in c.texts) == pytest.approx(min(ink_right(t) for t in c.texts))
    assert min(ink_left(t) for t in c.texts) - c.illustration_box.x1 == pytest.approx(4.0)


def test_a_title_aligned_right():
    t = lay(T + 'title "A Century" subtitle="Lives and wars" align=right illustration(apple.svg at=right)\n').title
    title, subtitle = t.texts
    assert ink_right(title) == pytest.approx(ink_right(subtitle))
    assert ink_left(title) == pytest.approx(5.0)  # the longer line still starts at the margin
    assert t.illustration_box.x0 - ink_right(title) == pytest.approx(4.0)


def test_a_title_illustration_matches_the_text_or_its_own_height():
    t = lay(T + 'title "A Century" subtitle="Lives" illustration(apple.svg)\n').title
    assert t.illustration_box.y0 == pytest.approx(cap_top(t.texts[0]))
    assert t.illustration_box.y1 == pytest.approx(t.texts[1].y)
    t = lay(T + 'title "A Century" illustration(apple.svg height=40mm)\n').title
    assert t.illustration_box.height == pytest.approx(40.0) and t.illustration_box.width == pytest.approx(20.0)
    middle = (cap_top(t.texts[0]) + t.texts[0].y) / 2  # the text is centred against a taller illustration
    assert (t.illustration_box.y0 + t.illustration_box.y1) / 2 == pytest.approx(middle)
    assert ink(t)[1] == pytest.approx(5.0)


def test_max_height_scales_the_whole_stack_down_but_never_up():
    natural = lay(T + CREDITS).credits
    height = natural.texts[-1].y - cap_top(natural.texts[0])
    small = lay(T + CREDITS.replace("credits ", "credits max_height=15mm ")).credits
    assert small.texts[-1].y - cap_top(small.texts[0]) == pytest.approx(15.0)
    k = 15.0 / height
    assert [t.shaped.size_mm for t in small.texts] == pytest.approx([t.shaped.size_mm * k for t in natural.texts])
    assert small.illustration_box.height == pytest.approx(15.0)
    roomy = lay(T + CREDITS.replace("credits ", f"credits max_height={height + 10}mm ")).credits
    assert [t.shaped.size_mm for t in roomy.texts] == [t.shaped.size_mm for t in natural.texts]


# -- keeping clear of them -----------------------------------------------------------------------------------


def test_bars_keep_out_of_the_lanes_the_title_crosses():
    people = "".join(f'^person "P{i}" 1900-1930\n' for i in range(9))
    L = lay(T + 'title "A Century" font_size=10mm\n' + people)
    lanes = sorted(b.lane for b in L.bars)
    assert lanes == list(range(9))
    for b in L.bars:
        assert b.y1 < L.title.box.y0 or b.y0 > L.title.box.y1 + 1.5 - 1e-9
    # Past the end of the title, the same lanes are free again.
    later = lay(T + 'title "A Century" font_size=10mm\n' + people + people.replace("1900-1930", "1960-1990")
                .replace('"P', '"Q'))
    assert max(b.lane for b in later.bars if b.entity.label.startswith("Q")) == 8
    # The title's reservation doesn't make its side look full.
    assert later.above.lanes_used == 9 and lay(T + 'title "A"\n').above.lanes_used == 0


def test_no_room_for_a_bar_beside_the_title_is_fatal():
    people = "".join(f'^person "P{i}" 1900-1930\n' for i in range(12))
    assert "no-room" in error_codes(T + 'title "A Century" font_size=10mm\n' + people, stage=layout)


def test_a_title_that_doesnt_fit_is_fatal():
    assert error_codes(T + 'title "A" font_size=120mm\n', stage=layout) == ["no-room-for-title"]
    assert error_codes(T + 'title "' + "W" * 120 + '"\n', stage=layout) == ["no-room-for-title"]
    assert error_codes(T + CREDITS.replace("credits ", "credits font_size=20mm "), stage=layout) == [
        "no-room-for-credits"
    ]


def test_flags_and_poles_keep_clear_of_the_title():
    # Stacked events under the title: the flags climb towards it, and none may touch it.
    events = "".join(f'^event "Event number {i}" 1905-0{i + 1}\n' for i in range(8))
    L = lay(T + 'title "A Century of Clever People" font_size=10mm\n' + events)
    keep = L.title.box.padded(1.5)
    for e in L.events:
        assert not e.flag_box.overlaps(keep) or "label-collision" in [d.code for d in L.diagnostics]
        for a, b in e.pole_segments:
            assert not keep_inside([(e.x, a), (e.x, b)], keep.padded(-0.01)), e.entity.label


def test_a_graph_is_broken_around_the_title_and_credits():
    graph = 'graph "" {\n  1900 0\n  1950 100\n  1999 -100\n}\n'
    L = lay(T + 'title "A Century of Clever People"\n' + CREDITS + graph)
    texts = [t.box for block in (L.title, L.credits) for t in block.texts] + [L.credits.illustration_box]
    for line in L.graphs[0].line:
        for box in texts:
            assert not keep_inside(line, box.padded(-0.01))


def test_the_title_and_credits_pens_are_in_the_job():
    L = lay(T + 'title "A" blue\n' + CREDITS.replace("credits ", "credits violet "))
    assert L.pens == ("black", "blue", "violet")


# -- drawing --------------------------------------------------------------------------------------------------


def test_they_are_drawn_last_before_the_crop_marks_in_their_own_pens():
    d = draw(lay(T + 'title "A" blue illustration(apple.svg)\n' + CREDITS.replace("credits ", "credits violet ")))
    titles = [s for s in d.strokes if s.stage is Stage.TITLES]
    assert titles and {s.pen for s in titles} == {"blue", "violet"}
    stages = [s.stage for s in d.strokes]
    assert stages.index(Stage.TITLES) > max(i for i, s in enumerate(stages) if s is Stage.AXIS)
    assert all(s is Stage.CROP_MARKS for s in stages[stages.index(Stage.CROP_MARKS):])


def test_the_logo_is_drawn_in_its_box_with_a_warning_for_fills():
    L = lay(T + CREDITS)
    d = draw(L)
    box = L.credits.illustration_box.padded(0.01)
    logo = [s for s in d.strokes if s.stage is Stage.TITLES and box.x0 <= s.points[0][0] <= box.x1]
    assert logo and all(box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1 for s in logo for x, y in s.points)
    assert [(w.code, w.location.line) for w in d.diagnostics] == [("illustration-content", 2)]
