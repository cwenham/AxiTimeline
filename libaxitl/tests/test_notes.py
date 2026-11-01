"""Notes (§17): paragraphs of free text on the top or bottom edge, anchored along the roll, kept clear of the title,
the credits and each other, and kept clear of by everything else."""

import pytest

from libaxitl import AxitlError, Edge, Horizontal, NoteAnchor, Side, Stage, draw, layout, parse, parse_date, shape
from libaxitl.geometry import keep_inside

T = "timeline start=1900 end=1999 length=1000 width=210 ticks=off\n"
LONG = (
    "The years between the wars were marked by an uneasy peace, economic turmoil and the rise of new ideologies "
    "across Europe, and by a great deal else besides."
)


def doc(source):
    return parse(source).document


def lay(source):
    return layout(doc(source))


def error_codes(source, stage=parse):
    with pytest.raises(AxitlError) as info:
        parse(source) if stage is parse else lay(source)
    return [d.code for d in info.value.errors]


def message(source, stage=parse):
    with pytest.raises(AxitlError) as info:
        parse(source) if stage is parse else lay(source)
    return info.value.errors[0].message


def warnings(L):
    return [d.code for d in L.diagnostics]


def ink(block):
    """Where the block's ink reaches: (left, top, right, bottom)."""
    boxes = [(t.x + i[0], t.y + i[1], t.x + i[2], t.y + i[3]) for t in block.texts for i in [t.shaped.ink_box()]]
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


# -- the declaration ----------------------------------------------------------------------------------------


def test_defaults():
    n = doc(T + 'note "Dates are Gregorian throughout."\n').notes[0]
    assert [(p.text, p.heading) for p in n.paragraphs] == [("Dates are Gregorian throughout.", False)]
    assert (n.anchor, n.edge, n.width_mm, n.align, n.margin_mm, n.clearance_mm) == (
        NoteAnchor.START, Edge.TOP, None, Horizontal.LEFT, 5.0, 25.0
    )
    assert (n.pen, n.font, n.font_size_mm, n.heading_font, n.heading_font_size_mm) == (
        "black", "HersheySans1", 4.0, "HersheySans1", 5.0
    )


def test_settings_over_several_lines():
    n = doc(
        T + 'note "x" blue\n'
        "    anchor=1945-05 edge=bottom width=8cm align=right\n"
        "    font=HersheySerifMed font_size=3mm heading_font=HersheySans1 heading_font_size=6mm\n"
        "    margin=8 clearance=10mm\n"
    ).notes[0]
    assert (n.pen, n.anchor, n.edge, n.width_mm, n.align) == ("blue", parse_date("1945-05"), Edge.BOTTOM, 80.0,
                                                              Horizontal.RIGHT)
    assert (n.font, n.font_size_mm, n.heading_font, n.heading_font_size_mm) == ("HersheySerifMed", 3.0,
                                                                                  "HersheySans1", 6.0)
    assert (n.margin_mm, n.clearance_mm) == (8.0, 10.0)


def test_font_and_size_come_from_the_timeline():
    n = doc(T.replace("ticks=off", "ticks=off font=EMSTech font_size=3mm") + 'note "x"\n').notes[0]
    assert (n.font, n.font_size_mm, n.heading_font, n.heading_font_size_mm) == ("EMSTech", 3.0, "EMSTech", 3.75)


def test_quoted_lines_together_make_a_paragraph_and_a_blank_line_ends_it():
    source = T + (
        "note anchor=middle {\n"
        '    heading "The war years"\n'
        '    "Two wars took up a tenth"   // a comment after a line\n'
        "    // a comment on its own doesn't end the paragraph\n"
        '    "of the century."\n'
        "\n"
        '    "A second    paragraph."\n'
        '    heading "Then"\n'
        '    "A third."\n'
        "}\n"
    )
    result = parse(source)
    paragraphs = result.document.notes[0].paragraphs
    assert [(p.text, p.heading, p.location.line) for p in paragraphs] == [
        ("The war years", True, 3),
        ("Two wars took up a tenth of the century.", False, 4),
        ("A second paragraph.", False, 8),  # spaces inside the text collapse, as they would in wrapping
        ("Then", True, 9),
        ("A third.", False, 10),
    ]
    assert '"Two wars took up a tenth of the century."\n' in result.flattened_text


