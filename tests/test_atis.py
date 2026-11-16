import pytest

from atc.controller.atis import Atis
from atc.phraseology import weather
from atc.weather.metar import Cloud, parse_metar

EDDH = parse_metar("METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG")
EDDH_LATER = parse_metar("METAR EDDH 141520Z AUTO 21008KT 9999 FEW034 07/04 Q1018 NOSIG")


def test_eddh_broadcast(eddh):
    atis = Atis(eddh, first_letter="B")
    atis.update(EDDH, "23")
    assert atis.broadcast() == (
        "Hamburg information Bravo, time one four fife zero. Runway in use two tree. "
        "Wind two two zero degrees seven knots, visibility one zero kilometres or more, "
        "scattered tree thousand fife hundred feet, temperature seven, dew point four, QNH one zero one eight. "
        "Advise on initial contact you have information Bravo."
    )


def test_letter_advances_only_on_change(eddh):
    atis = Atis(eddh)
    assert atis.update(EDDH, "23") and atis.letter == "A"
    assert not atis.update(EDDH, "23") and atis.letter == "A"  # same observation, same runway
    assert atis.update(EDDH_LATER, "23") and atis.letter == "B"  # new METAR
    assert atis.update(EDDH_LATER, "33") and atis.letter == "C"  # runway change


def test_letter_wraps_from_zulu_to_alfa(eddh):
    atis = Atis(eddh, first_letter="Z")
    atis.update(EDDH, "23")
    atis.update(EDDH_LATER, "23")
    assert atis.letter == "A"


def test_without_metar(eddh):
    atis = Atis(eddh)
    atis.update(None, "15")
    assert atis.broadcast() == ("Hamburg information Alfa. Runway in use one fife. No weather information "
                                "available. Advise on initial contact you have information Alfa.")


def test_cavok_gusts_and_frost(eddh):
    atis = Atis(eddh)
    atis.update(parse_metar("EDDH 140650Z 25015G28KT CAVOK M03/M07 Q1031"), "23")
    text = atis.broadcast()
    assert "Wind two fife zero degrees one fife knots gusting two eight knots, cav okay" in text
    assert "temperature minus tree, dew point minus seven" in text


@pytest.mark.parametrize("metres, words", [
    (9999, "visibility one zero kilometres or more"),
    (8000, "visibility eight kilometres"),
    (1500, "visibility one thousand fife hundred metres"),
    (350, "visibility tree hundred metres"),
    (50, "visibility less than one hundred metres"),
])
def test_visibility(metres, words):
    assert weather.visibility(metres) == words


@pytest.mark.parametrize("code, words", [
    ("-RA", "light rain"), ("+TSRA", "heavy thunderstorm with rain"), ("TS", "thunderstorm"),
    ("-SHRA", "light rain showers"), ("VCSH", "showers in the vicinity"), ("BR", "mist"),
    ("FZFG", "freezing fog"), ("RASN", "rain and snow"),
])
def test_weather_phenomena(code, words):
    assert weather.phenomenon(code) == words


def test_clouds():
    assert weather.cloud(Cloud("BKN", 1200, "CB")) == "broken one thousand two hundred feet cumulonimbus"
    assert weather.cloud(Cloud("OVC", 800, None)) == "overcast eight hundred feet"
