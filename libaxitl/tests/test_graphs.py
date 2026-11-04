"""Background graphs (language spec §15): declaring them, reading their points, the vertical scale, the line, where
their own text goes, breaking around the foreground, shading and drawing."""

import math

import pytest

from libaxitl import AxitlError, Box, Fill, RenderOptions, Stage, draw, layout, parse, parse_date, render
from libaxitl.dates import DateValue
from libaxitl.diagnostics import SourceLocation
from libaxitl.geometry import segment_crosses
from libaxitl.graphdata import FormatError, time_reader
from libaxitl.graphs import auto_marks, number_text, steffen
from libaxitl.model import LineMode, ValueScaleMode, YScale

# 1000mm from 1900 to the end of 2000; the baseline across the middle, at 100mm, with 97mm of room either side
# for a fitted graph (3mm from each edge); no ticks, so nothing hangs below the baseline.
T = "timeline start=1900 end=2000 length=1000 width=200 ticks=off\n"
BASE = 100.0


def parsed(source, files=None):
    return parse(T + source, (lambda name: files[name]) if files else None)


def graph(source, files=None):
    return parsed(source, files).document.graphs[0]


def laid(source, files=None):
    return layout(parsed(source, files).document)


def errors(source, files=None):
    with pytest.raises(AxitlError) as info:
        parsed(source, files)
    return info.value.errors


def codes(source, files=None):
    return [d.code for d in errors(source, files)]


def x_of(L, date):
    return L.time_to_position(parse_date(date))


def ys(lines):
    return [y for line in lines for _, y in line]


# -- declaring a graph (§15.1) --------------------------------------------------------------------------------


def test_an_inline_graph_and_its_defaults():
    g = graph('graph "G" {\n1900 1\n1950 2.5\n}\n')
    assert (g.title, g.pen, g.origin, g.y_scale, g.line, g.fill) == (
        "G", "HB-pencil", 0.0, YScale.LINEAR, LineMode.STRAIGHT, Fill.NONE,
    )
    assert (g.value_scale, g.value_scale_mm, g.value_marks, g.data) == (ValueScaleMode.EVERY, 1000.0, None, None)
    assert (g.height_mm, g.range, g.fill_depth_mm, g.shadow_mm) == (None, None, None, None)
    assert (g.font, g.font_size_mm) == ("HersheySans1", 4.0)
    assert [(p.value, p.location.line) for p in g.points] == [(1.0, 3), (2.5, 4)]
    assert g.points[0].seconds == parse_date("1900").first_second()


def test_every_setting():
    g = graph(
        'graph "G" 2H-pencil\n'
        "    origin=first\n    y_scale=log\n    height=4cm\n    range=10\n    line=step\n    fill=diagonal\n"
        "    fill_depth=3\n    shadow=1.5mm\n    value_scale=50cm\n    value_marks=200,100,50\n"
        '    font="EMSTech"\n    font_size=5mm {\n1900 100\n}\n'
    )
    assert (g.pen, g.origin, g.y_scale, g.height_mm, g.range, g.line) == (
        "2H-pencil", None, YScale.LOG, 40.0, 10.0, LineMode.STEP,
    )
    assert (g.fill, g.fill_depth_mm, g.shadow_mm, g.value_scale_mm) == (Fill.DIAGONAL, 3.0, 1.5, 500.0)
    assert (g.value_marks, g.font, g.font_size_mm) == ((50.0, 100.0, 200.0), "EMSTech", 5.0)
    assert graph('graph "G" value_scale=start {\n1900 1\n}\n').value_scale is ValueScaleMode.START
    assert graph('graph "G" value_scale=off {\n1900 1\n}\n').value_scale is ValueScaleMode.OFF


def test_a_graph_inherits_the_timelines_font():
    g = parse('timeline start=1900 end=2000 length=1m width=200 font="EMSTech" font_size=3mm\ngraph "G" {\n1900 1\n}\n')
    assert (g.document.graphs[0].font, g.document.graphs[0].font_size_mm) == ("EMSTech", 3.0)