def test_quoted_lines_join_only_inside_a_notes_body():
    d = doc(T + 'credits {\n  "a"\n  "b"\n}\nnote {\n  "c"\n  "d"\n}\n')
    assert [line.text for line in d.credits.lines] == ["a", "b"]
    assert [p.text for p in d.notes[0].paragraphs] == ["c d"]


def test_escapes_survive_joining():
    n = doc(T + 'note {\n  "a \\"quoted\\""\n  "word \\\\ here"\n}\n').notes[0]
    assert n.paragraphs[0].text == 'a "quoted" word \\ here'


def test_a_note_can_come_from_an_include_and_there_can_be_several(make_files):
    files = make_files({"common.axitl": 'note "From a common file" edge=bottom\n'})
    d = parse(T + 'include "common.axitl"\nnote "Here"\n', files).document
    assert [n.paragraphs[0].text for n in d.notes] == ["From a common file", "Here"]
    assert [n.order for n in d.notes] == [0, 1]


@pytest.mark.parametrize(
    "source, code",
    [
        ('note "a" {\n  "b"\n}\n', "bad-value"),
        ("note\n", "bad-value"),
        ("note {\n}\n", "bad-value"),
        ('note ""\n', "bad-value"),
        ('note "a" anchor=sometime\n', "bad-value"),
        ('note "a" anchor=1900-1910\n', "bad-value"),
        ('note "a" edge=left\n', "bad-value"),
        ('note "a" align=middle\n', "bad-value"),
        ('note "a" width=0\n', "bad-value"),
        ('note "a" clearance=-1\n', "bad-value"),
        ('note "a" at=start\n', "unknown-parameter"),
        ('note "a" side=above\n', "unknown-parameter"),
        ('note "a" purple\n', "unknown-pen"),
        ('note "a" red blue\n', "duplicate-pen"),
        ('note "a" illustration(x.svg)\n', "bad-value"),
        ('note "a" font=Nope\n', "unknown-font"),
        ('group "G" 1900-1950 {\n  note "a"\n}\n', "nested-note"),
        ('note {\n  "a"\n', "syntax"),
        ('note {\n  heading\n}\n', "syntax"),
    ],
)
def test_errors(source, code):
    assert code in error_codes(T + source)


def test_error_messages_point_the_author_somewhere_useful():
    assert "anchor=" in message(T + 'note "a" at=start\n')
    assert "edge=" in message(T + 'note "a" side=above\n')
    assert "note" in message(T + 'note {\n  "a"\n')
    assert "start, middle, end or one date" in message(T + 'note "a" anchor=sometime\n')
    assert "heading" in message(T + 'note "a" {\n  "b"\n}\n')


def test_missing_characters_are_a_warning():
    result = parse(T + 'note "A curly ’ apostrophe"\n')
    assert "missing-glyph" in [d.code for d in result.diagnostics]


# -- placement ----------------------------------------------------------------------------------------------


def test_a_note_at_the_start_sits_in_the_top_corner_inside_its_margin():
    L = lay(T + 'note "Dates are Gregorian throughout."\n')
    (note,) = L.notes
    left, top, _, _ = ink(note)
    assert left == pytest.approx(5.0) and top == pytest.approx(5.0)
    assert note.side is Side.ABOVE and note.kind == "note"


def test_on_the_bottom_edge_its_ink_ends_at_the_margin():
    L = lay(T + 'note "Notes go by the baseline" edge=bottom anchor=end margin=8\n')
    _, _, right, bottom = ink(L.notes[0])
    assert right == pytest.approx(1000 - 8) and bottom == pytest.approx(210 - 8)
    assert L.notes[0].side is Side.BELOW


