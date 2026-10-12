"""layout(): scale and window, sides and lanes, events and flags, illustrations, ticks (§§4, 6–10)."""

import pytest

from libaxitl import AxitlError, Box, FlagDirection, LabelPlacement, Side, layout, parse, parse_date
from libaxitl.geometry import segment_crosses
from libaxitl.dates import DateValue

# 1900 to the end of 1999 on exactly one metre: 10mm a year on average, baseline in the middle (y = 105).
T = "timeline start=1900 end=1999 length=1000 width=210 ticks=off\n"
APPLE = '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="40mm"/>'  # aspect ratio 0.5
FLAG_H = (0.693 + 0.220) * 4  # HersheySans1 line box at the default 4mm


def lay(source, now=None, files=None):
    resolve = (lambda name: files[name]) if files else None
    return layout(parse(source, resolve).document, parse_date(now) if now else None)


def bar(result, label):
    return next(b for b in result.bars if b.entity.label == label)


def event(result, label):
    return next(e for e in result.events if e.entity.label == label)


def codes(result):
    return [d.code for d in result.diagnostics]


def error_codes(source, now=None, files=None):
    with pytest.raises(AxitlError) as info:
        lay(source, now, files)
    return [d.code for d in info.value.errors]


# -- scale, window and baseline (§4) ----------------------------------------------------------------------


def test_time_maps_linearly_onto_the_length():
    r = lay(T)
    assert r.time_to_position(parse_date("1900")) == 0.0
    assert r.time_to_position(parse_date("1950")) == 500.0  # 12 leap days in each half
    assert r.time_to_position(parse_date("1999"), end=True) == 1000.0
    assert (r.length_mm, r.scale_derived, r.scale.unit) == (1000.0, True, "year")


def test_scale_gives_the_length():
    r = lay("timeline start=1900 end=1999 scale=10mm/year width=210\n")
    assert r.length_mm == pytest.approx(1000.0, rel=1e-4)  # a mean Gregorian year is 365.2425 days
    assert not r.scale_derived and str(r.scale) == "10mm/year"


def test_derived_scale_is_shown_in_a_readable_unit():
    r = lay("timeline start=1986-04-25T14:00:00 end=1986-04-26T06:00:00 length=2m width=210\n")
    assert r.scale.unit == "hour" and r.scale.mm == pytest.approx(125.0, rel=1e-4)


@pytest.mark.parametrize("baseline, y", [("low", 210 / 1.618034), ("high", 210 / 1.618034**2), ("middle", 105.0)])
def test_baseline_uses_the_golden_ratio(baseline, y):
    r = lay(T.replace("width=210", f"width=210 baseline={baseline}"))
    assert r.baseline_y == pytest.approx(y, rel=1e-6)
    assert r.above.space_mm + r.below.space_mm == pytest.approx(210)


def test_clipping_open_ends_and_omission():
    r = lay(
        T
        + 'person "early" 1850-1920\nperson "ongoing" 1980-\nspan "late" 1990-2050\n'
        + 'event "gone" 1800\nspan "gone too" 2001-2010\n'
    )
    early, ongoing, late = bar(r, "early"), bar(r, "ongoing"), bar(r, "late")
    assert (early.x0, early.cap_start, early.cap_end) == (0.0, True, False)
    assert (ongoing.x1, ongoing.open_end, ongoing.clipped_end, ongoing.cap_end) == (1000.0, True, False, True)
    assert (late.x1, late.clipped_end, late.cap_end) == (1000.0, True, True)
    assert [e.label for e in r.omitted] == ["gone", "gone too"]
    assert codes(r) == ["outside-window", "outside-window"]


def test_now_is_supplied_by_the_host_and_truncated():
    source = T.replace("end=1999", "end=now")
    r = lay(source, now="2026-10-12")
    assert r.now == DateValue(2026)
    assert r.end_seconds == parse_date("2027").first_second()
    assert lay(T).now is None  # not used, not reported
    assert error_codes(source) == ["needs-now"]
    assert error_codes(source, now="1850") == ["now-before-start"]
    assert error_codes(source.replace("start=1900", "start=1900-01-01"), now="2026") == ["now-too-coarse"]


# -- sides and lanes (§§6, 7, 9) --------------------------------------------------------------------------


