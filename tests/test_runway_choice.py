import pytest

from atc.weather.metar import parse_metar
from atc.weather.runway_choice import choose_runway, wind_components


def wx(wind: str):
    return parse_metar(f"EDDH 141450Z {wind} 9999 Q1018")


def test_wind_components():
    c = wind_components(230, 230, 10)
    assert c.headwind == pytest.approx(10) and c.crosswind == pytest.approx(0)
    c = wind_components(230, 320, 10)
    assert c.headwind == pytest.approx(0, abs=1e-9) and c.crosswind == pytest.approx(10)  # from the right
    assert wind_components(230, 50, 10).headwind == pytest.approx(-10)  # tailwind


# EDDH runways (true): 05 = 50.25, 23 = 230.25, 15 = 152.82, 33 = 332.82; 15/33 is the longer one
@pytest.mark.parametrize("wind, runway", [
    ("22007KT", "23"), ("33015KT", "33"), ("05010KT", "05"), ("15008KT", "15"),
])
def test_runway_with_most_headwind(eddh, wind, runway):
    assert choose_runway(eddh, wx(wind)).name == runway


def test_calm_without_current_uses_longest_runway(eddh):
    assert choose_runway(eddh, wx("00000KT")).name in ("15", "33")
    assert choose_runway(eddh, None).name in ("15", "33")


def test_light_wind_picks_the_better_end_of_the_longest_runway(eddh):
    assert choose_runway(eddh, wx("32003KT")).name == "33"


def test_calm_keeps_current_runway(eddh):
    assert choose_runway(eddh, wx("VRB03KT"), current="23").name == "23"


def test_hysteresis_keeps_current_while_still_headwind(eddh):
    # 33 would have more headwind now, but 23 is still fine: don't flip
    assert choose_runway(eddh, wx("30010KT"), current="23").name == "23"


def test_switches_when_tailwind_exceeds_limit(eddh):
    assert choose_runway(eddh, wx("06010KT"), current="23").name == "05"


def test_gusts_count_for_the_tailwind_limit(eddh):
    # 350/08: 4 kt tailwind on 23 is OK, but the 14 kt gust gives 7 kt tailwind
    assert choose_runway(eddh, wx("35008KT"), current="23").name == "23"
    assert choose_runway(eddh, wx("35008G14KT"), current="23").name == "33"


def test_unknown_current_runway_is_ignored(eddh):
    assert choose_runway(eddh, wx("22007KT"), current="99").name == "23"
