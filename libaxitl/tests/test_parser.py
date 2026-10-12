"""The grammar and AST builder: what each declaration means, inheritance, duplicates, fonts, illustrations."""

import pytest

from libaxitl import AxitlError, Baseline, DateRange, DateValue, Fill, Kind, OpenEndStyle, Side, parse
from libaxitl.model import TimeLabel

T = "timeline start=1900 end=2000 length=2m width=210\n"
APPLE = '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="40mm"><path d="M0 0 L 1 1"/></svg>'
HAND_FONT = """<svg xmlns="http://www.w3.org/2000/svg"><font horiz-adv-x="500">
<glyph unicode="a" d="M 0 0 L 0 400"/><glyph unicode="?" d="M 0 0 L 0 700"/></font></svg>"""


def entities(source, resolve=None):
    return list(parse(source, resolve).document.walk())


def error_codes(source, resolve=None):
    with pytest.raises(AxitlError) as info:
        parse(source, resolve)
    return [d.code for d in info.value.errors]


# -- the timeline declaration -----------------------------------------------------------------------------


def test_timeline_defaults():
    t = parse(T).document.timeline
    assert (t.start, t.end) == (DateValue(1900), DateValue(2000))
    assert (t.width_mm, t.length_mm, t.scale) == (210.0, 2000.0, None)
    assert t.baseline is Baseline.MIDDLE
    assert (t.above_lane_height_mm, t.below_lane_height_mm) == (8.0, 8.0)
    assert (t.above_baseline_offset_mm, t.below_baseline_offset_mm) == (3.0, 3.0)
    assert (t.ticks_mm, t.tick_label_every) == (3.5, None)
    assert t.open_end_style is OpenEndStyle.SAWTOOTH
    assert (t.font, t.font_size_mm) == ("HersheySans1", 4.0)


def test_timeline_settings():
    t = parse(
        "timeline start=600BC end=now scale=5mm/year width=21cm baseline=low lane_height=10mm "
        "above_lane_height=15mm baseline_offset=2mm below_baseline_offset=4 ticks=off tick_label_every=10 "
        'open_end_style=sine font="EMSTech" font_size=0.5cm\n'
    ).document.timeline
    assert t.end is None and t.end_is_now
    assert (t.scale.mm, t.scale.unit, t.width_mm) == (5.0, "year", 210.0)
    assert (t.above_lane_height_mm, t.below_lane_height_mm) == (15.0, 10.0)
    assert (t.above_baseline_offset_mm, t.below_baseline_offset_mm) == (2.0, 4.0)
    assert (t.ticks_mm, t.tick_label_every, t.open_end_style) == (None, 10, OpenEndStyle.SINE)
    assert (t.font, t.font_size_mm, t.baseline) == ("EMSTech", 5.0, Baseline.LOW)


@pytest.mark.parametrize(
    "source, code",
    [
        ("timeline start=1900 end=2000 length=2m\n", "missing-parameter"),  # width is required
        ("timeline start=1900 end=2000 width=210\n", "missing-parameter"),  # length or scale
        ("timeline start=1900 end=2000 length=2m scale=1mm/year width=210\n", "bad-value"),
        ("timeline start=2000 end=1900 length=2m width=210\n", "bad-value"),
        ("timeline start=1900 end=2000 length=2m width=0\n", "bad-value"),
        ("timeline start=1900 end=2000 length=2m width=210 baseline=top\n", "bad-value"),
        ("timeline start=1900 end=2000 length=2m width=210 tick_label_every=0\n", "bad-value"),
        ("timeline start=1900 end=2000 length=2m width=210 colour=red\n", "unknown-parameter"),
        ("timeline start=1900 end=2000 length=2m width=210 width=200\n", "duplicate-parameter"),
        ("timeline start=1900 end=2000 length=2m width=210 red\n", "unexpected-item"),
        ("timeline start=19000BCX end=2000 length=2m width=210\n", "bad-date"),
        (T + T, "duplicate-timeline"),
        ('event "e" 1950\n', "missing-timeline"),
    ],
)
def test_timeline_errors(source, code):
    assert code in error_codes(source)


# -- entity lines -----------------------------------------------------------------------------------------