@pytest.mark.parametrize(
    "source, code",
    [
        ('graph "G"\n', "graph-data"),  # no points from anywhere
        ('graph "G" data="d.csv" {\n1900 1\n}\n', "graph-data"),  # points from two places
        ('graph "G" first_row=2 {\n1900 1\n}\n', "bad-value"),  # CSV settings need a CSV
        ('graph "G" range=10 {\n1900 1\n}\n', "bad-value"),  # range needs height
        ('graph "G" y_scale=log {\n1900 1\n}\n', "bad-value"),  # log needs an origin above zero
        ('graph "G" y_scale=log origin=1 {\n1900 0\n}\n', "bad-value"),  # ...and values above zero
        ('graph "G" y_scale=log origin=1 height=1cm range=1 {\n1900 2\n}\n', "bad-value"),  # a ratio above 1
        ('graph "G" fill=solid shadow=1mm {\n1900 1\n}\n', "bad-value"),  # a shadow needs its thickness
        ('graph "G" fill_depth=1mm {\n1900 1\n}\n', "bad-value"),  # shading needs a pattern
        ('graph "G" line=curvy {\n1900 1\n}\n', "bad-value"),
        ('graph "G" value_marks=1,x {\n1900 1\n}\n', "bad-value"),
        ('graph "G" value_scale=often {\n1900 1\n}\n', "bad-value"),
        ('graph "G" origin=zero {\n1900 1\n}\n', "bad-value"),
        ('graph "G" colour=red {\n1900 1\n}\n', "unknown-parameter"),
        ('graph "G" purple {\n1900 1\n}\n', "unknown-pen"),
        ('graph "G" red blue {\n1900 1\n}\n', "duplicate-pen"),
        ('graph "G" illustration(a.svg) {\n1900 1\n}\n', "unexpected-item"),
        ('^graph "G" {\n1900 1\n}\n', "graph-marks"),
        ('!graph "G" {\n1900 1\n}\n', "graph-marks"),
        ('group "S" 1900-1950 {\ngraph "G" {\n1900 1\n}\n}\n', "nested-graph"),
        ('graph "G" {\n1900 1 2\n}\n', "bad-point"),
        ('graph "G" {\n1950 1\n1940 2\n}\n', "points-out-of-order"),
        ('graph "G" {\n1950 1\n1950 2\n}\n', "points-out-of-order"),
        ('graph "G" {\n1950-13 1\n}\n', "bad-time"),
        ('graph "G" {\n1950 x\n}\n', "bad-value"),
        ('graph "G" {\n1950 .\n}\n', "bad-value"),  # not a gap unless missing= says so
        ('graph "G" missing=. {\n1950 .\n}\n', "no-points"),
    ],
)
def test_graph_errors(source, code):
    assert code in codes(source)


def test_an_unclosed_body_of_points_is_reported_on_the_graphs_line():
    [e] = errors('graph "G" {\n1900 1\n')
    assert e.message == "this graph's { body of points is never closed with }" and e.location.line == 2


def test_points_with_gaps():
    g = graph('graph "G" missing=-999 {\n1900 1\n1910 -999\n1920 3   // a comment\n}\n')
    assert [p.value for p in g.points] == [1.0, None, 3.0]


def test_a_graph_defined_again_in_another_file_last_wins():
    files = {"a.axitl": 'graph "G" {\n1900 1\n}\n'}
    result = parsed('include "a.axitl"\ngraph "G" {\n1900 2\n}\ngraph "" {\n1900 3\n}\ngraph "" {\n1900 4\n}\n', files)
    assert [g.points[0].value for g in result.document.graphs] == [2.0, 3.0, 4.0]  # untitled graphs never clash
    assert [d.code for d in result.diagnostics] == ["duplicate-graph"]


def test_a_title_character_the_font_lacks_is_a_warning():
    result = parsed('graph "Ōsaka" {\n1900 1\n}\n')
    assert [d.code for d in result.diagnostics] == ["missing-glyph"]


def test_an_include_doesnt_change_a_graph():
    files = {"a.axitl": 'graph "G" {\n1900 1\n}\n'}
    result = parsed('include "a.axitl" priority=-3 side=below\n', files)
    assert "graph" in result.flattened_text and result.document.graphs[0].title == "G"


# -- reading a CSV file (§15.2) ---------------------------------------------------------------------------------


