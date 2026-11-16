"""L2: the runway in use follows the real traffic (LiveTraffic), not only the METAR."""
from atc.airport.geo import destination_point
from tests.test_ground_flow import GROUND, Session
from tests.test_safety import midpoint
from tests.test_traffic_picture import on_final, plane


def runway(airport, end_name):
    return next(r for r in airport.runways if end_name in (r.ends[0].name, r.ends[1].name))


def land(s, airport, end_name, oid):
    """An aircraft on a 3 nm final, then on the runway: one landing."""
    end = airport.runway_end(end_name)
    first = s.atc.update_traffic([on_final(airport, end_name, 3, oid)])
    rolling = plane(*midpoint(runway(airport, end_name)), alt=airport.elevation_ft, gs=120, hdg=end.heading_true,
                    oid=oid)
    return first + s.atc.update_traffic([rolling])


def depart(s, airport, end_name, oid):
    """An aircraft rolling on the runway, then climbing out ahead of it: one departure."""
    end = airport.runway_end(end_name)
    s.atc.update_traffic([plane(*midpoint(runway(airport, end_name)), alt=airport.elevation_ft, gs=140,
                                hdg=end.heading_true, oid=oid)])
    lat, lon = destination_point(end.lat, end.lon, end.heading_true, 3)
    return s.atc.update_traffic([plane(lat, lon, airport.elevation_ft + 1200, 170, end.heading_true, False, oid)])


def test_the_metar_alone_picks_23(eddh):
    assert Session(eddh).atc.runway == "23"  # wind 220/07


def test_two_landings_against_the_metar_choice_change_the_runway(eddh):
    s = Session(eddh)
    letter = s.atc.atis.letter
    land(s, eddh, "05", 1)
    assert s.atc.runway == "23"  # one aircraft could be a go-around or a training flight
    notes = [r.text for r in land(s, eddh, "05", 2)]  # on final already counts
    assert s.atc.runway == "05" and s.atc.atis.letter != letter
    assert notes == [f"EDDH runway in use now 05, as the traffic uses it (ATIS information {s.atc.atis.letter})"]


def test_departures_decide_the_departure_runway(eddh):
    s = Session(eddh)
    depart(s, eddh, "05", 1)
    depart(s, eddh, "05", 2)
    assert s.atc.runway == "05"


def test_the_clearance_then_names_that_runway(eddh):
    s = Session(eddh)
    land(s, eddh, "05", 1)
    land(s, eddh, "05", 2)
    s.sim.update(com1_khz=GROUND)
    s.tick()
    [clearance] = s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information "
                                f"{s.atc.atis.letter}")[:1]
    assert "runway zero fife" in clearance


def test_no_change_after_the_clearance(eddh):
    s = Session(eddh)
    s.sim.update(com1_khz=GROUND)
    s.tick()
    s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information Alfa")
    land(s, eddh, "05", 1)
    land(s, eddh, "05", 2)
    assert s.atc.runway == "23"


def test_a_new_metar_does_not_undo_the_traffics_runway(eddh):
    from atc.weather.metar import parse_metar
    s = Session(eddh)
    land(s, eddh, "05", 1)
    land(s, eddh, "05", 2)
    s.atc.update_weather(parse_metar("METAR EDDH 141520Z AUTO 23010KT 9999 SCT035 07/04 Q1018 NOSIG"), None)
    assert s.atc.runway == "05"


def test_the_arrival_runway_follows_the_landings_at_the_destination(eddh, eddm):
    s = Session(eddh, destination=eddm)
    assert s.atc.arrival_runway == "08R"  # wind 080/08
    land(s, eddm, "26L", 1)
    land(s, eddm, "26L", 2)
    assert s.atc.arrival_runway == "26L"


def test_departures_only_give_the_direction_for_arrivals(eddh, eddm):
    # At EDDM departures use 26R, arrivals 26L: our 08R turns around to its other end, not onto the departure runway
    s = Session(eddh, destination=eddm)
    depart(s, eddm, "26R", 1)
    depart(s, eddm, "26R", 2)
    assert s.atc.arrival_runway == "26L"


def test_aircraft_on_final_count_too(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.atc.update_traffic([on_final(eddm, "26L", 8, 1), on_final(eddm, "26L", 4, 2)])
    assert s.atc.arrival_runway == "26L"


def test_a_runway_change_after_the_star_is_told_by_radio(eddh, eddm):
    """B3: the descent clearance named the STAR for 08R; the traffic now lands on 26L."""
    from tests.test_air_flow import MUNICH_APPROACH, cleared_for_takeoff

    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 300, 35000)
    s.atc.phase, s.atc.descent_given = "arrival", True
    s.sim.update(com1_khz=MUNICH_APPROACH)
    land(s, eddm, "26L", 1)
    land(s, eddm, "26L", 2)
    assert s.tick() == ["Lufthansa four Alfa Bravo, runway change, expect vectors ILS approach runway two six left"]
    assert s.tick() == []  # told once


def test_no_runway_change_call_before_the_descent_clearance(eddh, eddm):
    s = Session(eddh, destination=eddm)
    land(s, eddm, "26L", 1)
    land(s, eddm, "26L", 2)
    assert s.atc.arrival_runway == "26L" and s.atc.runway_change is None
