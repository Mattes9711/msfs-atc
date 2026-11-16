"""L6: traffic ahead on the same final: the number in the sequence, whom to follow, speed control to keep the
distance (3 NM, more behind a heavier aircraft), and the landing clearance only once it has landed and vacated."""
from dataclasses import replace

from atc.phraseology import spoken
from tests.test_air_flow import MUNICH_APPROACH, MUNICH_TOWER
from tests.test_ground_flow import confirmed
from tests.test_runway_traffic import landing, munich_runway_mid
from tests.test_traffic_picture import on_final

CS = "Lufthansa four Alfa Bravo"


def emirates(t):
    return replace(t, atc_id="UAE4LK", airline="Emirates", flight_number="", model="B77W")


def test_the_approach_clearance_gives_the_sequence(eddh, eddm):
    from tests.test_air_flow import cleared_for_takeoff
    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 2, 35000)
    s.tick()
    s.say(118205, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")
    s.say(118205, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    s.atc.phase, s.atc.descent_given = "arrival", True
    rwy = s.atc.arrival_runway
    s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    heading = s.atc.pending[-1].value
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 4500 feet, QNH 1019, speed 220 knots, heading {heading}, "
                                            f"Lufthansa 4AB"))
    s.atc.update_traffic([on_final(eddm, rwy, 6, oid=1), on_final(eddm, rwy, 3, oid=2)])
    s.sim.on_final(eddm, eddm.runway_end(rwy), 10)
    assert s.tick() == [f"{CS}, number tree, traffic to follow Lufthansa Airbus on six mile final, "
                        f"cleared ILS approach runway {spoken.runway(rwy)}, speed one eight zero knots"]


def test_tower_continues_the_approach_until_the_one_ahead_has_vacated(eddh, eddm):
    s = landing(eddh, eddm)
    rwy = s.atc.arrival_runway
    ahead = on_final(eddm, rwy, 4)
    s.atc.update_traffic([ahead])
    assert s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS") == [
        f"{CS}, Munich Tower, continue approach, number two, traffic to follow Lufthansa Airbus on four mile final"]
    s.atc.update_traffic([replace(ahead, lat=munich_runway_mid(s, eddm)[0], lon=munich_runway_mid(s, eddm)[1],
                                  on_ground=True, ground_speed_kt=60)])  # landed, rolling out
    assert s.tick() == []
    s.atc.update_traffic([])  # vacated
    [clearance] = s.tick()
    assert clearance.endswith("cleared to land") and "caution" not in clearance


def test_speed_control_when_catching_up(eddh, eddm):
    s = landing(eddh, eddm)
    rwy, end = s.atc.arrival_runway, eddm.runway_end(s.atc.arrival_runway)
    ahead = replace(on_final(eddm, rwy, 6), ground_speed_kt=130)
    s.atc.update_traffic([ahead])
    s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS")
    s.sim.on_final(eddm, end, 8.5)
    s.sim.update(ground_speed_kt=180)
    assert s.tick() == [f"{CS}, reduce speed one six zero knots, traffic ahead"]  # 2.5 NM behind, closing
    assert confirmed(s.say(MUNICH_TOWER, "reduce speed 160 knots, Lufthansa 4AB"))
    assert s.tick() == []  # give it time
    s.sim.on_final(eddm, end, 7.9)
    s.sim.update(ground_speed_kt=170)
    assert s.tick() == [f"{CS}, reduce to final approach speed, traffic ahead"]  # still closing
    s.sim.on_final(eddm, end, 7.0)
    assert s.tick() == []  # told everything there is


def test_no_speed_control_with_enough_distance_or_inside_four_miles(eddh, eddm):
    s = landing(eddh, eddm)
    rwy, end = s.atc.arrival_runway, eddm.runway_end(s.atc.arrival_runway)
    s.atc.update_traffic([replace(on_final(eddm, rwy, 3), ground_speed_kt=120)])
    s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS")
    s.sim.on_final(eddm, end, 6.5)
    s.sim.update(ground_speed_kt=180)
    assert s.tick() == []  # 3.5 NM: enough
    s.atc.update_traffic([replace(on_final(eddm, rwy, 1.5), ground_speed_kt=120)])
    s.sim.on_final(eddm, end, 3.8)
    assert s.tick() == []  # too close in for speed control


def test_behind_a_heavy_more_distance_and_a_wake_caution(eddh, eddm):
    s = landing(eddh, eddm)
    rwy, end = s.atc.arrival_runway, eddm.runway_end(s.atc.arrival_runway)
    ahead = replace(emirates(on_final(eddm, rwy, 6)), ground_speed_kt=140)
    s.atc.update_traffic([ahead])
    assert s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS") == [
        f"{CS}, Munich Tower, continue approach, number two, traffic to follow Emirates Boeing on six mile final"]
    s.sim.on_final(eddm, end, 10.5)
    s.sim.update(ground_speed_kt=180)
    assert s.tick() == [f"{CS}, reduce speed one six zero knots, traffic ahead"]  # 4.5 NM: a medium needs 5
    assert confirmed(s.say(MUNICH_TOWER, "reduce speed 160 knots, Lufthansa 4AB"))
    s.atc.update_traffic([])  # landed and vacated
    [clearance] = s.tick()
    assert clearance.startswith(f"{CS}, caution wake turbulence from the landing Emirates Boeing, ")
    assert clearance.endswith("cleared to land")


def in_pattern(eddm, rwy, along_nm, side_nm, heading_off, oid=5):
    """An arrival beside the final: along_nm out from the threshold, side_nm to the side, heading the runway's
    heading plus heading_off, 2000 ft above the field."""
    from atc.airport.geo import destination_point
    from tests.test_traffic_picture import plane

    end = eddm.runway_end(rwy)
    lat, lon = destination_point(end.lat, end.lon, (end.heading_true + 180) % 360, along_nm)
    lat, lon = destination_point(lat, lon, (end.heading_true + 90) % 360, side_nm)
    return plane(lat, lon, eddm.elevation_ft + 2000, 180, (end.heading_true + heading_off) % 360, False, oid)


def test_traffic_on_downwind_or_base_is_in_the_sequence(eddh, eddm):
    """B6: not only aircraft already on final."""
    s = landing(eddh, eddm)  # we are on a 10 mile final
    rwy = s.atc.arrival_runway
    s.atc.update_traffic([in_pattern(eddm, rwy, 0, 3, 180)])  # abeam the threshold, flying the other way
    assert s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS") == [
        f"{CS}, Munich Tower, continue approach, number two, traffic to follow Lufthansa Airbus on downwind"]
    s.atc.update_traffic([in_pattern(eddm, rwy, 4, 3, -90)])  # turned base
    assert s.atc._sequence(s.sim.read()).endswith("Lufthansa Airbus on base")


def test_a_departure_climbing_out_is_not_in_the_sequence(eddh, eddm):
    s = landing(eddh, eddm)
    rwy = s.atc.arrival_runway
    s.atc.picture.departed.add("D-AIZA")  # seen departing from Munich before
    s.atc.update_traffic([in_pattern(eddm, rwy, 0, 3, 180)])
    [clearance] = s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS")
    assert clearance.endswith("cleared to land")