def test_a_csv_read_as_it_comes():
    files = {
        "lib/g.axitl": (
            'graph "G" data="../data/d.csv" first_row=3 last_row=7 separator=tab time_column=When value_column=2\n'
            '    time_format="MM/DD/YYYY" missing=.\n'
        ),
        "data/d.csv": "Prices, monthly\n\nWhen\tPrice\tVolume\n01/31/1929\t300.5\t10\n2/28/1929\t.\t11\n"
        "\n03/29/1929\t3.1e2\t12\nSource: nowhere\n",
    }
    result = parsed('include "lib/g.axitl"\n', files)
    g = result.document.graphs[0]
    assert g.data == "data/d.csv"
    assert [p.value for p in g.points] == [300.5, None, 310.0]
    assert [p.location for p in g.points] == [SourceLocation("data/d.csv", n) for n in (4, 5, 7)]
    assert g.points[1].seconds == parse_date("1929-02-28").first_second()
    assert ("data", "data/d.csv") in [(r.kind, r.name) for r in result.resources]


def test_csv_defaults_quoting_and_line_endings():
    files = {"d.csv": '﻿Date,"Adj Close",Note\r\n1986-04-26 01:23:44,"200",ok\r\n1986-04-26T01:23:45,,"a, b"\r\n'}
    g = graph('graph "G" data="d.csv" value_column="Adj Close" {', files) if False else graph(
        'graph "G" data="d.csv" value_column="Adj Close"\n', files
    )
    assert [p.value for p in g.points] == [200.0, None]
    assert g.points[0].seconds == parse_date("1986-04-26T01:23:44").first_second()
    plain = graph('graph "G" data="d.csv" header=no first_row=2 time_column=1 value_column=2\n', files)
    assert [p.value for p in plain.points] == [200.0, None]


def test_a_quoted_field_running_over_lines_takes_its_first_lines_number():
    files = {"d.csv": 'Date,Value,Note\n1900,1,"two\nlines"\n1901,x,\n'}
    [e] = errors('graph "G" data="d.csv"\n', files)
    assert e.location == SourceLocation("d.csv", 4) and "'x' isn't a number" in e.message


@pytest.mark.parametrize(
    "csv, settings, code, words",
    [
        ("Date,Value\n1900,1\n", "time_column=Year", "unknown-column", "its header (row 1) has Date, Value"),
        ("1900,1\n", "header=no time_column=Date", "bad-value", "give its number instead"),
        ('Date,Value\n1900,"1,234.5"\n', "", "bad-value", "thousands separators"),
        ("Date;Value\n1900;1,5\n", "separator=semicolon", "bad-value", "decimal point"),
        ("Date,Value\n1900,3\n,2\n", "", "bad-data", "a value but no time"),
        ("Date,Value,Other\n1900\n", "", "bad-data", "has 1 column"),
        ("Date,Value\n10/29/1929,1\n", "", "bad-time", "give time_format="),
        ("Date,Value\n13/01/1929,1\n", 'time_format="MM/DD/YYYY"', "bad-time", "isn't a real date"),
        ("Date,Value\n1900,1\n", 'time_format="DD/MM"', "bad-value", "no YYYY"),
        ("Date,Value\n", "", "no-points", "no points"),
        ("Date,Value\n1900,1\n", "first_row=5", "bad-data", "has no row 5"),
        ("Date,Value\n1900,1\n", "first_row=0", "bad-value", "counting from 1"),
        ("Date,Value\n1900,1\n", "first_row=3 last_row=2", "bad-value", "before first_row"),
        ("Date,Value\n1900,1\n", "separator=pipe", "bad-value", "comma, semicolon, tab"),
    ],
)
def test_csv_problems(csv, settings, code, words):
    found = errors(f'graph "G" data="d.csv" {settings}\n', {"d.csv": csv})
    assert any(e.code == code and words in e.message for e in found), [str(e) for e in found]


def test_a_missing_or_unreadable_data_file():
    assert codes('graph "G" data="nope.csv"\n', {}) == ["missing-data"]
    assert "not UTF-8" in errors('graph "G" data="d.csv"\n', {"d.csv": b"Date,Value\n1900,\xff\n"})[0].message