def test_higher_priority_takes_the_lower_lane():
    r = lay(T + '^span "low" 1900-1950\n^!span "high" 1920-1960\n')
    assert (bar(r, "high").lane, bar(r, "low").lane) == (0, 1)


def test_bars_that_dont_overlap_share_a_lane():
    r = lay(T + '^span "a" 1900-1910\n^span "b" 1930-1940\n')
    assert (bar(r, "a").lane, bar(r, "b").lane) == (0, 0)


def test_a_label_longer_than_its_bar_occupies_the_lane():
    long = lay(T + '^span "a short span with a long label" 1900-1901\n^span "next" 1905-1920\n')
    assert bar(long, "next").lane == 1
    short = lay(T + '^span "a" 1900-1901\n^span "next" 1905-1920\n')
    assert bar(short, "next").lane == 0


def test_automatic_sides_take_the_lower_lane_then_the_emptier_side():
    r = lay(T + 'span "a" 1900-1950\nspan "b" 1910-1960\nspan "c" 1920-1970\n')
    assert [(b.side, b.lane) for b in r.bars] == [(Side.ABOVE, 0), (Side.BELOW, 0), (Side.ABOVE, 1)]


def test_a_tie_on_a_low_baseline_goes_to_the_roomier_side():
    r = lay(T.replace("width=210", "width=210 baseline=low") + 'vspan "fill" 1900-1999\nspan "a" 1920-1930\n')
    # lane 0 is free above, lane 1 below: lower lane wins
    assert bar(r, "a").side is Side.ABOVE
    r = lay(T.replace("width=210", "width=210 baseline=high") + 'span "a" 1920-1930\n')
    assert bar(r, "a").side is Side.BELOW  # both lane 0; below has more of its width left


def test_a_group_is_placed_before_its_members():
    r = lay(T + 'group "G" 1900-1950 {\n  !!!span "m" 1910-1920\n  vspan "away" 1910-1920\n}\n')
    group, member, away = bar(r, "G"), bar(r, "m"), bar(r, "away")
    assert (group.lane, member.side, member.lane) == (0, group.side, 1)
    assert away.side is Side.BELOW


def test_no_room_is_fatal():
    assert error_codes("timeline start=1900 end=1999 length=1000 width=20 ticks=off\nspan \"s\" 1900-1950\n") == [
        "no-room"
    ]


def test_label_too_tall_for_its_lane():
    assert codes(lay(T + 'span "s" 1900-1950 font_size=7mm\n')) == ["label-too-tall"]


# -- events (§§6.1, 8) ------------------------------------------------------------------------------------


def test_an_event_goes_where_its_pole_is_shorter():
    blocked_above = lay(T + '^!!!span "big" 1900-1999\nevent "e" 1950\n')
    e = event(blocked_above, "e")
    assert e.side is Side.BELOW and e.pole_length == pytest.approx(3 + 1 + FLAG_H)
    open_field = lay(T + 'event "e" 1950\n')
    assert event(open_field, "e").side is Side.ABOVE  # equal poles: the tie-break picks above


def test_only_higher_priority_bars_extend_a_pole():
    lower = lay(T + '^span "low" 1900-1999\n^!event "e" 1950\n')
    assert event(lower, "e").base_pole_length == pytest.approx(3 + 1 + FLAG_H)
    higher = lay(T + '^!!span "high" 1900-1999\n^!event "e" 1950\n')
    # clears lane 0's bar (outer edge 3 + 8 - 1) plus the flag
    assert event(higher, "e").base_pole_length == pytest.approx(10 + 1 + FLAG_H)


def test_a_pole_that_fits_neither_side_is_fatal():
    narrow = "timeline start=1900 end=1999 length=1000 width=20 ticks=off\n"
    assert error_codes(narrow + 'event "e" 1950 font_size=8mm\n') == ["pole-does-not-fit"]


def test_flags_near_the_far_end_point_inward():
    r = lay(T + 'event "early" 1901\nevent "late" 1999-12\n')
    assert event(r, "early").direction is FlagDirection.RIGHT
    assert event(r, "late").direction is FlagDirection.LEFT
    assert event(r, "late").flag.box.x1 <= 1000.0


