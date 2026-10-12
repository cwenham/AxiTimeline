"""draw() and render(): strokes, fills, caps, illustrations, crop marks, windows, bleed, pens and metadata."""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from libaxitl import Box, RenderError, RenderOptions, Stage, draw, layout, parse, parse_date, render
from libaxitl.illustrate import illustration_strokes, parse_transform

T = "timeline start=1900 end=1999 length=1000 width=210 ticks=off\n"
SVG = "{http://www.w3.org/2000/svg}"


def drawing(source, files=None, now=None):
    resolve = (lambda name: files[name]) if files else None
    resolved = layout(parse(source, resolve).document, parse_date(now) if now else None)
    return resolved, draw(resolved)


def strokes(d, stage=None, pen=None):
    return [s for s in d.strokes if (stage is None or s.stage is stage) and (pen is None or s.pen == pen)]


def xs(stroke_list):
    return [x for s in stroke_list for x, _ in s.points]


# -- the illustration flattener ---------------------------------------------------------------------------


def test_shapes_and_transforms_fit_the_box():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        '<g transform="translate(50 0)"><rect x="0" y="0" width="50" height="50" fill="none"/></g>'
        '<circle cx="25" cy="25" r="25"/><line x1="0" y1="50" x2="100" y2="50"/></svg>'
    )
    lines, notes = illustration_strokes(svg, "a.svg", Box(10, 20, 30, 30), 0.1)
    pts = [p for line in lines for p in line]
    assert min(x for x, _ in pts) == pytest.approx(10) and max(x for x, _ in pts) == pytest.approx(30)
    assert min(y for _, y in pts) == pytest.approx(20) and max(y for _, y in pts) == pytest.approx(30)
    rect = next(line for line in lines if len(line) == 5)  # translated square: right half of the box
    assert {round(x, 6) for x, _ in rect} == {20.0, 30.0}
    assert notes == ["filled shapes are drawn as their outlines only"]  # the circle and line use the default fill


def test_what_cant_be_plotted_is_reported_and_left_out():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="10" height="10">'
        '<text x="1" y="5">hi</text><image href="x.png" width="5" height="5"/>'
        '<path d="M0 0 L 10 10" fill="none" stroke="black"/><g style="display:none"><path d="M0 0 L5 0"/></g>'
        "<defs><path id=\"p\" d=\"M0 0 L 1 1\"/></defs></svg>"
    )
    lines, notes = illustration_strokes(svg, "a.svg", Box(0, 0, 10, 10), 0.1)
    assert len(lines) == 1
    assert notes == ["text can't be plotted and is left out", "embedded images can't be plotted and are left out"]


@pytest.mark.parametrize(
    "text, point",
    [
        ("translate(10, 5)", (11, 6)),
        ("scale(2)", (2, 2)),
        ("rotate(90)", (-1, 1)),
        ("rotate(90 1 1)", (1, 1)),
        ("matrix(1 0 0 1 3 4)", (4, 5)),
        ("translate(10) scale(2)", (12, 2)),  # applied right to left: scaled, then moved
    ],
)
def test_transforms(text, point):
    a, b, c, d, e, f = parse_transform(text)
    assert (a + c + e, b + d + f) == pytest.approx(point)  # the point (1, 1)


# -- draw -------------------------------------------------------------------------------------------------


def test_axis_is_drawn_first_in_the_axis_pen():
    resolved, d = drawing(T.replace(" ticks=off", "").replace("length=1000", "length=175") + '^span "s" 1900-1950 red\n')
    assert d.strokes[0].stage is Stage.AXIS and d.strokes[0].pen == "black"
    assert d.strokes[0].points == ((0.0, resolved.baseline_y), (175.0, resolved.baseline_y))
    assert d.pens == ("black", "red", "2H-pencil")  # axis pen first; crop marks in pencil last


def test_a_bar_outline_is_closed_and_avoids_its_label():
    resolved, d = drawing(T + '^span "s" 1900-1950\n')
    bar = resolved.bars[0]
    outline = strokes(d, Stage.BARS)[0]
    assert outline.points[0] == outline.points[-1] == (bar.x0, bar.y0)
    assert set(outline.points) == {(bar.x0, bar.y0), (bar.x0, bar.y1), (bar.x1, bar.y1), (bar.x1, bar.y0)}


def test_a_label_running_past_its_bar_breaks_the_outline():
    resolved, d = drawing(T + '^span "a label much longer than its bar" 1900-1902\n')
    bar = resolved.bars[0]
    label = bar.label.box.padded(0.75)
    outline = [s for s in strokes(d, Stage.BARS) if (bar.x0, bar.y0) in s.points or (bar.x1, bar.y1) in s.points]
    end_edge = [p for s in outline for p in s.points if p[0] == bar.x1]
    assert end_edge and all(not (label.y0 < y < label.y1) for _, y in end_edge)


