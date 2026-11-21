from dataclasses import replace

import pytest

from atc.airport.model import Frequency
from atc.controller.safety import RunwayZones
from atc.flightplan.model import FlightPlan
from atc.phraseology import spoken
from atc.weather.metar import parse_metar
from tests.test_ground_flow import confirmed
from tests.test_air_flow import HAMBURG_APPROACH, MUNICH_APPROACH, MUNICH_TOWER, cleared_for_takeoff, cleared_ils
from tests.test_ground_flow import GROUND, TOWER, Session
from tests.test_taxi import RWY_09_27, airport, path, runway


@pytest.fixture
def departed(eddh, eddm):
    return cleared_for_takeoff(eddh, eddm)


def midpoint(rwy):
    return (rwy.ends[0].lat + rwy.ends[1].lat) / 2, (rwy.ends[0].lon + rwy.ends[1].lon) / 2


def rwy_05_23(eddh):
    return next(r for r in eddh.runways if r.ends[0].name == "05")


def taxiing(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    s.say(GROUND, "Lufthansa 4AB, request taxi")
    s.say(GROUND, "holding point A3 runway 23, Lufthansa 4AB")
    return s


def test_hold_short_points_set_the_protected_distance(eddh):
    s = Session(eddh)
    zones = RunwayZones(eddh, s.atc.taxi)
    limits = s.atc.taxi.strip_limit_m
    assert all(40 < limit < 200 for limit in limits.values())
    assert zones.runway_at(*midpoint(rwy_05_23(eddh))) == rwy_05_23(eddh)
    gate = eddh.default_parking()
    assert zones.runway_at(gate.lat, gate.lon) is None


def test_entering_a_runway_without_clearance_stops_the_aircraft(eddh, eddm):
    s = taxiing(eddh, eddm)
    s.sim.update(lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1])
    assert s.tick() == ["(runway incursion: runway 05/23 without clearance)",
                        "Lufthansa four Alfa Bravo, stop immediately, stop immediately"]
    assert s.tick() == []  # said once, not every second


def test_a_flight_loaded_on_the_runway_gets_a_hint_not_a_stop(eddh):
    # Found live: MSFS had loaded the flight on runway 23 at EDDH
    s = Session(eddh)
    s.sim.update(lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1])
    assert s.tick() == ["(the aircraft starts on runway 05/23; ATC expects a start at a gate or parking position)"]
    assert s.tick() == []
    gate = eddh.default_parking()
    s.sim.update(lat=gate.lat, lon=gate.lon)
    s.tick()
    s.sim.update(lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1])
    assert "stop immediately" in s.tick()[1]  # driving back onto it is an incursion


def test_on_the_runway_with_takeoff_clearance_is_fine(departed, eddh):
    departed.sim.update(lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1])
    assert departed.tick() == []


def test_ground_hands_off_to_tower_at_the_holding_point(eddh, eddm):
    s = taxiing(eddh, eddm)
    goal = s.atc.route_out.edges[-1].b
    s.sim.update(lat=s.atc.taxi.latlon[goal][0], lon=s.atc.taxi.latlon[goal][1])
    assert s.tick() == ["Lufthansa four Alfa Bravo, contact Hamburg Tower one two one decimal two eight zero"]
    assert s.tick() == []
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure")[0].endswith("cleared for takeoff")


def crossing_airport():
    a = airport([RWY_09_27, runway("18", 1000, 1200, "36", 1000, 200, 180)], [
        path((500, 800), (500, 600), "", type="P", start="P"),
        path((500, 600), (950, 600), "A", end="HSND"),
        path((950, 600), (1050, 600), "A", start="HSND"),
        path((1050, 600), (1500, 600), "A"),
        path((1500, 600), (1500, 90), "A5", end="HSND"),
    ], gate=(500, 800))
    return replace(a, frequencies=(Frequency("G", "Test", 121900), Frequency("T", "Test", 118500)))


def at_the_crossing():
    s = Session(crossing_airport(), plan=FlightPlan("DLH4AB", "TEST"),
                metar=parse_metar("TEST 141450Z 27010KT 9999 Q1013"))
    s.say(121900, "Lufthansa 4AB, request clearance information alpha")
    s.say(121900, f"runway 27, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert s.say(121900, "Lufthansa 4AB, request taxi") == [
        "Lufthansa four Alfa Bravo, taxi to holding point Alfa fife runway two seven, via Alfa, "
        "hold short runway one eight"]
    s.say(121900, "holding point alpha 5 runway 27 via alpha, hold short runway 18, Lufthansa 4AB")
    [(runway_name, hold)] = s.atc.crossing_points(s.atc.route_out)
    assert runway_name == "18"
    s.sim.update(lat=s.atc.taxi.latlon[hold][0], lon=s.atc.taxi.latlon[hold][1], ground_speed_kt=0)
    return s


def on_runway_18(s):
    rwy = next(r for r in s.atc.airport.runways if r.ends[0].name == "18")
    s.sim.update(lat=midpoint(rwy)[0], lon=midpoint(rwy)[1])


