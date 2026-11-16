import urllib.error

from atc.weather.source import LiveWeather

EDDH = "METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG"


def offline(url, timeout):
    raise urllib.error.URLError("no network")


def test_live_fetch_is_cached(tmp_path):
    weather = LiveWeather(tmp_path, fetch=lambda url, timeout: EDDH + "\n")
    assert weather.metar("eddh") == EDDH
    assert (tmp_path / "EDDH.txt").read_text(encoding="utf-8").strip() == EDDH


def test_offline_falls_back_to_cache(tmp_path):
    LiveWeather(tmp_path, fetch=lambda url, timeout: EDDH).metar("EDDH")
    assert LiveWeather(tmp_path, fetch=offline).metar("EDDH") == EDDH


def test_offline_without_cache_is_none(tmp_path):
    assert LiveWeather(tmp_path, fetch=offline).metar("EDDH") is None


def test_empty_answer_for_unknown_airport_is_none(tmp_path):
    assert LiveWeather(tmp_path, fetch=lambda url, timeout: "").metar("ZZZZ") is None
