"""L5: the next takeoff waits behind a departure: until it has passed the end of the runway, and behind a heavier
aircraft for the ICAO wake turbulence time."""
from dataclasses import replace

import pytest

from atc.controller import wake
from atc.sim.traffic import Traffic
from tests.test_ground_flow import TOWER, confirmed
from tests.test_runway_traffic import at_holding_point
from tests.test_safety import midpoint, rwy_05_23
from tests.test_tower import WIND

CS = "Lufthansa four Alfa Bravo"


@pytest.mark.parametrize("model, title, cat", [
    ("A388", "", "J"), ("B77W", "", "H"), ("747", "", "H"), ("A333", "", "H"), ("TT:ATCCOM.AC_MODEL_B748.0.text", "", "H"),
    ("A20N", "", "M"), ("A321", "", "M"), ("B738", "", "M"), ("C130", "", "M"), ("", "", "M"),
    ("C172", "", "L"), ("Skyhawk", "", "L"), ("", "Asobo Cessna Caravan", "L"), ("SR22", "", "L"),
])
def test_wake_categories(model, title, cat):
    assert wake.category(model, title) == cat


def test_spacing_times():
    assert wake.departure_spacing_s("H", "M") == 120
    assert wake.departure_spacing_s("H", "M", intersection=True) == 180
    assert wake.departure_spacing_s("J", "H") == 120 and wake.departure_spacing_s("J", "M") == 180
    assert wake.departure_spacing_s("M", "L") == 120
    assert wake.departure_spacing_s("M", "M") == 0 and wake.departure_spacing_s("L", "H") == 0
    assert wake.minutes(30) == "one minute" and wake.minutes(61) == "two minutes"


def heavy(lat, lon, gs=150.0, alt=60.0, ground=True):
    return Traffic(9, lat, lon, alt, gs, 230.0, ground, "UAE4LK", "Emirates", "", "B77W")


def past_the_runway(s, eddh, t):
    far = eddh.runway_end("05")  # departing on 23: the far end
    return replace(t, lat=far.lat - 0.005, lon=far.lon - 0.008, alt_ft=1500, on_ground=False)


def test_behind_a_heavy_departure_two_minutes_wake_turbulence(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    roll = heavy(*midpoint(rwy_05_23(eddh)))
    s.atc.update_traffic([roll], now=0)
    s.atc.update_traffic([past_the_runway(s, eddh, roll)], now=30)  # took off at 30 s
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, runway two tree, line up and wait, expect departure in two minutes, wake turbulence"]
    assert confirmed(s.say(TOWER, "line up and wait runway 23, Lufthansa 4AB"))
    s.atc.update_traffic([past_the_runway(s, eddh, roll)], now=120)
    assert s.tick() == []  # past the end, but not two minutes yet
    s.atc.update_traffic([past_the_runway(s, eddh, roll)], now=153)
    assert s.tick() == [f"{CS}, caution wake turbulence from the departing Emirates Boeing, {WIND}, "
                        f"runway two tree, cleared for takeoff"]


def test_lined_up_behind_a_rolling_heavy_then_told_the_wait(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    roll = heavy(*midpoint(rwy_05_23(eddh)))
    s.atc.update_traffic([roll], now=0)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, behind the departing Emirates Boeing, runway two tree, line up and wait"]
    assert confirmed(s.say(TOWER, "line up and wait runway 23, Lufthansa 4AB"))
    s.atc.update_traffic([past_the_runway(s, eddh, roll)], now=20)
    assert s.tick() == [f"{CS}, expect departure in two minutes, wake turbulence"]
    assert s.tick() == []
    assert s.say(TOWER, "Lufthansa 4AB, ready for departure") == [
        f"{CS}, hold position, expect departure in two minutes, wake turbulence"]
    s.atc.update_traffic([past_the_runway(s, eddh, roll)], now=141)
    [clearance] = s.tick()
    assert clearance.endswith("runway two tree, cleared for takeoff") and "caution wake turbulence" in clearance


def test_behind_a_medium_only_until_it_has_passed_the_runway_end(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    roll = replace(heavy(*midpoint(rwy_05_23(eddh))), atc_id="DLH1AL", airline="Lufthansa", model="A320")
    s.atc.update_traffic([roll], now=0)
    s.atc.update_traffic([replace(roll, alt_ft=400, on_ground=False)], now=10)  # just airborne
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, behind the departing Lufthansa Airbus, runway two tree, line up and wait"]
    assert confirmed(s.say(TOWER, "line up and wait runway 23, Lufthansa 4AB"))
    s.atc.update_traffic([past_the_runway(s, eddh, roll)], now=40)
    assert s.tick() == [f"{CS}, {WIND}, runway two tree, cleared for takeoff"]  # no wake spacing, no caution


def test_a_departure_that_turned_away_frees_the_runway(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    roll = replace(heavy(*midpoint(rwy_05_23(eddh))), model="A320")
    s.atc.update_traffic([roll], now=0)
    s.atc.update_traffic([replace(roll, alt_ft=800, on_ground=False, heading_true=180)], now=10)  # turned left
    assert s.say(TOWER, "Lufthansa 4AB, ready for departure") == [f"{CS}, {WIND}, runway two tree, cleared for takeoff"]


def test_without_a_clock_no_wake_time(eddh, eddm):
    """The fake sim and --text --nosim have no clock: ATC stays deterministic, only the runway end counts."""
    s = at_holding_point(eddh, eddm)
    roll = heavy(*midpoint(rwy_05_23(eddh)))
    s.atc.update_traffic([roll])
    s.atc.update_traffic([past_the_runway(s, eddh, roll)])
    assert s.say(TOWER, "Lufthansa 4AB, ready for departure") == [f"{CS}, {WIND}, runway two tree, cleared for takeoff"]


def close_parallels(eddm, apart_m):
    """EDDM with 08R/26L moved to apart_m south of 08L/26R (really 2300 m: independent runways)."""
    north = next(r for r in eddm.runways if r.ends[0].name == "08L")
    shift = apart_m / 111195
    moved = tuple(replace(r, ends=tuple(replace(e, lat=n.lat - shift, lon=n.lon) for e, n in zip(r.ends, north.ends)))
                  if r.ends[0].name == "08R" else r for r in eddm.runways)
    return replace(eddm, runways=moved)


def test_a_close_parallel_runway_counts_as_one_for_wake_turbulence(eddm):
    """B5: ICAO, parallel runways under 760 m apart: the wake time applies, the runway separation doesn't."""
    from atc.controller.controller import Controller
    from atc.flightplan.model import FlightPlan

    for apart, close in ((500, True), (2300, False)):
        airport = close_parallels(eddm, apart)
        atc = Controller(airport, FlightPlan("DLH4AB", "EDDM", aircraft="A320"), None)
        atc.runway = "26R"
        atc.last_departure["EDDM"] = wake.Departure(9, "26L", 0.0, "H", "the Emirates Boeing")
        atc.traffic_clock = 30.0
        assert (atc._departure_spacing() == "wake turbulence") is close
        atc.traffic_clock = 200.0
        assert atc._departure_spacing() is None  # wake time over; the parallel runway is not ours
