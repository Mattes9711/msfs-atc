import pytest

from atc.units import format_khz, mhz_to_khz, parse_level, parse_mhz


def test_sim_float_noise_is_rounded_away():
    assert mhz_to_khz(126.85499999999999) == 126855


@pytest.mark.parametrize("text, khz", [("121.28", 121280), ("121,280", 121280), (" 118.0 ", 118000)])
def test_parse_mhz(text, khz):
    assert parse_mhz(text) == khz


@pytest.mark.parametrize("text", ["", "abc", "117.975", "137.000", "1212.80"])
def test_parse_mhz_rejects_garbage_and_out_of_band(text):
    with pytest.raises(ValueError):
        parse_mhz(text)


def test_format_khz_keeps_three_decimals():
    assert format_khz(121280) == "121.280"
    assert format_khz(118005) == "118.005"


@pytest.mark.parametrize("text, ft", [("FL240", 24000), ("fl90", 9000), ("5000", 5000)])
def test_parse_level(text, ft):
    assert parse_level(text) == ft
