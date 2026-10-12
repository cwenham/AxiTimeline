import datetime as dt

import pytest

from libaxitl.dates import (
    DateError,
    DateRange,
    DateValue,
    Precision,
    civil_from_days,
    days_from_civil,
    parse_date,
    parse_when,
)

DAY = 86400


def seconds(year, month=1, day=1, h=0, m=0, s=0):
    """Seconds on the axis for an AD date, using Python's own calendar as the reference."""
    delta = dt.datetime(year, month, day, h, m, s) - dt.datetime(1970, 1, 1)
    return delta.days * DAY + delta.seconds


def test_calendar_matches_python_for_ad_dates():
    for year, month, day in [(1, 1, 1), (1600, 2, 29), (1970, 1, 1), (1986, 4, 26), (2000, 2, 29), (9999, 12, 31)]:
        assert days_from_civil(year, month, day) * DAY == seconds(year, month, day)
        assert civil_from_days(days_from_civil(year, month, day)) == (year, month, day)


def test_calendar_round_trips_across_bc():
    for days in range(days_from_civil(-800, 1, 1), days_from_civil(5, 1, 1), 997):
        assert days_from_civil(*civil_from_days(days)) == days


def test_no_year_zero_1bc_is_followed_by_1ad():
    end_of_1bc = parse_date("1BC").last_second()
    start_of_1ad = parse_date("1").first_second()
    assert start_of_1ad == end_of_1bc + 1
    # 1 BC (astronomical year 0) is a leap year in the proleptic Gregorian calendar
    assert parse_date("1BC").next_period_start() - parse_date("1BC").first_second() == 366 * DAY


@pytest.mark.parametrize(
    "text, precision",
    [
        ("1963", Precision.YEAR),
        ("1963-11", Precision.MONTH),
        ("1963-11-22", Precision.DAY),
        ("1963-11-22T12", Precision.HOUR),
        ("1963-11-22T12:30", Precision.MINUTE),
        ("1963-11-22T12:30:00", Precision.SECOND),
        ("44BC-03-15", Precision.DAY),
    ],
)
def test_precision_is_kept(text, precision):
    value = parse_date(text)
    assert value.precision is precision
    assert str(value) == text


def test_bc_suffix_variants():
    for text in ["44BC", "44bc", "44BCE", "44bce", "44Bce"]:
        assert parse_date(text).year == -43
    assert str(parse_date("44bce")) == "44BC"
    assert parse_date("44BC-03-15").describe() == "15 March 44 BC"


def test_anchoring_start_end_and_point():
    year = parse_date("1945")
    assert year.first_second() == seconds(1945)
    assert year.last_second() == seconds(1945, 12, 31, 23, 59, 59)
    month = parse_date("1963-11")
    assert month.last_second() == seconds(1963, 11, 30, 23, 59, 59)
    feb_leap = parse_date("2000-02")
    assert feb_leap.last_second() == seconds(2000, 2, 29, 23, 59, 59)
    minute = parse_date("1986-04-26T01:23")
    assert minute.last_second() == seconds(1986, 4, 26, 1, 23, 59)


def test_timezone_offsets_convert_to_utc_and_naive_is_literal():
    assert parse_date("1986-04-26T14:00:00+03:00").first_second() == parse_date("1986-04-26T11:00:00").first_second()
    assert parse_date("1986-04-26T11:00:00Z").first_second() == parse_date("1986-04-26T11:00:00").first_second()
    assert str(parse_date("1986-04-26T14:00:00-05:30")) == "1986-04-26T14:00:00-05:30"


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("0", "no year 0"),
        ("1963-13", "month 13"),
        ("1900-02-29", "no day 29"),  # 1900 is not a leap year
        ("1963-11-22T24:00", "00 to 23"),
        ("1963-11-22T12:60", "00 to 59"),
        ("1963-11-22T12:30:60", "leap seconds"),
        ("1963-1-5", "two digits"),
        ("1963AD", "AD"),
        ("-44", "BC suffix"),
        ("yesterday", "not a date"),
    ],
)
def test_bad_dates_explain_themselves(text, fragment):
    with pytest.raises(DateError, match=fragment):
        parse_date(text)


def test_truncation_for_now():
    now = DateValue.from_datetime(dt.datetime(2026, 10, 12, 15, 4, 5))
    assert str(now.truncate(Precision.YEAR)) == "2026"
    assert str(now.truncate(Precision.DAY)) == "2026-10-12"
    with pytest.raises(ValueError):
        parse_date("2026").truncate(Precision.DAY)


def test_truncating_an_offset_timestamp_goes_through_utc():
    late = parse_date("2026-12-31T23:30:00-01:00")  # 00:30 UTC on 1 January 2027
    assert str(late.truncate(Precision.YEAR)) == "2027"


def test_from_seconds_round_trip():
    value = parse_date("1642-12-25T09:15:30")
    assert DateValue.from_seconds(value.first_second()) == value


# -- ranges ----------------------------------------------------------------------------------------------


def test_year_ranges_use_hyphen():
    r = parse_when("1642-1727")
    assert isinstance(r, DateRange)
    assert (str(r.start), str(r.end)) == ("1642", "1727")
    assert str(r) == "1642-1727"
    bc = parse_when("509BC-27BC")
    assert (bc.start.year, bc.end.year) == (-508, -26)


def test_finer_ranges_use_slash():
    r = parse_when("1986-04-25T14:00:00/1986-04-25T23:10:00")
    assert r.start.precision is Precision.SECOND and r.end.precision is Precision.SECOND
    assert str(parse_when("1962-10-16/1962-10-28")) == "1962-10-16/1962-10-28"
    assert str(parse_when("5/12")) == "5-12"  # / between bare years is fine too


def test_open_ranges():
    assert parse_when("1953-").is_open
    assert parse_when("1953-04-01/").is_open
    assert parse_when("1953/").is_open
    with pytest.raises(DateError, match="with / instead"):
        parse_when("1953-04-")


def test_two_digits_after_a_year_are_a_month():
    value = parse_when("1910-12")
    assert isinstance(value, DateValue) and value.describe() == "December 1910"
    with pytest.raises(DateError, match="write 14/37"):
        parse_when("14-37")


def test_ranges_must_not_end_before_they_start():
    with pytest.raises(DateError, match="before it starts"):
        parse_when("1727-1642")
    assert parse_when("1945/1945").end.year == 1945  # one whole year is fine


@pytest.mark.parametrize("text", ["1963/1964/1965", "/1964"])
def test_malformed_ranges(text):
    with pytest.raises(DateError):
        parse_when(text)
