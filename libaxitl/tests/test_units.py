import pytest

from libaxitl.units import UnitError, format_number, parse_length, parse_scale


@pytest.mark.parametrize(
    "text, mm",
    [
        ("210", 210.0),
        ("21cm", 210.0),
        ("0.21m", 210.0),  # exact, not 210.00000000000003
        ("297.5", 297.5),
        ("4mm", 4.0),
        ("15m", 15000.0),
        ("1500cm", 15000.0),
        (".5", 0.5),
        ("0", 0.0),
    ],
)
def test_lengths_are_millimetres(text, mm):
    assert parse_length(text) == mm


@pytest.mark.parametrize("text", ["-5", "5 cm", "5km", "five", "", "5in", "5M"])
def test_bad_lengths(text):
    with pytest.raises(UnitError):
        parse_length(text)


def test_space_before_unit_gets_a_specific_message():
    with pytest.raises(UnitError, match="space"):
        parse_length("5 cm")


def test_scale_is_an_explicit_rate():
    scale = parse_scale("5mm/year")
    assert (scale.mm, scale.unit) == (5.0, "year")
    assert str(parse_scale("0.25mm/second")) == "0.25mm/second"


@pytest.mark.parametrize("text", ["5", "5mm", "5cm/year", "5mm/week", "mm/year"])
def test_bad_scales(text):
    with pytest.raises(UnitError):
        parse_scale(text)


def test_number_formatting_is_compact_and_has_no_negative_zero():
    assert format_number(210.0) == "210"
    assert format_number(1.25) == "1.25"
    assert format_number(-0.0001) == "0"
    assert format_number(2 / 3) == "0.667"
