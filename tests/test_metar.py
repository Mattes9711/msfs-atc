import pytest

from atc.weather.metar import Cloud, parse_metar

# Real METARs fetched from aviationweather.gov on 2026-11-14
EDDH = "METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG"
EDDM = "METAR EDDM 141450Z AUTO 08008KT CAVOK 06/00 Q1019 NOSIG"
KJFK = "METAR KJFK 141451Z 32011KT 10SM BKN038 BKN090 05/M03 A2978 RMK AO2 SLP083 T00501028 51007 $"


def test_european_metar():
    m = parse_metar(EDDH)
    assert (m.station, m.time) == ("EDDH", "141450Z")
    assert (m.wind_dir, m.wind_kt, m.gust_kt) == (220, 7, None)
    assert m.visibility_m == 9999
    assert m.clouds == (Cloud("SCT", 3500, None),)
    assert (m.temp_c, m.dewpoint_c, m.qnh_hpa) == (7, 4, 1018)


def test_cavok():
    m = parse_metar(EDDM)
    assert m.cavok and m.visibility_m == 10000 and m.clouds == ()


def test_us_metar_converts_miles_and_inches():
    m = parse_metar(KJFK)
    assert m.visibility_m == 16093
    assert m.qnh_hpa == 1008  # 29.78 inHg
    assert m.dewpoint_c == -3
    assert len(m.clouds) == 2


def test_gusts_variable_wind_and_mps():
    assert parse_metar("EDDF 141450Z 25015G28KT 9999 Q1010").gust_kt == 28
    vrb = parse_metar("EDDF 141450Z VRB03KT 9999 Q1010")
    assert (vrb.wind_dir, vrb.wind_kt) == (None, 3)
    assert parse_metar("UUEE 141450Z 18005MPS 9999 Q1010").wind_kt == 10


def test_trend_section_is_ignored():
    m = parse_metar("EDDH 141450Z 22007KT 9999 Q1018 TEMPO 30025G40KT 3000 TSRA")
    assert (m.wind_dir, m.wind_kt, m.weather) == (220, 7, ())


def test_weather_phenomena_and_cb():
    m = parse_metar("EDDH 141450Z 24012KT 4000 -TSRA BR FEW025CB OVC040 12/11 Q1002")
    assert m.weather == ("-TSRA", "BR")
    assert m.clouds[0] == Cloud("FEW", 2500, "CB")


def test_missing_wind_group_is_none_not_calm():
    assert parse_metar("EDDH 141450Z 9999 Q1018").wind_kt is None


@pytest.mark.parametrize("bad", ["", "hello world", "<html>error</html>"])
def test_garbage_is_rejected(bad):
    with pytest.raises(ValueError):
        parse_metar(bad)
