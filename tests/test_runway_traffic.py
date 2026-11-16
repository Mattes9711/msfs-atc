"""T2: the runway with other aircraft on it or landing on it: departure, landing and crossing wait, and ATC calls
by itself once the runway is free."""
from dataclasses import replace

from tests.test_ground_flow import confirmed
from tests.test_air_flow import MUNICH_TOWER, cleared_for_takeoff, cleared_ils
from tests.test_ground_flow import GROUND, TOWER
from tests.test_safety import at_the_crossing, midpoint, rwy_05_23
from tests.test_tower import WIND, taxiing
from tests.test_traffic_picture import on_final, plane

CS = "Lufthansa four Alfa Bravo"


def at_holding_point(eddh, eddm):
    s = taxiing(eddh, eddm)
    goal = s.atc.taxi.latlon[s.atc.route_out.edges[-1].b]
    s.sim.update(lat=goal[0], lon=goal[1])
    s.tick()  # Ground: "contact Hamburg Tower"
    s.say(GROUND, "contact Tower 121.280, Lufthansa 4AB")
    s.sim.update(com1_khz=TOWER)
    return s


def test_landing_traffic_holds_the_departure_until_it_has_landed(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    arrival = on_final(eddh, "23", 3)
    s.atc.update_traffic([arrival])
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, hold short runway two tree, landing traffic, I will call you"]
    assert confirmed(s.say(TOWER, "holding short runway 23, Lufthansa 4AB"))
    s.atc.update_traffic([replace(arrival, lat=midpoint(rwy_05_23(eddh))[0], lon=midpoint(rwy_05_23(eddh))[1],
                                  on_ground=True, ground_speed_kt=60)])  # landed, still rolling out
    assert s.tick() == []
    gate = eddh.default_parking()
    s.atc.update_traffic([replace(arrival, lat=gate.lat, lon=gate.lon, on_ground=True, ground_speed_kt=15)])  # off
    assert s.tick() == [f"{CS}, {WIND}, runway two tree, cleared for takeoff"]
    assert s.atc.phase == "takeoff"


def test_line_up_behind_a_departure_that_is_rolling(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    roll = plane(*midpoint(rwy_05_23(eddh)), gs=120, hdg=230)
    s.atc.update_traffic([roll])
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, ready for departure") == [
        f"{CS}, behind the departing Lufthansa Airbus, runway two tree, line up and wait"]
    assert confirmed(s.say(TOWER, "line up and wait runway 23, Lufthansa 4AB"))
    s.atc.update_traffic([replace(roll, alt_ft=500, on_ground=False)])  # airborne, still above the runway
    assert s.tick() == []
    far = eddh.runway_end("05")  # the far end of 23
    s.atc.update_traffic([replace(roll, lat=far.lat - 0.005, lon=far.lon - 0.008, alt_ft=1500, on_ground=False)])
    assert s.tick() == [f"{CS}, {WIND}, runway two tree, cleared for takeoff"]


def test_no_traffic_no_waiting(eddh, eddm):
    s = at_holding_point(eddh, eddm)
    s.atc.update_traffic([on_final(eddh, "23", 8)])  # far enough out
    assert s.say(TOWER, "Lufthansa 4AB, ready for departure") == [f"{CS}, {WIND}, runway two tree, cleared for takeoff"]


def landing(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 2, 35000)
    s.tick()
    s.say(118205, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")
    s.say(118205, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    s.atc.phase, s.atc.descent_given = "arrival", True
    cleared_ils(s, eddm)  # on a 10 nm final, handed to Tower
    return s


def munich_runway_mid(s, eddm):
    rwy = next(r for r in eddm.runways if s.atc.arrival_runway in (r.ends[0].name, r.ends[1].name))
    return midpoint(rwy)


def test_landing_waits_for_the_runway_and_comes_by_itself(eddh, eddm):
    s = landing(eddh, eddm)
    blocker = plane(*munich_runway_mid(s, eddm), alt=1500, gs=0)
    s.atc.update_traffic([blocker])
    assert s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS") == [
        f"{CS}, Munich Tower, continue approach, traffic on the runway, I will call you"]
    s.atc.update_traffic([])  # it has vacated
    [clearance] = s.tick()
    assert clearance.endswith("cleared to land")


def test_still_occupied_close_in_is_a_go_around(eddh, eddm):
    s = landing(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    s.atc.update_traffic([plane(*munich_runway_mid(s, eddm), alt=1500)])
    s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS")
    s.sim.on_final(eddm, end, 1.5)
    assert s.tick()[0].startswith(f"{CS}, go around, I say again, go around, runway occupied, fly heading")


def test_cleared_to_land_but_someone_lines_up_is_a_go_around(eddh, eddm):
    s = landing(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS")
    s.say(MUNICH_TOWER, f"cleared to land runway {s.atc.arrival_runway}, Lufthansa 4AB")
    s.atc.update_traffic([plane(*munich_runway_mid(s, eddm), alt=1500)])
    s.sim.on_final(eddm, end, 0.8)
    assert "go around, runway occupied" in s.tick()[0]


def test_crossing_waits_for_landing_traffic(eddh):
    s = at_the_crossing()  # the test airport: runway 18/36 to cross
    s.atc.update_traffic([on_final(s.atc.airport, "18", 2)])
    assert s.say(121900, "Lufthansa 4AB, holding short runway 18") == [
        f"{CS}, hold short runway one eight, landing traffic, I will call you"]
    assert confirmed(s.say(121900, "holding short runway 18, Lufthansa 4AB"))
    assert s.tick() == []
    s.atc.update_traffic([])
    assert s.tick() == [f"{CS}, cross runway one eight"]
    assert confirmed(s.say(121900, "crossing runway 18, Lufthansa 4AB"))
