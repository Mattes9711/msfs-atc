import pytest

from atc.phraseology import spoken


def test_digits_use_icao_pronunciation():
    assert spoken.digits("3590") == "tree fife niner zero"


@pytest.mark.parametrize("cs, words", [
    ("DLH4AB", "Lufthansa four Alfa Bravo"),
    ("DLH759", "Lufthansa seven fife niner"),
    ("BAW12J", "Speedbird one two Juliett"),
    ("D-EABC", "Delta Echo Alfa Bravo Charlie"),  # registration
    ("XYZ123", "X-ray Yankee Zulu one two tree"),  # unknown airline is spelled
])
def test_callsign(cs, words):
    assert spoken.callsign(cs) == words


@pytest.mark.parametrize("feet, words", [
    (12000, "flight level one two zero"),
    (35000, "flight level tree fife zero"),
    (10000, "flight level one hundred"),
    (20000, "flight level two hundred"),
    (9000, "flight level niner zero"),
])
def test_flight_level(feet, words):
    assert spoken.flight_level(feet) == words


@pytest.mark.parametrize("feet, words", [
    (3000, "tree thousand feet"),
    (3500, "tree thousand fife hundred feet"),
    (800, "eight hundred feet"),
    (10000, "one zero thousand feet"),
    (12500, "one two thousand fife hundred feet"),
])
def test_altitude(feet, words):
    assert spoken.altitude(feet) == words


@pytest.mark.parametrize("bad", [0, 3550, -1000])
def test_altitude_rejects_non_hundreds(bad):
    with pytest.raises(ValueError):
        spoken.altitude(bad)


@pytest.mark.parametrize("deg, words", [
    (240, "two four zero"), (5, "zero zero fife"), (0, "tree six zero"), (360, "tree six zero"), (359.6, "tree six zero"),
])
def test_heading_is_three_digits_and_north_is_360(deg, words):
    assert spoken.heading(deg) == words


@pytest.mark.parametrize("khz, words", [
    (121280, "one two one decimal two eight zero"),
    (126855, "one two six decimal eight fife fife"),
    (121500, "one two one decimal fife"),  # last two digits zero -> only four digits
    (118000, "one one eight decimal zero"),
    (118005, "one one eight decimal zero zero fife"),
])
def test_frequency(khz, words):
    assert spoken.frequency(khz) == words


def test_squawk_must_be_octal():
    assert spoken.squawk("4721") == "four seven two one"
    with pytest.raises(ValueError):
        spoken.squawk("4781")


@pytest.mark.parametrize("hpa, words", [(1013, "one zero one tree"), (998, "niner niner eight")])
def test_qnh(hpa, words):
    assert spoken.qnh(hpa) == words


@pytest.mark.parametrize("name, words", [("23", "two tree"), ("05", "zero fife"), ("08L", "zero eight left")])
def test_runway(name, words):
    assert spoken.runway(name) == words


@pytest.mark.parametrize("args, words", [
    ((260, 12), "wind two six zero degrees one two knots"),
    ((0, 0), "wind calm"),
    ((None, 4), "wind variable four knots"),
    ((360, 18, 30), "wind tree six zero degrees one eight knots gusting tree zero knots"),
])
def test_wind(args, words):
    assert spoken.wind(*args) == words


def test_one_knot_is_singular():
    # Found with a real Munich METAR (01001KT): "one knots"
    assert spoken.wind(10, 1) == "wind zero one zero degrees one knot"
    assert spoken.speed(180) == "one eight zero knots"
