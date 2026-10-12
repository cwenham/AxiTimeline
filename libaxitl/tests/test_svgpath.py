import pytest

from libaxitl.svgpath import PathError, bounding_box, parse_path, to_path_data, transform


def test_relative_and_shorthand_commands_become_absolute():
    segs = parse_path("m 1 2 l 3 0 h 1 v 2 z")
    assert segs == (("M", 1.0, 2.0), ("L", 4.0, 2.0), ("L", 5.0, 2.0), ("L", 5.0, 4.0), ("Z",))


def test_implicit_lineto_after_moveto():
    assert parse_path("M 0 0 10 0 10 10") == (("M", 0.0, 0.0), ("L", 10.0, 0.0), ("L", 10.0, 10.0))


def test_quadratic_becomes_cubic():
    (_, (kind, *coords)) = parse_path("M 0 0 Q 3 3 6 0")
    assert kind == "C"
    assert coords == pytest.approx([2, 2, 4, 2, 6, 0])


def test_arcs_are_rejected():
    with pytest.raises(PathError, match="arc"):
        parse_path("M 0 0 A 5 5 0 0 1 10 0")


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