def test_spec_example_lines(make_files):
    (newton, doe) = entities(
        T + '^!!person "Isaac Newton" 1642-1727 red illustration(newton.svg)\n--person  "John Doe" 1953-2022 blue\n',
        make_files({"newton.svg": APPLE}),
    )
    assert (newton.kind, newton.side, newton.priority, newton.pen) == (Kind.PERSON, Side.ABOVE, 2, "red")
    assert newton.when == DateRange(DateValue(1642), DateValue(1727))
    assert newton.illustration.aspect_ratio == 0.5 and newton.illustration.height_mm is None
    assert (doe.side, doe.priority, doe.pen) == (None, -2, "blue")


def test_side_marks_and_priorities():
    es = entities(T + 'vspan "a" 1900-1910\n^event "b" 1905\nv---group "c" 1900-1950 {\n}\n')
    assert [(e.side, e.priority) for e in es] == [(Side.BELOW, 0), (Side.ABOVE, 0), (Side.BELOW, -3)]


def test_defaults_on_an_entity():
    (e,) = entities(T + 'span "s" 1910-1920\n')
    assert (e.pen, e.fill, e.font, e.font_size_mm, e.illustration, e.member_of) == (
        "black", Fill.NONE, "HersheySans1", 4.0, None, None
    )


def test_pens_from_all_three_families():
    es = entities(T + 'event "a" 1901 HB-pencil\nevent "b" 1902 6H-pencil\nevent "c" 1903 fountain-indigo\n')
    assert [e.pen for e in es] == ["HB-pencil", "6H-pencil", "fountain-indigo"]


def test_open_ended_entities():
    (a, b) = entities(T + 'person "a" 1953-\nspan "b" 1953-04-01/\n')
    assert a.when.is_open and b.when.is_open


def test_escaped_quotes_in_labels():
    (e,) = entities(T + r'event "The \"Glorious\" Revolution" 1688' + "\n")
    assert e.label == 'The "Glorious" Revolution'


@pytest.mark.parametrize(
    "line, code",
    [
        ('span "X" 1910-12', "needs-range"),
        ('span "X" 1963//1964', "needs-range"),
        ('event "X" 1939-1945', "event-range"),
        ('event "X" 1939-', "event-range"),
        ('person "A" 1900-1950 gray', "unknown-pen"),
        ('person "A" 1900-1950 red blue', "duplicate-pen"),
        ('person "A" 1900 1950', "unexpected-item"),
        ('!-person "A" 1900-1950', "mixed-priority"),
        ('person "A"', "missing-date"),
        ('person "A" red 1900-1950', "bad-date"),
        ('person Isaac 1900-1950', "syntax"),
        ('persn "A" 1900-1950', "syntax"),
        ('event "e" 1920 {\n}', "unexpected-body"),
        ('event "e" 1920 fill=solid', "bad-value"),
        ('span "s" 1920-1930 fill=stripes', "bad-value"),
        ('span "s" 1920-1930 side=above', "unknown-parameter"),
        ('span "s" 1920-1930 font="hersheysans1"', "unknown-font"),
        ('span "s" 1920-1930 illustration(missing.svg)', "missing-illustration"),
        ('span "s" 1920-1930 illustration(a.svg', "syntax"),
        ('span "s" 1920-1930 illustration(a.svg width=3mm)', "unknown-parameter"),
        ('group "G" 1900-1950 {\n  event "e" 1920', "syntax"),
        ("}", "syntax"),
        ('group "G" 1900-1950 {\ntimeline start=1900\n}', "nested-timeline"),
    ],
)
def test_entity_errors(line, code, make_files):
    assert code in error_codes(T + line + "\n", make_files({"a.svg": APPLE}))


def test_several_errors_are_reported_together():
    codes = error_codes(T + 'person "A" 1900-1950 gray\nevent "B" 1900-1950\nspan "C" 1910-12\n')
    assert codes == ["unknown-pen", "event-range", "needs-range"]


def test_glued_comment_gets_the_targeted_message():
    with pytest.raises(AxitlError, match="did you mean a single '/'"):
        parse(T + 'span "Something" 1963//1964\n')


# -- groups -----------------------------------------------------------------------------------------------