def test_a_note_at_the_middle_or_a_date_is_centred_on_it():
    L = lay(T + 'note "In the middle" anchor=middle\nnote "At 1950" anchor=1950 edge=bottom\n')
    middle, dated = L.notes
    left, _, right, _ = ink(middle)
    assert (left + right) / 2 == pytest.approx(500)
    left, _, right, _ = ink(dated)
    assert (left + right) / 2 == pytest.approx(L.time_to_position(parse_date("1950")))


def test_a_date_near_an_end_keeps_the_note_on_the_paper():
    L = lay(T + f'note "{LONG}" anchor=1901\n')
    assert ink(L.notes[0])[0] == pytest.approx(5.0)
    assert "note-moved" not in warnings(L)  # it still reaches its date


def test_paragraphs_wrap_to_the_width():
    L = lay(T + f'note "{LONG}" width=60mm\n')
    lines = L.notes[0].texts
    assert len(lines) > 2
    assert all(t.shaped.width <= 60 + 1e-9 for t in lines)
    # Filled greedily: no line could have taken the next line's first word.
    for this, nxt in zip(lines, lines[1:]):
        longer = shape(this.shaped.font, f"{this.text} {nxt.text.split(' ')[0]}", this.shaped.size_mm)
        assert longer.width > 60
    assert " ".join(t.text for t in lines) == LONG


def test_the_default_width_is_thirty_ems_or_the_paper():
    L = lay(T + f'note "{LONG} {LONG}"\n')
    assert max(t.shaped.width for t in L.notes[0].texts) <= 120 + 1e-9
    assert max(t.shaped.width for t in L.notes[0].texts) > 100
    short = lay(T.replace("length=1000", "length=100") + f'note "{LONG}"\n')
    assert max(t.shaped.width for t in short.notes[0].texts) <= 90 + 1e-9


def test_lines_and_paragraphs_go_down_the_page():
    L = lay(T + f'note {{\n  heading "Heading"\n  "{LONG}"\n\n  "Second."\n}}\n')
    ys = [t.y for t in L.notes[0].texts]
    assert ys == sorted(ys) and len(set(ys)) == len(ys)
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert gaps[-1] > gaps[-2]  # the space before a paragraph is more than between its lines
    assert L.notes[0].texts[0].shaped.size_mm == 5.0


def test_aligned_right():
    L = lay(T + f'note "{LONG}" width=60mm align=right\n')
    rights = [t.x + t.shaped.ink_box()[2] for t in L.notes[0].texts]
    assert max(rights) - min(rights) < 1e-9


def test_a_word_too_long_for_the_width_is_a_warning():
    L = lay(T + 'note "Antidisestablishmentarianism is long" width=20mm\n')
    assert "note-word-too-long" in warnings(L)
    assert L.notes[0].texts[0].text == "Antidisestablishmentarianism"


def test_a_width_longer_than_the_paper_is_fatal():
    assert error_codes(T + 'note "a" width=1m\n', stage=layout) == ["no-room-for-note"]


def test_too_tall_for_its_side_is_fatal():
    paragraphs = "\n\n".join(f'  "{LONG}"' for _ in range(12))
    assert error_codes(T + f"note {{\n{paragraphs}\n}}\n", stage=layout) == ["no-room-for-note"]


def test_outside_the_timeline_it_is_left_out_with_a_warning():
    L = lay(T + 'note "Later" anchor=2050\n')
    assert L.notes == () and "outside-window" in warnings(L)


# -- keeping clear of the title, the credits and each other -----------------------------------------------------


def test_it_keeps_25mm_clear_of_the_title():
    L = lay(T + 'title "A Century of Clever People" font_size=10mm\nnote "About this timeline"\n')
    assert L.notes[0].box.x0 == pytest.approx(L.title.box.x1 + 25)


def test_the_clearance_can_be_changed():
    L = lay(T + 'title "A Century" font_size=10mm\nnote "About" clearance=5mm\n')
    assert L.notes[0].box.x0 == pytest.approx(L.title.box.x1 + 5)
    L = lay(T + 'title "A Century" font_size=10mm\nnote "About" clearance=0\n')
    assert L.notes[0].box.x0 == pytest.approx(L.title.box.x1)