def test_colliding_flags_are_staggered_by_priority():
    r = lay(T + '^event "first" 1950\n^!event "second" 1950\n')
    first, second = event(r, "first"), event(r, "second")
    assert first.pole_length == first.base_pole_length
    assert second.pole_length >= first.pole_length + FLAG_H
    assert not first.flag.box.overlaps(second.flag.box)
    assert codes(r) == []


def test_a_flag_crossed_by_a_taller_pole_flips():
    r = lay(T + '^event "A long label for this event" 1950\n^!event "B" 1951\n')
    a, b = event(r, "A long label for this event"), event(r, "B")
    assert b.pole_length > a.pole_length  # B has priority, so B is taller
    assert (a.direction, b.direction) == (FlagDirection.LEFT, FlagDirection.RIGHT)  # B's pole no longer crosses A
    assert codes(r) == []


def test_flags_lift_clear_of_bar_labels():
    r = lay(T + '^span "Delayed test window" 1950-1960\n^event "Test delayed" 1950\n')
    label, flag = bar(r, "Delayed test window").label.box, event(r, "Test delayed").flag.box
    assert not flag.overlaps(label) and flag.y1 < label.y0


def test_unresolvable_collisions_are_a_warning():
    narrow = "timeline start=1900 end=1999 length=60 width=22 ticks=off\n"
    r = lay(narrow + '^event "A label far too long" 1950\n^event "Another long label" 1950\n')
    assert "label-collision" in codes(r)


# -- illustrations (§3.5) ---------------------------------------------------------------------------------


def test_a_bar_illustration_reserves_lanes_just_outward_of_its_bar():
    r = lay(T + '^span "s" 1900-1950 illustration(a.svg)\n', files={"a.svg": APPLE})
    ill = bar(r, "s").illustration
    assert (ill.lane, ill.lanes) == (1, 2)  # default height: two lanes
    assert (ill.box.x0, ill.box.x1) == (0.0, 8.0)  # 16mm tall at a 0.5 aspect ratio
    assert (ill.box.y0, ill.box.y1) == pytest.approx((105 - 3 - 8 - 16, 105 - 3 - 8))


def test_an_illustration_height_rounds_up_to_whole_lanes():
    r = lay(T + '^span "s" 1900-1950 illustration(a.svg height=20mm)\n', files={"a.svg": APPLE})
    assert bar(r, "s").illustration.lanes == 3


def test_an_event_illustration_sits_beside_its_pole():
    r = lay(T + '^event "e" 1950 illustration(a.svg)\n', files={"a.svg": APPLE})
    ill = event(r, "e").illustration
    assert (ill.lane, ill.box.x1) == (0, pytest.approx(500 - 1.5))  # left of the pole, clear of the flag


def test_an_illustration_in_a_poles_path_is_nudged():
    source = T + '^!!span "tall" 1900-1999\n^!span "s" 1940-1960 illustration(a.svg)\n^event "e" 1940-06\n'
    r = lay(source, files={"a.svg": APPLE})
    ill, e = bar(r, "s").illustration, event(r, "e")
    assert e.pole_length > 105 - ill.box.y1  # the pole reaches the illustration's band
    assert not ill.box.x0 - 1.5 < e.x < ill.box.x1 + 1.5  # and no longer runs through it
    assert ill.box.x0 == pytest.approx(e.x + 1.5)  # moved right, the side with more room
    assert codes(r) == []


def test_no_room_for_an_illustration_is_fatal():
    narrow = "timeline start=1900 end=1999 length=1000 width=40 ticks=off\n"
    assert error_codes(narrow + '^span "s" 1900-1950 illustration(a.svg)\n', files={"a.svg": APPLE}) == [
        "no-room-for-illustration"
    ]


# -- ticks, pens, determinism -----------------------------------------------------------------------------


def test_ticks_hang_below_the_baseline_and_lanes_start_beyond_them():
    r = lay(T.replace(" ticks=off", "").replace("length=1000", "length=175"))  # 1.75mm a year
    labelled = [t for t in r.ticks if t.label]
    assert r.tick_interval == "2 years" and r.tick_label_interval == "10 years"
    assert [t.label.text for t in labelled][:3] == ["1900", "1910", "1920"]
    assert all(t.length == 2.0 for t in labelled) and {t.length for t in r.ticks} == {1.0, 2.0}
    assert all(t.label.box.y0 >= r.baseline_y + 2.0 for t in labelled)
    assert r.below.inner_mm == pytest.approx(2.0 + 0.5 + 0.913 * 3 + 3)
    assert r.above.inner_mm == 3.0