def test_a_file_wrong_on_every_row_lists_a_few_then_counts_the_rest():
    csv = "Date,Value\n" + "".join(f"19{n:02d},x\n" for n in range(12))
    found = errors('graph "G" data="d.csv"\n', {"d.csv": csv})
    assert [e.location.line for e in found[:5]] == [2, 3, 4, 5, 6]
    assert found[5].message == "and 7 more rows with problems in 'd.csv'" and len(found) == 6


def test_log_values_at_or_below_zero_are_reported_at_their_row():
    [e] = errors('graph "G" data="d.csv" y_scale=log origin=first\n', {"d.csv": "Date,Value\n1900,1\n1901,-2\n"})
    assert e.location == SourceLocation("d.csv", 3) and "-2" in e.message


@pytest.mark.parametrize(
    "fmt, text, date",
    [
        (None, "1986-04-26 01:23:44", "1986-04-26T01:23:44"),
        (None, "1929", "1929"),
        (None, "44BC-03-15", "44BC-03-15"),
        ("MM/DD/YYYY", "1/5/1929", "1929-01-05"),
        ("DD MMM YYYY", "29 oct 1929", "1929-10-29"),
        ("MMMM YYYY", "October 1929", "1929-10"),
        ("YYYY-MM-DD hh:mm", "1986-04-26 01:23", "1986-04-26T01:23"),
        ("YYYYMMDD", "19291029", "1929-10-29"),
    ],
)
def test_time_formats(fmt, text, date):
    assert time_reader(fmt)(text) == parse_date(date).first_second()


def test_decimal_years():
    read = time_reader("decimal_year")
    assert read("1958") == parse_date("1958").first_second()
    assert read("1958.5") == parse_date("1958-07-02T12:00:00").first_second()  # half of a 365-day year


@pytest.mark.parametrize("fmt, text", [("MMM YYYY", "Oct. 1929"), ("MMMM YYYY", "Octob 1929"), ("DD/MM/YYYY", "1929")])
def test_times_that_dont_fit_their_format(fmt, text):
    with pytest.raises(ValueError):
        time_reader(fmt)(text)


@pytest.mark.parametrize("fmt", ["DD/MM", "YYYY YYYY", "MM MMM YYYY"])
def test_formats_that_cant_work(fmt):
    with pytest.raises(FormatError):
        time_reader(fmt)


# -- the vertical scale (§15.5) ------------------------------------------------------------------------------


def test_fitted_to_the_paper():
    g = laid('graph "G" value_scale=off {\n1900 10\n1950 -5\n2000 2\n}\n').graphs[0]
    assert g.rate_mm == pytest.approx(9.7)  # 10 above and 5 below: the side above decides
    assert (g.above_mm, g.below_mm) == (pytest.approx(97), pytest.approx(48.5))
    assert (min(ys(g.line)), max(ys(g.line))) == (pytest.approx(3.0), pytest.approx(148.5))


def test_fitting_on_the_side_with_less_room():
    L = layout(parse('timeline start=1900 end=2000 length=1000 width=200 baseline=low ticks=off\n'
                     'graph "G" value_scale=off {\n1900 1\n1950 -1\n}\n').document)
    room_below = 200 - L.baseline_y - 3
    assert L.graphs[0].rate_mm == pytest.approx(room_below)


def test_height_and_range():
    assert laid('graph "G" height=50mm {\n1900 10\n1950 -4\n}\n').graphs[0].rate_mm == pytest.approx(5)
    assert laid('graph "G" height=40mm range=20 {\n1900 10\n}\n').graphs[0].rate_mm == pytest.approx(2)
    log = laid('graph "G" y_scale=log origin=100 height=30mm range=10 value_scale=off {\n1900 1000\n1950 10\n}\n')
    g = log.graphs[0]
    assert g.rate_mm == pytest.approx(30) and g.rate_unit == "power of ten"
    assert g.line[0][0] == (0.0, pytest.approx(BASE - 30)) and g.line[0][-1][1] == pytest.approx(BASE + 30)