def test_a_group_is_a_bracket_open_towards_its_members():
    resolved, d = drawing(T + '^group "G" 1900-1950 {\n}\n')
    bar = resolved.bars[0]
    (outline,) = [s for s in strokes(d, Stage.BARS) if (bar.x0, bar.y1) in s.points]
    assert outline.points[0] == (bar.x0, bar.y0) and outline.points[-1] == (bar.x1, bar.y0)
    top_edge = [(p, q) for p, q in zip(outline.points, outline.points[1:], strict=False) if p[1] == q[1] == bar.y0]
    assert top_edge == []  # above the baseline the members are outward, so the top stays open


@pytest.mark.parametrize("style", ["sawtooth", "sine"])
def test_open_and_clipped_ends_get_caps_inside_the_bar(style):
    resolved, d = drawing(T.replace("ticks=off", f"ticks=off open_end_style={style}") + '^span "s" 1850-\n')
    bar = resolved.bars[0]
    assert bar.cap_start and bar.cap_end
    outline = strokes(d, Stage.BARS)[0]
    assert all(bar.x0 <= x <= bar.x1 for x, _ in outline.points)
    caps = [x for x, _ in outline.points if bar.x0 < x < bar.x0 + 2 or bar.x1 - 2 < x < bar.x1]
    assert caps  # torn edges reach into the bar


@pytest.mark.parametrize("fill", ["solid", "diagonal", "crosshatch", "wave", "dots"])
def test_fills_stay_inside_the_bar_and_clear_of_the_label(fill):
    resolved, d = drawing(T + f'^span "Label" 1900-1950 fill={fill}\n')
    unfilled = {s.points for s in drawing(T + '^span "Label" 1900-1950\n')[1].strokes}
    bar = resolved.bars[0]
    label = bar.label.box.padded(0.75)
    hatch = [s for s in d.strokes if s.points not in unfilled]
    assert hatch
    for s in hatch:
        assert all(bar.y0 - 1e-6 <= y <= bar.y1 + 1e-6 for _, y in s.points)
        assert all(bar.x0 - 1e-6 <= x <= bar.x1 + 1e-6 for x, _ in s.points)
        assert all(not (label.x0 + 1e-6 < x < label.x1 - 1e-6) for x, _ in s.points)


def test_fills_are_anchored_to_the_page():
    _, a = drawing(T + '^span "a" 1900-1950 fill=diagonal\n')
    _, b = drawing(T + '^span "a" 1900-1950 fill=diagonal\n^span "b" 1960-1970\n')
    first = lambda d: {s.points for s in strokes(d, Stage.BARS)}  # noqa: E731
    assert first(a) <= first(b)  # adding another bar doesn't move the first one's hatching


def test_events_draw_their_pole_segments_and_flags():
    resolved, d = drawing(T + '^!!span "big" 1900-1999\n^event "e" 1950 time_label=year\n')
    ev = resolved.events[0]
    poles = [s for s in strokes(d, Stage.EVENTS) if len(s.points) == 2 and s.points[0][0] == s.points[1][0] == ev.x]
    assert [(s.points[0][1], s.points[1][1]) for s in poles] == list(ev.pole_segments)


def test_illustrations_are_drawn_inside_their_box_in_their_owners_pen():
    apple = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20"><path d="M0 0 L10 20" stroke="black" fill="none"/></svg>'
    resolved, d = drawing(T + '^span "s" 1900-1950 green illustration(a.svg)\n', files={"a.svg": apple})
    box = resolved.bars[0].illustration.box
    (line,) = strokes(d, Stage.ILLUSTRATIONS)
    assert line.pen == "green"
    assert [v for p in line.points for v in p] == pytest.approx([box.x0, box.y0, box.x1, box.y1])


def test_unplottable_illustration_content_is_a_warning():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text>hi</text></svg>'
    _, d = drawing(T + '^span "s" 1900-1950 illustration(a.svg)\n', files={"a.svg": svg})
    assert [x.code for x in d.diagnostics] == ["illustration-content"]


def test_crop_marks_every_50cm_on_both_edges():
    resolved, d = drawing(T.replace("length=1000", "length=1200"))
    marks = strokes(d, Stage.CROP_MARKS, pen="2H-pencil")
    uprights = [s for s in marks if s.points[0][0] == s.points[1][0]]
    centres = sorted((s.points[0][0], (s.points[0][1] + s.points[1][1]) / 2) for s in uprights)
    assert centres == [(0.0, 0.0), (0.0, 210.0), (500.0, 0.0), (500.0, 210.0), (1000.0, 0.0), (1000.0, 210.0)]
    assert min(x for s in marks for x, _ in s.points) == 0.0  # the arm at the job's start stops there
    assert d.page_margin_mm == 2.5


def test_length_by_pen():
    _, d = drawing(T + '^span "s" 1900-1950 red\n')
    lengths = d.length_by_pen()
    assert list(lengths) == ["black", "red", "2H-pencil"]
    assert lengths["black"] == pytest.approx(1000.0)  # just the baseline: ticks are off
    # crosses at 0, 500 and 1000mm on both edges, 5mm each way, but none reaches past the job's ends
    assert lengths["2H-pencil"] == pytest.approx(2 * ((2.5 + 5) + 10 + (2.5 + 5)))