def test_it_keeps_25mm_clear_of_the_credits():
    credits = 'credits {\n  heading "Design"\n  "A. N. Author"\n}\n'
    L = lay(T + credits + 'note "The end" anchor=end edge=bottom\n')
    assert L.notes[0].box.x1 == pytest.approx(L.credits.box.x0 - 25)


def test_the_title_doesnt_push_a_note_on_the_other_edge():
    L = lay(T + 'title "A Century" font_size=10mm\nnote "Under it" edge=bottom\n')
    assert ink(L.notes[0])[0] == pytest.approx(5.0)


def test_a_dated_note_moves_the_least_distance_and_says_so_if_it_leaves_its_date():
    title = 'title "A Century of Clever People" font_size=10mm\n'
    L = lay(T + title + 'note "Near" anchor=1905\n')
    assert L.notes[0].box.x0 == pytest.approx(L.title.box.x1 + 25)
    assert "note-moved" in warnings(L)
    assert "the title" in next(d.message for d in L.diagnostics if d.code == "note-moved")


def test_notes_keep_clear_of_each_other():
    L = lay(T + 'note "First" anchor=1950\nnote "Second" anchor=1950\n')
    first, second = L.notes
    assert second.box.x0 >= first.box.x1 + 25 - 1e-9 or second.box.x1 <= first.box.x0 - 25 + 1e-9
    # On different edges they don't meet.
    L = lay(T + 'note "First" anchor=1950\nnote "Second" anchor=1950 edge=bottom\n')
    assert L.notes[0].box.x0 == pytest.approx(L.notes[1].box.x0, abs=5)


def test_no_room_along_the_edge_is_fatal():
    source = T.replace("length=1000", "length=200") + 'title "A Century of Clever" font_size=10mm\nnote "x y z" clearance=90\n'
    assert error_codes(source, stage=layout) == ["no-room-for-note"]
    assert "the title" in message(source, stage=layout)


# -- keeping everything else clear of a note ---------------------------------------------------------------------


def test_bars_keep_out_of_the_lanes_a_note_crosses():
    people = "".join(f'^person "P{i}" 1900-1990\n' for i in range(9))
    L = lay(T + f'note "{LONG}" anchor=middle\n' + people)
    keep = L.notes[0].box
    for b in L.bars:
        assert b.y1 < keep.y0 or b.y0 > keep.y1 + 1.5 - 1e-9 or b.x1 < keep.x0 or b.x0 > keep.x1
    assert L.above.lanes_used == 9


def test_flags_and_poles_keep_clear_of_a_note():
    events = "".join(f'^event "Event number {i}" 1950-0{i + 1}\n' for i in range(8))
    L = lay(T + f'note "{LONG}" anchor=1950\n' + events)
    keep = L.notes[0].box.padded(1.5)
    for e in L.events:
        assert not e.flag_box.overlaps(keep) or "label-collision" in warnings(L)
        for a, b in e.pole_segments:
            assert not keep_inside([(e.x, a), (e.x, b)], keep.padded(-0.01)), e.entity.label


def test_a_graph_is_broken_around_a_note():
    graph = 'graph "" {\n  1900 0\n  1950 100\n  1999 -100\n}\n'
    L = lay(T + f'note "{LONG}" anchor=middle\n' + graph)
    for line in L.graphs[0].line:
        for t in L.notes[0].texts:
            assert not keep_inside(line, t.box.padded(-0.01))


# -- drawing --------------------------------------------------------------------------------------------------


def test_a_note_is_drawn_last_in_its_pen():
    L = lay(T + 'note "One" blue\nnote "Two" edge=bottom violet\n')
    assert L.pens == ("black", "blue", "violet")
    d = draw(L)
    notes = [s for s in d.strokes if s.stage is Stage.TITLES]
    assert {s.pen for s in notes} == {"blue", "violet"}
    for s in notes:
        assert any(n.box.padded(0.01).x0 <= s.points[0][0] <= n.box.x1 + 0.01 for n in L.notes)