def test_origin_first_is_the_first_value_inside_the_timeline():
    L = laid('graph "G" origin=first height=10mm value_scale=off {\n1890 50\n1910 100\n1950 120\n}\n')
    g = L.graphs[0]
    assert g.origin == 100.0
    first = g.line[0][0]
    assert first[0] == 0.0  # the line runs from before the start, clipped at it
    second = [p for p in g.line[0] if p[0] == pytest.approx(x_of(L, "1910"))][0]
    assert second[1] == pytest.approx(BASE)


def test_a_line_pushed_past_the_paper_is_cut_inside_its_edge():
    L = laid('graph "G" height=150mm value_scale=off {\n1900 10\n1950 -10\n2000 10\n}\n')
    assert min(ys(L.graphs[0].line)) >= 1.0 - 1e-9 and max(ys(L.graphs[0].line)) <= 199.0 + 1e-9
    assert [d.code for d in L.diagnostics] == ["graph-off-paper"]


def test_graphs_outside_the_timeline_are_left_out():
    L = laid('graph "G" {\n1800 1\n1850 2\n}\ngraph "H" origin=first {\n1850 1\n2050 2\n}\n')
    assert L.graphs == () and [d.code for d in L.diagnostics] == ["graph-outside-window", "graph-outside-window"]


# -- the line (§15.6) ----------------------------------------------------------------------------------------


def test_a_step_line_holds_each_value_and_a_gap_ends_the_hold():
    L = laid('graph "G" line=step missing=. height=10mm value_scale=off {\n1900 1\n1950 2\n1960 .\n1970 3\n}\n')
    g = L.graphs[0]
    x50, x60, x70 = x_of(L, "1950"), x_of(L, "1960"), x_of(L, "1970")
    y1, y2 = BASE - 10 / 3, BASE - 20 / 3
    assert g.line[0] == ((0.0, pytest.approx(y1)), (pytest.approx(x50), pytest.approx(y1)),
                         (pytest.approx(x50), pytest.approx(y2)), (pytest.approx(x60), pytest.approx(y2)))
    dot = g.line[1]  # the last point stands alone: a dot
    assert dot[0][1] == dot[1][1] and dot[1][0] - dot[0][0] == pytest.approx(0.25)
    assert (dot[0][0] + dot[1][0]) / 2 == pytest.approx(x70)
    assert all(not (p[0] == pytest.approx(x70)) for p in g.path[0])  # a dot casts no shading


def test_a_straight_line_breaks_at_a_gap():
    g = laid('graph "G" missing=. value_scale=off {\n1900 1\n1910 2\n1920 .\n1930 1\n1940 2\n}\n').graphs[0]
    assert len(g.line) == 2


def test_a_smooth_line_passes_through_every_point_and_never_overshoots():
    L = laid('graph "G" line=smooth height=50mm value_scale=off {\n1900 0\n1920 10\n1940 10\n1960 0\n1980 5\n}\n')
    line = L.graphs[0].line[0]
    assert min(y for _, y in line) >= BASE - 50 - 1e-6 and max(y for _, y in line) <= BASE + 1e-6
    flat = [y for x, y in line if x_of(L, "1920") - 1 <= x <= x_of(L, "1940") + 1]
    assert flat and all(y == pytest.approx(BASE - 50, abs=0.11) for y in flat)  # level between equal points
    for year, value in (("1920", 10), ("1960", 0), ("1980", 5)):
        assert distance_to((x_of(L, year), BASE - 5 * value), line) < 0.11