def test_crowded_tick_labels_are_coarsened_with_a_warning():
    r = lay(T.replace(" ticks=off", ""))  # 10mm a year: quarterly ticks; half-year labels would overlap
    assert (r.tick_interval, r.tick_label_interval) == ("3 months", "1 year")
    assert codes(r) == ["tick-labels-coarsened"]


def test_ticks_off():
    r = lay(T)
    assert (r.ticks, r.tick_interval, r.below.inner_mm) == ((), None, 3.0)


def test_pens_axis_pen_first_then_vocabulary_order():
    r = lay(T + '^span "a" 1900-1950 HB-pencil\nevent "b" 1960 red\n')
    assert r.pens == ("black", "red", "HB-pencil")


def test_layout_is_deterministic():
    source = T + 'span "a" 1900-1950\nspan "b" 1910-1960\nevent "c" 1920\n!event "d" 1920\n'
    assert lay(source) == lay(source)


# -- time labels and broken poles (§§3.11, 8) -------------------------------------------------------------

TIME_H = 0.913 * 3  # the time label's line box at three-quarters of 4mm


def test_a_time_label_sits_under_the_label_and_lengthens_the_flag():
    r = lay(T + '^event "e" 1950 time_label=day\n^event "late" 1999-12 time_label=year\n')
    e, late = event(r, "e"), event(r, "late")
    assert e.time_label.text == "1950" and e.time_label.shaped.text == "1950"
    assert e.base_pole_length == pytest.approx(3 + 1 + FLAG_H + 0.4 + TIME_H)
    assert e.time_label.box.y0 >= e.flag.box.y1  # underneath the name
    assert e.time_label.box.x0 == pytest.approx(e.flag.box.x0)  # flag points right: aligned left
    assert late.direction is FlagDirection.LEFT
    assert late.time_label.box.x1 == pytest.approx(late.flag.box.x1)  # points left: aligned right, by the pole
    assert e.flag_box.y0 == e.flag.box.y0 and e.flag_box.y1 == pytest.approx(e.time_label.box.y1)


def segments_in_distance(r, e):
    sign = -1 if e.side is Side.ABOVE else 1
    return [tuple(round((y - r.baseline_y) * sign, 3) for y in seg) for seg in e.pole_segments]


def test_a_pole_is_broken_around_the_bars_it_passes():
    r = lay(T + '^!!span "big" 1900-1999\n^event "e" 1950\n')
    e = event(r, "e")
    # the bar's rectangle runs 4–10mm from the baseline; the pole leaves 0.75mm either side and drops the
    # 0.25mm stub between the bar and its flag
    assert segments_in_distance(r, e) == [(0.0, 3.25), (11.0, round(11 + FLAG_H, 3))]


def test_flags_are_lifted_clear_of_bars_of_any_priority():
    r = lay(T + '^span "low" 1900-1999\n^!event "e" 1950\n')
    low, e = bar(r, "low"), event(r, "e")
    assert e.base_pole_length == pytest.approx(3 + 1 + FLAG_H)  # the lower-priority bar sets no floor...
    assert e.flag_box.y1 < low.y0  # ...but the flag still clears it
    assert codes(r) == []


def test_the_pole_beside_its_own_flag_is_never_broken():
    # 12mm above the baseline: too little to lift the flag clear of the bar, so it stays on it
    narrow = "timeline start=1900 end=1999 length=1000 width=24 ticks=off\n"
    r = lay(narrow + '^span "low" 1900-1999\n^!event "e" 1950\n')
    e = event(r, "e")
    assert e.pole_length == pytest.approx(12.0)
    assert segments_in_distance(r, e) == [(0.0, 3.25), (round(12 - FLAG_H, 3), 12.0)]
    assert "label-collision" in codes(r)


def test_a_pole_is_broken_around_a_tick_label():
    r = lay(T.replace(" ticks=off", "").replace("length=1000", "length=175") + 'vevent "e" 1910\n')
    e = event(r, "e")
    label = next(t.label for t in r.ticks if t.label and t.label.text == "1910")
    for y0, y1 in e.pole_segments:
        assert y1 <= label.box.y0 or y0 >= label.box.y1
    assert len(e.pole_segments) == 2