def test_group_children_inherit_pen_and_font_but_not_side():
    source = T + (
        '^!group "Industrial Revolution" 1760-1840 orange font="EMSTech" font_size=5mm {\n'
        '  !!person "James Watt" 1736-1819\n'
        '  !!event "Newcomen engine" 1712 HB-pencil font="HersheySans1"\n'
        '  group "Inner" 1770-1800 {\n'
        '    span "deep" 1780-1790\n'
        "  }\n"
        "}\n"
    )
    group, watt, newcomen, inner, deep = entities(source)
    assert (group.side, group.pen, group.font, group.font_size_mm) == (Side.ABOVE, "orange", "EMSTech", 5.0)
    assert (watt.side, watt.pen, watt.font, watt.font_size_mm) == (None, "orange", "EMSTech", 5.0)
    assert (newcomen.pen, newcomen.font) == ("HB-pencil", "HersheySans1")
    assert (watt.member_of, inner.member_of, deep.member_of) == ("Industrial Revolution",) * 2 + ("Inner",)
    assert deep.pen == "orange"
    assert [e.order for e in (group, watt, newcomen, inner, deep)] == [0, 1, 2, 3, 4]


# -- duplicates (§5) --------------------------------------------------------------------------------------


def test_duplicates_across_files_last_one_wins(make_files):
    files = make_files({"a.axitl": 'person "Julius Caesar" 100BC-44BC red\n'})
    result = parse(T + 'include "a.axitl"\nperson "Julius Caesar" 100BC-44BC blue\n', files)
    (caesar,) = result.document.entities
    assert caesar.pen == "blue"
    (warning,) = result.diagnostics
    assert warning.code == "duplicate-entity"
    assert str(warning.location) == "a.axitl:1" and "main.axitl:3" in warning.message


def test_repeated_labels_within_one_file_are_kept():
    es = entities(T + 'person "John Smith" 1900-1950\nperson "John Smith" 1920-1980\n')
    assert len(es) == 2


def test_an_events_identity_includes_its_date(make_files):
    files = make_files({"uk.axitl": 'event "General election" 1945\nevent "General election" 1950-02\n'})
    source = T + 'include "uk.axitl"\nevent "General election" 1950\nevent "General election" 1945 red\n'
    result = parse(source, files)
    kept = [(str(e.when), e.pen, e.location.source) for e in result.document.walk()]
    # 1945 is defined in both files, so the later one wins; 1950-02 and 1950 differ in precision, so both stay
    assert kept == [("1950-02", "black", "uk.axitl"), ("1950", "black", "main.axitl"), ("1945", "red", "main.axitl")]
    (warning,) = result.diagnostics
    assert str(warning.location) == "uk.axitl:1"


def test_a_dropped_group_takes_its_members_with_it(make_files):
    files = make_files({"a.axitl": 'group "G" 1900-1950 {\n  event "only in a" 1920\n}\n'})
    result = parse(T + 'include "a.axitl"\ngroup "G" 1900-1950 {\n}\n', files)
    assert [e.label for e in result.document.walk()] == ["G"]


# -- fonts and illustrations ------------------------------------------------------------------------------


def test_custom_font_is_fetched_relative_to_the_declaring_file(make_files):
    files = make_files({"lib/a.axitl": 'event "a" 1920 font="fonts/hand.svg"\n', "lib/fonts/hand.svg": HAND_FONT})
    result = parse(T + 'include "lib/a.axitl"\n', files)
    (e,) = result.document.entities
    assert e.font == "lib/fonts/hand.svg"
    assert set(result.document.fonts) == {"HersheySans1", "lib/fonts/hand.svg"}
    assert [(r.kind, r.name) for r in result.resources] == [("include", "lib/a.axitl"), ("font", "lib/fonts/hand.svg")]


def test_builtin_fonts_never_go_through_resolve(make_files):
    resolve = make_files({})
    parse(T + 'event "a" 1920 font="EMSAllure"\n', resolve)
    assert resolve.requested == []


def test_unreadable_custom_font(make_files):
    files = make_files({"bad.svg": "<svg/>"})
    assert error_codes(T + 'event "a" 1920 font="bad.svg"\n', files) == ["bad-font"]
    assert error_codes(T + 'event "a" 1920 font="nope.svg"\n', files) == ["missing-font"]