def test_the_pilot_reports_holding_short_and_gets_the_crossing_clearance():
    # Found in the first flight (EDDH): ATC crossed the pilot by itself and didn't understand the report
    s = at_the_crossing()
    assert s.tick() == []  # ATC doesn't clear a crossing on its own
    assert s.say(121900, "Test Ground, Lufthansa 4AB, holding short runway 18") == [
        "Lufthansa four Alfa Bravo, cross runway one eight"]
    assert confirmed(s.say(121900, "crossing runway 18, Lufthansa 4AB"))
    # crossing now is no incursion
    on_runway_18(s)
    assert "stop immediately" not in " ".join(s.tick())


def test_crossing_without_a_clearance_is_still_an_incursion():
    s = at_the_crossing()
    on_runway_18(s)
    assert "stop immediately" in " ".join(s.tick())


def test_a_silent_pilot_at_the_crossing_gets_a_hint_after_15_seconds():
    s = at_the_crossing()
    assert s.tick(now=100) == [] and s.tick(now=114) == []
    assert s.tick(now=115) == ['(you are holding short of runway 18: report it, e.g. "Test Ground, Lufthansa four '
                               'Alfa Bravo, holding short runway one eight")']
    assert s.tick(now=130) == []  # once
    assert s.say(121900, "Lufthansa 4AB, holding short 18") == ["Lufthansa four Alfa Bravo, cross runway one eight"]


def test_no_hint_while_rolling_or_without_a_clock():
    s = at_the_crossing()
    assert s.tick() == [] and s.tick() == []  # text mode: no clock, no hint
    s.sim.update(ground_speed_kt=8)
    assert s.tick(now=100) == [] and s.tick(now=200) == []


@pytest.mark.parametrize("call", ["Lufthansa 4AB, ready to cross runway 18", "Lufthansa 4AB, request crossing runway 18",
                                  "holding short of runway one eight, Lufthansa 4AB",
                                  "Lufthansa 4AB, holding short"])  # no runway: the next one on the route
def test_ways_to_report_at_a_crossing(call):
    assert at_the_crossing().say(121900, call) == ["Lufthansa four Alfa Bravo, cross runway one eight"]


def test_holding_short_of_the_departure_runway_goes_to_tower():
    s = at_the_crossing()
    s.say(121900, "Lufthansa 4AB, holding short runway 18")
    s.say(121900, "crossing runway 18, Lufthansa 4AB")
    assert s.say(121900, "Lufthansa 4AB, holding short runway 27") == [
        "Lufthansa four Alfa Bravo, contact Test Tower one one eight decimal fife"]
    assert s.say(118500, "Test Tower, Lufthansa 4AB, holding short runway 27") == [
        "Lufthansa four Alfa Bravo, wind two seven zero degrees one zero knots, runway two seven, cleared for takeoff"]


def test_an_unknown_runway_is_asked_again():
    assert at_the_crossing().say(121900, "Lufthansa 4AB, holding short runway 33") == [
        "Lufthansa four Alfa Bravo, say again the runway"]


def test_multi_segment_crossing_holds_at_the_hold_short_not_at_the_centreline_segment():
    # Like KJFK: hold short at x=900, then two segments inside the protected area before the one over the
    # centreline (x=1000). Holding at the start of the centreline segment would already be an incursion.
    a = airport([RWY_09_27, runway("18", 1000, 1200, "36", 1000, 200, 180)], [
        path((500, 800), (500, 600), "", type="P", start="P"),
        path((500, 600), (900, 600), "A", end="HSND"),
        path((900, 600), (960, 600), "A", start="HSND"),
        path((960, 600), (1040, 600), "A"),
        path((1040, 600), (1500, 600), "A"),
        path((1500, 600), (1500, 90), "A5", end="HSND"),
    ], gate=(500, 800))
    s = Session(replace(a, frequencies=(Frequency("G", "Test", 121900), Frequency("T", "Test", 118500))),
                plan=FlightPlan("DLH4AB", "TEST"), metar=parse_metar("TEST 141450Z 27010KT 9999 Q1013"))
    route = s.atc.taxi_route(s.sim.read())
    [(_, hold)] = s.atc.crossing_points(route)
    assert s.atc.taxi.nodes[hold][0] == pytest.approx(900, abs=1)


def airborne_to_munich(s, eddm):
    s.sim.fly(s.atc.airport, eddm, 2, 35000)
    s.tick()
    s.say(HAMBURG_APPROACH, "Lufthansa 4AB, with you")
    s.say(HAMBURG_APPROACH, "climb flight level 350, Lufthansa 4AB")
    s.atc.phase, s.atc.descent_given = "arrival", True
    cleared_ils(s, eddm)  # on a 10 nm final, handed to Tower


def missed_approach(eddm, rwy_name):
    end = eddm.runway_end(rwy_name)
    heading = round((end.heading_true - eddm.mag_var) / 5) * 5 % 360
    return f"fly heading {spoken.heading(heading)}, climb altitude fife thousand feet, " \
           f"contact Munich Approach one one eight decimal eight tree zero"