def distance_to(point, line):
    def to_segment(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        t = max(0.0, min(1.0, ((point[0] - p[0]) * dx + (point[1] - p[1]) * dy) / (dx * dx + dy * dy or 1)))
        return math.dist(point, (p[0] + t * dx, p[1] + t * dy))

    return min(to_segment(p, q) for p, q in zip(line, line[1:], strict=False))


def test_steffen_curves_stay_between_their_neighbours():
    points = [(0.0, 0.0), (1.0, 5.0), (2.0, 4.0), (3.0, 9.0), (3.1, -2.0)]
    curve = steffen(points, 0.01)
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        inside = [y for x, y in curve if x0 <= x <= x1]
        assert min(inside) >= min(y0, y1) - 1e-9 and max(inside) <= max(y0, y1) + 1e-9


def test_dense_data_is_simplified_within_a_tenth_of_a_millimetre():
    points = "".join(f"{1900 + n // 12}-{n % 12 + 1:02d} {1 + (n % 2) * 1e-4}\n" for n in range(1200))
    g = laid(f'graph "G" height=10mm value_scale=off {{\n{points}}}\n').graphs[0]
    assert sum(len(line) for line in g.line) < 20  # a flat line, whatever its 1200 points


# -- the graph's own text (§15.9) ------------------------------------------------------------------------------


FOREGROUND = 'span "A span" 1910-1990\nevent "An event" 1950\nperson "Somebody" 1920-1970\n'


def foreground_ink(L):
    boxes = [Box(b.x0, b.y0, b.x1, b.y1) for b in L.bars] + [b.label.box for b in L.bars]
    boxes += [e.flag_box for e in L.events]
    return boxes


def test_the_title_and_labels_keep_clear_of_the_foreground():
    L = laid(FOREGROUND + 'graph "A graph" {\n1900 1\n1950 -1\n2000 1\n}\n')
    g = L.graphs[0]
    assert "A graph" in [t.text for t in g.texts]
    for text in g.texts:
        assert not any(text.box.overlaps(b) for b in foreground_ink(L)), text.text
        assert not text.box.overlaps(Box(0, BASE - 0.3, 1000, BASE + 0.3))


def test_the_title_sits_beside_the_line_away_from_the_baseline():
    L = laid('graph "Above" height=20mm value_scale=off {\n1900 1\n2000 1\n}\n')
    [title] = L.graphs[0].texts
    line_y = L.graphs[0].line[0][0][1]
    assert title.box.y1 <= line_y - 1.5 + 1e-6 and title.box.x0 == pytest.approx(0.5)


def test_value_scales_off_at_the_start_or_repeated():
    source = 'graph "" value_scale={} {{\n1900 0\n2000 10\n}}\n'

    def rules(setting):
        g = laid(source.format(setting)).graphs[0]
        return [r for r in g.rules if r[0][0] == r[-1][0]]  # the vertical rules

    assert rules("off") == []
    assert [round(r[0][0]) for r in rules("start")] == [1]
    repeated = [r[0][0] for r in rules("25cm")]
    assert [round(x) for x in repeated[:4]] == [1, 250, 500, 750] and 990 < repeated[4] < 1000  # moved onto the paper


def test_value_marks_auto_and_given():
    g = laid('graph "" value_scale=start {\n1900 0\n2000 10\n}\n').graphs[0]
    assert sorted(t.text for t in g.texts) == ["0", "10", "5"]
    given = laid('graph "" value_scale=start value_marks=2.5,7.5 {\n1900 0\n2000 10\n}\n').graphs[0]
    assert sorted(t.text for t in given.texts) == ["0", "2.5", "7.5"]
    origin_label = [t for t in g.texts if t.text == "0"][0]
    assert origin_label.box.y1 < BASE  # just above the baseline, never on it


def test_two_graphs_scales_never_stand_in_line():
    L = laid('graph "" value_scale=start {\n1900 0\n2000 10\n}\ngraph "" value_scale=start {\n1900 0\n2000 -10\n}\n')
    xs = [g.rules[0][0][0] for g in L.graphs]
    assert xs[1] > xs[0] + 3


@pytest.mark.parametrize(
    "lowest, highest, log, marks",
    [
        (0, 10, False, [0, 5, 10]),
        (-0.4, 1.1, False, [-0.0, 0.5, 1.0]),
        (30, 30000, True, [100, 1000, 10000]),
        (41, 381, True, [50, 100, 200]),
    ],
)
def test_auto_marks(lowest, highest, log, marks):
    assert auto_marks(lowest, highest, log) == pytest.approx(marks)


@pytest.mark.parametrize("value, text", [(30000, "30,000"), (3200, "3,200"), (-0.5, "-0.5"), (0.30000000000000004, "0.3"),
                                         (-0.0, "0"), (210.76, "210.76")])
def test_number_text(value, text):
    assert number_text(value) == text


# -- breaking around the foreground, and the foreground left alone (§§15.8, 15.10) --------------------------


def test_the_line_is_broken_around_a_flag_but_crosses_bars_and_poles():
    L = laid('event "An event with a long label" 1950\nspan "Span" 1900-1990\n'
             'graph "" height=10mm range=10 value_scale=off {\n1900 5\n2000 5\n}\n')
    flag = L.events[0].flag_box
    line = L.graphs[0].line
    assert len(line) == 2  # in two pieces
    inner = Box(flag.x0 - 0.7, flag.y0 - 0.7, flag.x1 + 0.7, flag.y1 + 0.7)
    assert not any(segment_crosses(p, q, inner) for piece in line for p, q in zip(piece, piece[1:]))


def test_adding_a_graph_moves_nothing():
    plain = laid(FOREGROUND)
    with_graph = laid(FOREGROUND + 'graph "G" fill=solid {\n1900 1\n1950 -1\n2000 1\n}\n')
    assert (with_graph.bars, with_graph.events, with_graph.ticks) == (plain.bars, plain.events, plain.ticks)


def test_graph_pens_come_straight_after_the_axis_pen():
    L = laid('span "S" 1920-1960 red\ngraph "G" 2H-pencil {\n1900 1\n}\ngraph "H" {\n1900 1\n}\n'
             'graph "I" red {\n1900 1\n}\n')
    assert L.pens == ("black", "2H-pencil", "HB-pencil", "red")
    assert laid('graph "G" black {\n1900 1\n}\n').pens == ("black",)


def test_layout_is_deterministic():
    source = FOREGROUND + 'graph "G" line=smooth fill=diagonal fill_depth=3mm {\n1900 1\n1950 -1\n2000 1\n}\n'
    assert render(laid(source)) == render(laid(source))


# -- shading and drawing (§§15.7, 15.10) -----------------------------------------------------------------------


def shading_strokes(source):
    L = laid(source)
    d = draw(L)
    line = {piece for g in L.graphs for piece in g.line}
    shade = [s for s in d.strokes if s.stage is Stage.BACKGROUND and len(s.points) == 2 and s.points not in line
             and s.points[0][1] == s.points[1][1] and s.points[0][0] != s.points[1][0]]
    return L, d, shade


def test_graphs_are_drawn_after_the_axis_and_before_the_bars():
    L = laid(FOREGROUND + 'graph "G" {\n1900 1\n2000 1\n}\n')
    stages = [s.stage for s in draw(L).strokes]
    assert stages.index(Stage.BACKGROUND) > stages.index(Stage.AXIS)
    assert max(i for i, s in enumerate(stages) if s is Stage.BACKGROUND) < stages.index(Stage.BARS)
    assert {s.pen for s in draw(L).strokes if s.stage is Stage.BACKGROUND} == {"HB-pencil"}


def test_shading_under_the_line_stays_within_its_depth():
    # A flat line 20mm above the baseline: solid shading (horizontal lines) 5mm deep, below it.
    _, _, shade = shading_strokes('graph "" height=20mm fill=solid fill_depth=5mm value_scale=off {\n1900 1\n2000 1\n}\n')
    assert shade and all(BASE - 20 <= s.points[0][1] <= BASE - 15 for s in shade)


def test_shading_reaches_the_baseline_without_a_depth_and_lies_towards_it():
    _, _, shade = shading_strokes('graph "" height=20mm fill=solid value_scale=off {\n1900 1\n2000 1\n}\n')
    assert max(s.points[0][1] for s in shade) == pytest.approx(BASE, abs=0.4)
    _, _, below = shading_strokes('graph "" height=20mm fill=solid fill_depth=5mm value_scale=off {\n1900 -1\n2000 -1\n}\n')
    assert below and all(BASE + 15 <= s.points[0][1] <= BASE + 20 for s in below)


def test_a_shadow_falls_below_and_later():
    L, _, shade = shading_strokes(
        'graph "" height=20mm fill=solid fill_depth=3mm shadow=2mm value_scale=off {\n1910 1\n1990 1\n}\n'
    )
    x0, x1 = x_of(L, "1910"), x_of(L, "1990")
    assert shade and all(BASE - 18 - 1e-6 <= s.points[0][1] <= BASE - 15 + 1e-6 for s in shade)
    assert min(min(p[0] for p in s.points) for s in shade) == pytest.approx(x0 + 2, abs=0.5)
    assert max(max(p[0] for p in s.points) for s in shade) == pytest.approx(x1 + 5, abs=0.5)


def test_shading_is_broken_around_text():
    L, _, shade = shading_strokes('event "An event with a long label" 1950\n'
                                  'graph "" height=10mm range=10 fill=solid value_scale=off {\n1900 9\n2000 9\n}\n')
    flag = L.events[0].flag_box.padded(0.7)
    assert shade and not any(segment_crosses(*s.points, flag) for s in shade)


def test_a_graph_is_a_layer_of_its_own_in_the_svg():
    L = laid('graph "G" {\n1900 1\n2000 1\n}\n')
    svg = render(L, RenderOptions(pen="HB-pencil"))
    assert 'id="HB-pencil-background"' in svg and 'inkscape:label="HB-pencil"' in svg


# -- units and fill pens (§§15.7, 15.9) ----------------------------------------------------------------------


def test_a_unit_heads_every_value_scale_at_the_far_end_of_its_rule():
    L = laid('graph "" unit=MW value_scale=25cm y_scale=log origin=3200 {\n1900 30\n1950 30000\n}\n')
    g = L.graphs[0]
    units = [t for t in g.texts if t.text == "MW"]
    rules = [r for r in g.rules if r[0][0] == r[-1][0]]
    assert len(units) == len(rules) == 5
    for unit, rule in zip(units, rules, strict=True):
        bottom = max(rule[0][1], rule[1][1])  # the rule reaches further below the baseline than above it
        assert unit.box.y0 > bottom and unit.box.x0 > rule[0][0]
        labels = [t for t in g.texts if t.text != "MW" and abs(t.x - unit.x) < 1e-9]
        assert all(not unit.box.overlaps(t.box) for t in labels)


def test_a_unit_goes_to_the_other_end_when_the_far_end_has_no_room():
    # Values below the baseline reaching nearly to the paper's edge: no room for the unit under them.
    L = laid('graph "" unit=% height=96mm value_scale=start {\n1900 -10\n1950 2\n}\n')
    [unit] = [t for t in L.graphs[0].texts if t.text == "%"]
    assert unit.box.y1 < BASE


def test_graph_fill_pen_and_unit_settings():
    g = graph('graph "G" fill=solid fill_pen=4H-pencil unit="°C" {\n1900 1\n}\n')
    assert (g.pen, g.fill_pen, g.unit) == ("HB-pencil", "4H-pencil", "°C")
    plain = graph('graph "G" red {\n1900 1\n}\n')
    assert (plain.fill_pen, plain.unit) == ("red", "")
    assert "bad-value" in codes('graph "G" fill_pen=HB-pencil {\n1900 1\n}\n')  # nothing to fill
    assert "unknown-pen" in codes('graph "G" fill=solid fill_pen=pink {\n1900 1\n}\n')


def test_a_graphs_shading_is_drawn_in_its_fill_pen_and_plotted_early():
    L = laid('span "S" 1910-1990 red\ngraph "G" fill=solid fill_pen=4H-pencil {\n1900 1\n2000 1\n}\n')
    d = draw(L)
    by_pen = {(s.pen, s.stage) for s in d.strokes if s.stage is Stage.BACKGROUND}
    assert by_pen == {("HB-pencil", Stage.BACKGROUND), ("4H-pencil", Stage.BACKGROUND)}
    assert L.pens == ("black", "HB-pencil", "4H-pencil", "red")
    line = set(L.graphs[0].line)
    assert all(s.pen == "HB-pencil" for s in d.strokes if s.points in line)  # the line keeps the graph's pen


@pytest.mark.parametrize("fmt, text, years_before", [("Ma", "66", 66_000_000), ("ka", "11.7", 11_700),
                                                     ("Ga", "4.6", 4_600_000_000), ("ma", "0", 0)])
def test_ages_before_present(fmt, text, years_before):
    assert time_reader(fmt)(text) == DateValue(1950 - years_before).first_second()


def test_ages_before_present_may_have_any_fraction():
    half = time_reader("ka")("0.0005")  # half a year before 1950
    assert half == parse_date("1949-07-02T12:00:00").first_second()
    with pytest.raises(ValueError, match="number of Ma"):
        time_reader("Ma")("66Ma")