def test_missing_glyphs_are_warnings_naming_the_entity(make_files):
    result = parse(T + 'event "Newton’s Ω" 1920\nevent "aß" 1921 font="hand.svg"\n',
                   make_files({"hand.svg": HAND_FONT}))
    messages = [d.message for d in result.diagnostics]
    assert [d.code for d in result.diagnostics] == ["missing-glyph"] * 3
    assert "U+2019" in messages[0] and "drawing ' instead" in messages[0] and 'event "Newton' in messages[0]
    assert "U+03A9" in messages[1] and "drawing ? instead" in messages[1]
    assert "U+00DF" in messages[2] and "drawing ? instead" in messages[2]  # "ss" would need an s


def test_illustration_size_and_height(make_files):
    viewbox_only = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10"/>'
    files = make_files({"pics/a.svg": APPLE, "pics/b.svg": viewbox_only})
    (a, b) = entities(
        T + 'event "a" 1920 illustration(pics/a.svg height=4cm)\nevent "b" 1921 illustration("pics/b.svg")\n', files
    )
    assert (a.illustration.height_mm, a.illustration.aspect_ratio) == (40.0, 0.5)
    assert (b.illustration.name, b.illustration.aspect_ratio) == ("pics/b.svg", 3.0)


@pytest.mark.parametrize(
    "svg", ['<svg xmlns="http://www.w3.org/2000/svg"/>', "not xml", '<html xmlns="http://www.w3.org/2000/svg"/>']
)
def test_unusable_illustrations(svg, make_files):
    assert error_codes(T + 'event "a" 1920 illustration(a.svg)\n', make_files({"a.svg": svg})) == ["bad-illustration"]


# -- determinism ------------------------------------------------------------------------------------------


def test_parsing_is_deterministic(make_files):
    source = T + 'include "a.axitl"\n^!!person "p" 1900-1950 red\n'
    files = {"a.axitl": 'group "G" 1900-1950 {\n  event "e" 1920\n}\n'}
    first = parse(source, make_files(files))
    second = parse(source, make_files(files))
    assert first.flattened_text == second.flattened_text
    assert first.document == second.document
    assert first.resources == second.resources


# -- time labels (§3.11) ----------------------------------------------------------------------------------


def test_time_label_is_inherited_like_font():
    source = T.replace("width=210", "width=210 time_label=year") + (
        'event "plain" 1901\n'
        'group "G" 1900-1950 time_label=day {\n'
        '  event "inherits" 1910-05-01\n'
        '  event "switched off" 1911 time_label=none\n'
        '  group "inner" 1920-1930 {\n'
        '    event "deep" 1925-03-02 time_label=date\n'
        '    event "deep default" 1926\n'
        '  }\n'
        '  span "bar" 1912-1913\n'
        "}\n"
    )
    doc = parse(source).document
    assert doc.timeline.time_label is TimeLabel.YEAR
    labels = {e.label: e.time_label for e in doc.walk()}
    assert labels["plain"] is TimeLabel.YEAR
    assert (labels["G"], labels["inherits"], labels["switched off"]) == (TimeLabel.DAY, TimeLabel.DAY, TimeLabel.NONE)
    assert (labels["deep"], labels["deep default"]) == (TimeLabel.DATE, TimeLabel.DAY)
    assert labels["bar"] is TimeLabel.NONE  # bars have no flag
    assert parse(T).document.timeline.time_label is TimeLabel.NONE


@pytest.mark.parametrize("line", ['person "p" 1900-1950 time_label=year', 'span "s" 1900-1950 time_label=day'])
def test_time_label_on_a_bar_is_an_error(line):
    with pytest.raises(AxitlError, match="applies to events"):
        parse(T + line + "\n")


def test_bad_time_label():
    with pytest.raises(AxitlError, match="time_label= takes one of none, date, year, month, day, hour, min, sec"):
        parse(T + 'event "e" 1950 time_label=minute\n')


def test_a_time_label_the_font_cant_draw_is_a_warning(make_files):
    result = parse(T + 'event "a" 1920 font="hand.svg" time_label=year\n', make_files({"hand.svg": HAND_FONT}))
    messages = [d.message for d in result.diagnostics]
    assert any("for the time label of event" in m and "U+0031" in m for m in messages)  # the font has no "1"