def test_pilot_reported_go_around(departed, eddm):
    airborne_to_munich(departed, eddm)
    end = eddm.runway_end(departed.atc.arrival_runway)
    departed.sim.on_final(eddm, end, 10)
    departed.tick()
    departed.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established")
    departed.say(MUNICH_TOWER, f"cleared to land runway {departed.atc.arrival_runway}, Lufthansa 4AB")
    assert departed.say(MUNICH_TOWER, "Going around, Lufthansa 4AB") == [
        f"Lufthansa four Alfa Bravo, roger, {missed_approach(eddm, departed.atc.arrival_runway)}"]
    # Calling Approach as told starts a new approach
    assert "cleared ILS approach" in departed.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, with you")[0]


def test_atc_sends_around_without_landing_clearance(departed, eddm):
    airborne_to_munich(departed, eddm)
    end = eddm.runway_end(departed.atc.arrival_runway)
    departed.sim.on_final(eddm, end, 10)
    departed.tick()  # handed to Tower, but the pilot never calls
    departed.sim.update(com1_khz=MUNICH_TOWER)
    departed.sim.on_final(eddm, end, 1.5)
    assert departed.tick() == [f"Lufthansa four Alfa Bravo, go around, I say again, go around, "
                               f"{missed_approach(eddm, departed.atc.arrival_runway)}"]


def test_unreported_go_around_is_detected(departed, eddm):
    airborne_to_munich(departed, eddm)
    end = eddm.runway_end(departed.atc.arrival_runway)
    departed.sim.on_final(eddm, end, 10)
    departed.tick()
    departed.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established")
    departed.say(MUNICH_TOWER, f"cleared to land runway {departed.atc.arrival_runway}, Lufthansa 4AB")
    departed.sim.on_final(eddm, end, 0.5)  # ~160 ft
    assert departed.tick() == []
    departed.sim.update(alt_agl_ft=800, alt_msl_ft=eddm.elevation_ft + 800)
    out = departed.tick()
    assert out[0] == "(go-around detected)"
    assert out[1] == f"Lufthansa four Alfa Bravo, {missed_approach(eddm, departed.atc.arrival_runway)}"


def test_crossing_clearance_names_the_next_runway_to_hold_short_of():
    """A4: a route over two runways: the first is in the taxi clearance, the next comes with the first crossing."""
    from atc.airport.taxi import Edge, TaxiRoute

    s = at_the_crossing()
    s.atc.route_out = TaxiRoute((Edge(0, 1, "A", 100, False, ("18",)), Edge(1, 2, "A", 100, False, ("09",))), cost=0)
    assert s.say(121900, "Test Ground, Lufthansa 4AB, holding short runway 18") == [
        "Lufthansa four Alfa Bravo, cross runway one eight, hold short runway zero niner"]
    assert confirmed(s.say(121900, "crossing runway 18, holding short runway 09, Lufthansa 4AB"))


def test_a_hold_line_nearer_in_than_the_others_ends_the_runway_there():
    # EDHL, the emulator, 2026-11-19: runway 07's hold lines 166-171 m out, the one on taxiway C 98 m; vacated via C
    # and past its hold line, the median (163 m) still had the aircraft on the runway: "stop immediately" twice
    from tests.test_taxi import ll
    a = airport([RWY_09_27], [
        path((200, 170), (200, 300), "A", start="HSND"), path((800, 170), (800, 300), "B", start="HSND"),
        path((1400, 170), (1400, 300), "D", start="HSND"), path((1800, 100), (1800, 300), "C", start="HSND"),
        path((200, 300), (1800, 300), "L")], gate=(1000, 300))
    zones = RunwayZones(a, Session(a).atc.taxi)
    assert zones.runway_at(*ll(1800, 124)) is None  # past C's hold line, 100 m out
    assert zones.runway_at(*ll(1800, 80)).ends[0].name == "09"  # short of it
    assert zones.runway_at(*ll(800, 150)).ends[0].name == "09"  # short of B's, 170 m out
    assert zones.runway_at(*ll(1000, 0)).ends[0].name == "09"  # on the centreline


def test_past_a_hold_line_a_farther_hold_point_close_by_does_not_matter():
    # EDDH, the emulator, 2026-11-21: past Z5O's hold line (86 m out), at 170 m, a hold point 200 m out was the
    # nearest one; with its line as the edge the aircraft was back "on the runway": stop immediately
    from tests.test_taxi import ll
    a = airport([RWY_09_27], [
        path((1000, 86), (1000, 300), "Z", start="HSND"), path((1100, 200), (1100, 300), "W", start="HSND"),
        path((1000, 300), (1100, 300), "L")], gate=(1050, 300))
    zones = RunwayZones(a, Session(a).atc.taxi)
    assert zones.runway_at(*ll(1060, 170)) is None
    assert zones.runway_at(*ll(1000, 60)).ends[0].name == "09"  # short of Z's hold line
    assert zones.runway_at(*ll(1060, -170)) is None  # the other side: no hold lines there, the median (138 m)