# -- render -----------------------------------------------------------------------------------------------


def svg_root(text):
    return ET.fromstring(text.encode())


def path_xs(root):
    return [float(v) for p in root.iter(f"{SVG}path") for v in re.findall(r"[ML]?(-?[\d.]+) -?[\d.]+", p.get("d"))]


def test_a_preview_has_every_pen_as_a_layer_at_true_size():
    resolved, d = drawing(T + '^span "s" 1900-1950 red\n')
    root = svg_root(render(resolved, drawing=d))
    assert (root.get("width"), root.get("height"), root.get("viewBox")) == ("1000mm", "215mm", "0 -2.5 1000 215")
    layers = [g.get("{http://www.inkscape.org/namespaces/inkscape}label") for g in root.iter(f"{SVG}g")]
    assert layers == ["black", "red", "2H-pencil"]


def test_a_pen_file_has_only_that_pen_on_the_same_page():
    resolved, d = drawing(T + '^span "s" 1900-1950 red\n')
    preview = svg_root(render(resolved, drawing=d))
    red = svg_root(render(resolved, RenderOptions(pen="red"), drawing=d))
    assert red.get("viewBox") == preview.get("viewBox")
    assert [g.get("id") for g in red.iter(f"{SVG}g")] == ["pen-red"]
    with pytest.raises(RenderError, match="doesn't use the pen 'blue'"):
        render(resolved, RenderOptions(pen="blue"), drawing=d)


def test_a_window_is_cut_geometrically_with_bleed_only_at_cut_edges():
    resolved, d = drawing(T + '^span "s" 1900-1999 fill=diagonal\n')
    middle = svg_root(render(resolved, RenderOptions(window=(300, 200), bleed_mm=2), drawing=d))
    assert middle.get("viewBox") == "298 -2.5 204 215"
    assert min(path_xs(middle)) >= 298 - 1e-6 and max(path_xs(middle)) <= 502 + 1e-6
    start = svg_root(render(resolved, RenderOptions(window=(0, 200), bleed_mm=2), drawing=d))
    assert start.get("viewBox") == "0 -2.5 202 215"  # the job's own start is not a cut
    end = svg_root(render(resolved, RenderOptions(window=(900, 500), bleed_mm=2), drawing=d))
    assert end.get("viewBox") == "898 -2.5 102 215"  # runs past the end: stops there, no bleed


def polylines(text):
    """Every polyline in an SVG's paths, as tuples of (x, y) strings."""
    out = set()
    for p in svg_root(text).iter(f"{SVG}path"):
        for sub in re.findall(r"M[^M]+", p.get("d")):
            numbers = re.findall(r"-?[\d.]+", sub)
            out.add(tuple(zip(numbers[0::2], numbers[1::2], strict=True)))
    return out


def test_a_window_reprints_exactly_what_the_whole_job_drew():
    resolved, d = drawing(T + '^span "s" 1900-1999 fill=crosshatch\n^event "e" 1950\n')
    whole = polylines(render(resolved, drawing=d))
    window = polylines(render(resolved, RenderOptions(window=(400, 200)), drawing=d))
    inside = {line for line in whole if all(400 <= float(x) <= 600 for x, _ in line)}
    assert inside and inside <= window


@pytest.mark.parametrize("window", [(-1, 10), (1000, 10), (5, 0)])
def test_bad_windows(window):
    resolved, d = drawing(T)
    with pytest.raises(RenderError):
        render(resolved, RenderOptions(window=window), drawing=d)


def test_metadata_carries_the_library_fields_and_the_hosts():
    resolved, d = drawing(T + '^span "s" 1900-1950 red\n')
    text = render(resolved, RenderOptions(pen="red", window=(100, 300), bleed_mm=2, metadata={"job-hash": "abc"}), drawing=d)
    job = svg_root(text).find(f"{SVG}metadata/{{urn:axitimeline:job:1}}job")
    assert job.get("pen") == "red" and job.get("job-hash") == "abc"
    assert (job.get("window-start-mm"), job.get("window-end-mm"), job.get("bleed-start-mm")) == ("100", "400", "2")
    assert float(job.get("stroke-length-mm")) > 0
    with pytest.raises(RenderError):
        render(resolved, RenderOptions(metadata={"pen": "x"}), drawing=d)


def test_render_is_deterministic():
    source = T + '^span "s" 1900-1950 fill=wave\nevent "e" 1960 time_label=date\n'
    assert render(*drawing(source)[:1]) == render(*drawing(source)[:1])


def test_strokes_are_all_finite():
    resolved, d = drawing(T + '^span "s" 1850- fill=dots\n')
    assert all(math.isfinite(v) for s in d.strokes for p in s.points for v in p)
