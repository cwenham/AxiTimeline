"""Baseline ticks (§10): the ladder, day-of-month ticks, BC/AD years, label rungs and coarsening."""

import pytest

from libaxitl.dates import DateValue, Precision, parse_date
from libaxitl.ticks import LADDER, Rung, label_text, nearest_rung, plan_ticks

YEAR = 31556952


def moments(rung: Rung, first: str, last: str) -> list[str]:
    t0, t1 = parse_date(first).first_second(), parse_date(last).last_second()
    precision = Precision.DAY if rung.unit in ("day", "month", "year") else Precision.SECOND
    return [str(DateValue.from_seconds(t, precision)) for t in rung.ticks(t0, t1)]


@pytest.mark.parametrize(
    "ideal, rung",
    [
        (0.2, Rung("second", 1)),
        (40, Rung("second", 30)),
        (100, Rung("minute", 2)),
        (4 * 3600, Rung("hour", 3)),
        (8 * 86400, Rung("day", 10)),
        (0.61 * YEAR, Rung("month", 6)),
        (0.9 * YEAR, Rung("year", 1)),
        (30 * YEAR, Rung("year", 25)),
        (3_000_000 * YEAR, Rung("year", 2_000_000)),
    ],
)
def test_nearest_rung_by_ratio(ideal, rung):
    assert nearest_rung(ideal) == rung


def test_day_of_month_ticks_restart_each_month():
    assert moments(Rung("day", 10), "1986-01", "1986-02") == [
        "1986-01-01", "1986-01-11", "1986-01-21", "1986-02-01", "1986-02-11", "1986-02-21",
    ]
    # the last tick is dropped when it would sit closer than half a step to next month's 1st
    assert moments(Rung("day", 15), "1986-01", "1986-01") == ["1986-01-01", "1986-01-16"]
    assert moments(Rung("day", 1), "2000-02", "2000-02")[-1] == "2000-02-29"


def test_month_ticks():
    assert moments(Rung("month", 3), "1986", "1986") == ["1986-01-01", "1986-04-01", "1986-07-01", "1986-10-01"]


def test_year_ticks_use_written_numbers_across_bc_and_ad():
    # no year zero: 100BC to 100 is 199 years, one short of the other gaps
    assert moments(Rung("year", 100), "350BC", "250") == [
        "300BC-01-01", "200BC-01-01", "100BC-01-01", "100-01-01", "200-01-01",
    ]


def test_fixed_ticks_are_aligned_to_midnight():
    assert moments(Rung("hour", 6), "1986-04-25T14:00:00", "1986-04-26T06:00:00") == [
        "1986-04-25T18:00:00", "1986-04-26T00:00:00", "1986-04-26T06:00:00",
    ]


@pytest.mark.parametrize(
    "tick, label",
    [
        (Rung("year", 2), Rung("year", 10)),  # decades: 5 is skipped because 2 doesn't divide it
        (Rung("year", 20), Rung("year", 100)),  # centuries
        (Rung("minute", 15), Rung("minute", 30)),  # half-hours
        (Rung("month", 1), Rung("month", 3)),
        (Rung("day", 10), Rung("month", 1)),
        (Rung("hour", 12), Rung("day", 1)),
        (Rung("day", 2), Rung("day", 10)),
    ],
)
def test_label_rung_is_the_smallest_larger_rung_whose_ticks_are_all_ticks(tick, label):
    first = next(r for r in LADDER if r.nominal_seconds > tick.nominal_seconds and tick.contains_all_ticks_of(r))
    assert first == label


@pytest.mark.parametrize(
    "seconds, precision, text",
    [
        (parse_date("1610").first_second(), Precision.YEAR, "1610"),
        (parse_date("500BC").first_second(), Precision.YEAR, "500BC"),
        (parse_date("1986-04").first_second(), Precision.MONTH, "1986-04"),
        (parse_date("1986-04-26").first_second(), Precision.DAY, "1986-04-26"),
        (parse_date("1986-04-26T14:00").first_second(), Precision.HOUR, "14:00"),
        (parse_date("1986-04-26T01:23").first_second(), Precision.MINUTE, "01:23"),
        (parse_date("1986-04-26T01:23:44").first_second(), Precision.SECOND, "01:23:44"),
    ],
)
def test_label_format_follows_the_label_rung(seconds, precision, text):
    assert label_text(seconds, precision) == text


def plan(first, last, length, label_every=None, char_mm=2.0):
    t0, t1 = parse_date(first).first_second(), parse_date(last).next_period_start()
    mm_per_s = length / (t1 - t0)
    return plan_ticks(
        t0, t1, lambda t: length * (t - t0) / (t1 - t0), length, mm_per_s, 3.5, label_every,
        lambda s: len(s) * char_mm, 1.0,
    )


def test_plan_labels_every_decade_for_two_year_ticks():
    p = plan("1600", "1699", 175.0)  # 1.75 mm/year: 2-year ticks at 3.5mm
    assert (p.rung, p.label_rung, p.coarsened) == (Rung("year", 2), Rung("year", 10), False)
    assert [m.label for m in p.marks if m.label][:3] == ["1600", "1610", "1620"]


def test_plan_coarsens_labels_that_would_overlap():
    p = plan("1600", "1699", 175.0, char_mm=5.0)  # 20mm labels don't fit 17.5mm apart
    assert p.coarsened and p.label_rung == Rung("year", 20)


def test_plan_with_tick_label_every():
    p = plan("1600", "1699", 175.0, label_every=25)
    assert p.label_rung is None
    # the paper ends exactly at 1 January 1700, and a tick there is still on the paper
    assert [m.label for m in p.marks if m.label] == ["1600", "1650", "1700"]


def test_end_labels_stay_on_the_paper():
    p = plan("1600", "1699", 175.0)
    first = next(m for m in p.marks if m.label)
    assert first.label_x0 == 0.0  # centred on x=0 it would hang off the start


def test_an_end_label_shifted_inward_takes_precedence_over_its_neighbour():
    # 1mm a year with 1-year labels 8mm wide: the ladder settles on decades from the centred labels...
    p = plan("1600", "1699", 100.0, char_mm=2.0)
    assert p.label_rung == Rung("year", 10) and not p.coarsened
    # ...and the end labels, pushed inward, don't overlap anything
    labelled = [m for m in p.marks if m.label]
    assert all(b.label_x0 >= a.label_x0 + a.label_width + 1.0 for a, b in zip(labelled, labelled[1:], strict=False))
    assert all(0 <= m.label_x0 and m.label_x0 + m.label_width <= 100.0 for m in labelled)
    assert all(m.major for m in p.marks if m.seconds in {x.seconds for x in labelled})


def test_a_neighbour_gives_way_to_a_shifted_end_label():
    p = plan("1600", "1609", 100.0, char_mm=2.0)  # 10mm a year: quarterly ticks, 8mm yearly labels fit centred
    assert (p.rung, p.label_rung) == (Rung("month", 3), Rung("year", 1))
    # "1600" is pushed to x=0..8, colliding with "1601" centred at 10 (6..14): 1601 keeps its long tick only
    y1601 = next(m for m in p.marks if m.seconds == parse_date("1601").first_second())
    assert (y1601.major, y1601.label) == (True, None)
    assert [m.label for m in p.marks if m.label][:2] == ["1600", "1602"]