# -- bar labels too long for their bars (§7) --------------------------------------------------------------

LONG = "A long label for a short bar"


def test_a_label_that_fits_stays_inside():
    b = bar(lay(T + '^span "Fits" 1900-1950\n'), "Fits")
    assert b.label_placement is LabelPlacement.INSIDE
    assert b.x0 < b.label.box.x0 and b.label.box.x1 < b.x1


def test_a_long_label_goes_beside_its_bar_when_theres_room():
    b = bar(lay(T + f'^span "{LONG}" 1950-1951\n'), LONG)
    assert (b.label_placement, b.leader) == (LabelPlacement.BESIDE, None)
    assert b.label.box.x0 == pytest.approx(b.x1 + 1.5)
    assert b.y0 < b.label.box.y0 < b.label.box.y1 < b.y1  # same lane


def test_at_the_paper_end_it_goes_before_the_bar_instead():
    b = bar(lay(T + f'^span "{LONG}" 1998-1999\n'), LONG)
    assert b.label_placement is LabelPlacement.BESIDE
    assert b.label.box.x1 == pytest.approx(b.x0 - 1.5)


def test_a_long_label_never_pushes_its_bar_outward():
    r = lay(T + f'^!span "Neighbour" 1952-1970\n^span "{LONG}" 1949-1950\n')
    assert bar(r, LONG).lane == 0


def test_otherwise_it_is_pulled_out_with_a_45_degree_leader():
    r = lay(T + f'^!span "Neighbour" 1952-1970\n^span "{LONG}" 1949-1950\n')
    b = bar(r, LONG)
    assert b.label_placement is LabelPlacement.PULLED_OUT
    (ax, ay), (ex, ey) = b.leader
    assert (ax, ay) == pytest.approx(((b.x0 + b.x1) / 2, b.y0))  # the middle of the bar's outer edge
    assert ex - ax == pytest.approx(ay - ey) == pytest.approx(5.0)  # 45°, up to the middle of the next lane
    assert b.label.box.x0 == pytest.approx(ex + 0.5)  # pointing at the start of the label
    assert b.leader_segments == (b.leader,)  # nothing in the way


def test_it_is_pulled_out_leftwards_when_the_paper_ends():
    r = lay(T + f'^!span "Neighbour" 1980-1993\n^span "{LONG}" 1995-1996\n')
    b = bar(r, LONG)
    (ax, _), (ex, _) = b.leader
    assert b.label_placement is LabelPlacement.PULLED_OUT and ex < ax
    assert b.label.box.x1 == pytest.approx(ex - 0.5)


def test_a_leader_is_broken_around_the_bars_it_crosses():
    r = lay(T + f'^!!!span "Close" 1952-1970\n^!!span "{LONG}" 1949-1950\n^!span "Roof" 1940-1970\n')
    b, roof = bar(r, LONG), bar(r, "Roof")
    assert b.leader[1][1] == pytest.approx(105 - (3 + 2 * 8 + 4))  # two lanes out
    assert len(b.leader_segments) == 2
    for p, q in b.leader_segments:
        assert not segment_crosses(p, q, Box(roof.x0, roof.y0, roof.x1, roof.y1))


def test_no_room_within_three_lanes_overruns_with_a_warning():
    roofs = "".join(f'^!span "R{n}" 1900-1999\n' for n in (1, 2, 3))
    r = lay(T + f'^!!!span "Wall" 1952-1999\n^!!span "{LONG}" 1949-1950\n' + roofs)
    b = bar(r, LONG)
    assert b.label_placement is LabelPlacement.OVERRUN
    assert b.label.box.x0 == pytest.approx(b.x0 + 1.5)
    assert codes(r) == ["label-crowded"]


def test_flags_clear_leaders_and_pulled_out_labels():
    r = lay(T + f'^!span "Neighbour" 1952-1970\n^span "{LONG}" 1949-1950\n^event "Event" 1950-06\n')
    b, e = bar(r, LONG), event(r, "Event")
    assert not segment_crosses(*b.leader, e.flag_box.padded(0.4))
    assert not e.flag_box.overlaps(b.label.box)
