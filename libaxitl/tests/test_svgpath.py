import math

import pytest

from libaxitl.svgpath import (
    PathError,
    apply_matrix,
    bounding_box,
    flatten,
    multiply,
    parse_path,
    to_path_data,
    transform,
)


def test_relative_and_shorthand_commands_become_absolute():
    segs = parse_path("m 1 2 l 3 0 h 1 v 2 z")
    assert segs == (("M", 1.0, 2.0), ("L", 4.0, 2.0), ("L", 5.0, 2.0), ("L", 5.0, 4.0), ("Z",))


def test_implicit_lineto_after_moveto():
    assert parse_path("M 0 0 10 0 10 10") == (("M", 0.0, 0.0), ("L", 10.0, 0.0), ("L", 10.0, 10.0))


def test_quadratic_becomes_cubic():
    (_, (kind, *coords)) = parse_path("M 0 0 Q 3 3 6 0")
    assert kind == "C"
    assert coords == pytest.approx([2, 2, 4, 2, 6, 0])


def test_arcs_become_cubics_on_the_ellipse():
    segs = parse_path("M 10 0 A 10 10 0 0 1 0 10")
    assert segs[-1][0] == "C" and segs[-1][-2:] == (0.0, 10.0)
    for x, y in flatten(segs, 0.2)[0]:
        assert math.hypot(x, y) == pytest.approx(10, abs=0.01)


def test_arc_flags_may_run_together():
    assert parse_path("M0 0 a5 5 0 1010 0")[-1][-2:] == (10.0, 0.0)
    assert parse_path("M0 0 A5 5 0 1 0 10 0") == parse_path("M0 0 a5 5 0 1010 0")


def test_a_large_arc_goes_the_long_way_round():
    small = flatten(parse_path("M 0 0 A 5 5 0 0 1 10 0"), 0.2)[0]
    large = flatten(parse_path("M 0 0 A 5 5 0 1 0 10 0"), 0.2)[0]
    assert min(y for _, y in small) == pytest.approx(-5, abs=0.01)  # sweep 1 in SVG's y-down: up and over
    assert max(y for _, y in large) == pytest.approx(5, abs=0.01)


def test_matrices_compose_inner_first():
    move, double = (1, 0, 0, 1, 10, 0), (2, 0, 0, 2, 0, 0)
    (_, x, y), = apply_matrix([("M", 1, 1)], multiply(move, double))
    assert (x, y) == (12, 2)  # doubled, then moved


def test_flatten_closes_subpaths_and_splits_curves():
    (square,) = flatten(parse_path("M0 0 H2 V2 H0 Z"))
    assert square[0] == square[-1] == (0, 0)
    (curve,) = flatten(parse_path("M0 0 C 0 10 10 10 10 0"), max_piece=1.0)
    assert 20 <= len(curve) <= 32


def test_garbage_is_rejected():
    with pytest.raises(PathError):
        parse_path("M 0 0 L foo")


def test_bounding_box_includes_curve_extrema():
    # The control points pull the curve up to y = 7.5, well below the control points at y = 10.
    box = bounding_box(parse_path("M 0 0 C 0 10 10 10 10 0"))
    assert box == pytest.approx((0, 0, 10, 7.5))
    assert bounding_box(()) is None


def test_transform_flips_font_units_into_svg_orientation():
    segs = transform(parse_path("M 0 0 L 0 100"), scale=0.01, dx=5, dy=20)
    assert to_path_data(segs) == "M 5 20 L 5 19"
