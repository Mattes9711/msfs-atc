"""Found in the first full test flight, EDDH → EDDM on 2026-11-16 (Milestone 8, part B: the runway at the
destination, the sequence, traffic information and the landing; part C: on the ground)."""
from dataclasses import replace

from atc.intent.parser import parse
from atc.phraseology.farewell import farewell
from tests.test_air_flow import MUNICH_TOWER
from tests.test_approach_sequence import in_pattern
from tests.test_ground_flow import Session
from tests.test_runway_traffic import landing
from tests.test_runway_use import land
from tests.test_safety import midpoint
from tests.test_traffic_info import around
from tests.test_traffic_picture import on_final

CS = "Lufthansa four Alfa Bravo"


def parallel(eddm, end_name):
    """The other runway end at Munich pointing the same way: 26L ↔ 26R, 08L ↔ 08R."""
    return {"26L": "26R", "26R": "26L", "08L": "08R", "08R": "08L"}[end_name]


# --- B1: the landing runway ---------------------------------------------------------------------------------------

def test_a_tie_keeps_the_runway(eddh, eddm):
    """The test flight flipped 26R → 26L → 26R within 7 s during the go-around."""
    s = Session(eddh, destination=eddm)
    land(s, eddm, "26L", 1)
    land(s, eddm, "26L", 2)
    assert s.atc.arrival_runway == "26L"
    land(s, eddm, "26R", 3)
    land(s, eddm, "26R", 4)
    assert s.atc.arrival_runway == "26L"  # two against two: stays
    land(s, eddm, "26R", 5)
    assert s.atc.arrival_runway == "26R"  # more landings on 26R: changes


def test_the_runway_may_still_change_while_vectored(eddh, eddm):
    """It froze at the first call to Approach, before the destination's traffic was seen (40 nm range)."""
    s = Session(eddh, destination=eddm)
    s.atc.phase, s.atc.descent_given = "approach", True  # vectored, not yet cleared for the ILS
    land(s, eddm, "26R", 1)
    land(s, eddm, "26R", 2)
    assert s.atc.arrival_runway == "26R"
    s.atc.approach_cleared = True  # cleared for the ILS: no more changes
    for oid in range(3, 7):
        land(s, eddm, "26L", oid)
    assert s.atc.arrival_runway == "26R"


# --- B2/B3: the sequence ----------------------------------------------------------------------------------------

def test_the_pattern_traffic_of_the_parallel_is_not_ahead_of_us(eddh, eddm):
    """"number six" at Munich: the arrivals for 26R counted for our 26L."""
    s = landing(eddh, eddm)
    ours = s.atc.arrival_runway
    other = parallel(eddm, ours)
    side = 3 if eddm.runway_end(other).lat > eddm.runway_end(ours).lat else -3  # its outer side
    side = side if eddm.runway_end(ours).heading_true > 180 else -side
    s.atc.update_traffic([in_pattern(eddm, other, 0, side, 180)])  # on the parallel's downwind
    [clearance] = s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS")
    assert "number" not in clearance and clearance.endswith("cleared to land")


def test_an_aircraft_without_a_name_is_not_called_traffic_twice(eddh, eddm):
    s = landing(eddh, eddm)
    rwy = s.atc.arrival_runway
    unknown = replace(in_pattern(eddm, rwy, 0, 3, 180), atc_id="N1234", airline="", flight_number="", model="")
    s.atc.update_traffic([unknown])
    assert s.atc._sequence(s.sim.read()) == "number two, traffic to follow on downwind"


# --- B4: traffic information on final ---------------------------------------------------------------------------

def test_on_final_no_traffic_information_about_traffic_behind_or_landing(eddh, eddm):
    s = landing(eddh, eddm)
    s.atc.phase = "final"
    st = s.sim.read()
    heading_true = (st.heading_mag + eddm.mag_var) % 360
    behind = around(st.lat, st.lon, heading_true + 180, 1, st.alt_msl_ft - 1500, heading_true, oid=11)
    assert s.atc.update_traffic([behind], now=0) == []  # "six o'clock, same direction, 1500 below"
    on_parallel = on_final(eddm, parallel(eddm, s.atc.arrival_runway), 6, oid=12)
    assert not [r for r in s.atc.update_traffic([on_parallel], now=10) if "traffic," in r.text]


def test_at_most_one_traffic_information_a_minute(eddh, eddm):
    from tests.test_traffic_info import climbing

    s = climbing(eddh, eddm)
    st = s.sim.read()
    heading_true = st.heading_mag + eddh.mag_var
    one = around(st.lat, st.lon, heading_true + 60, 4, st.alt_msl_ft + 1000, heading_true + 180, oid=21)
    two = around(st.lat, st.lon, heading_true - 60, 4, st.alt_msl_ft + 1000, heading_true + 180, oid=22)
    assert len(s.atc.update_traffic([one], now=100)) == 1
    assert s.atc.update_traffic([one, two], now=130) == []  # 30 s later: not yet
    assert len(s.atc.update_traffic([one, two], now=161)) == 1  # a minute later: the second one


# --- B5: the landing ---------------------------------------------------------------------------------------------

def test_landing_on_another_runway_is_no_incursion(eddh, eddm):
    """Cleared for 26L, landed on 26R with the traffic: "stop immediately" while rolling out."""
    s = landing(eddh, eddm)
    s.say(MUNICH_TOWER, "Munich Tower, Lufthansa 4AB, established ILS")
    assert s.atc.phase == "landing"
    other = parallel(eddm, s.atc.arrival_runway)
    rwy = next(r for r in eddm.runways if other in (r.ends[0].name, r.ends[1].name))
    lat, lon = midpoint(rwy)
    s.sim.update(lat=lat, lon=lon, alt_msl_ft=eddm.elevation_ft + 9, alt_agl_ft=9.0, on_ground=True,
                 ground_speed_kt=90, heading_mag=eddm.runway_end(other).heading_true - eddm.mag_var)
    out = s.tick()
    assert not any("stop immediately" in line for line in out)
    assert any(line.startswith("(landed on runway") for line in out)


def test_stopping_is_an_acknowledgement():
    assert parse("Lufthansa 758 stopping immediately", "DLH758").kind == "acknowledge"


# --- C: on the ground ---------------------------------------------------------------------------------------------

def at_node(s, node):
    lat, lon = s.atc.taxi.latlon[node]
    s.sim.update(lat=lat, lon=lon, on_ground=True, ground_speed_kt=0)


def beside_the_route_end(s):
    """At A1, another holding point of 23 than the route's A3: Ground's automatic handoff doesn't come."""
    [a1] = [n for n in s.atc.taxi.holding_points("23") if "A1" in {e.name for e in s.atc.taxi.adjacent[n]}]
    at_node(s, a1)
    assert s.tick() == []


def test_on_holding_point_is_a_holding_point_report():
    """C1: "On holding point, Lufthansa 758" got "say again" twice; STT once heard "One holding point"."""
    for text in ("On holding point, Lufthansa 4AB", "One holding point, Lufthansa 4AB",
                 "Lufthansa 4AB, Hamburg Tower, good day, on holding point, runway 33",
                 "Lufthansa 4AB at holding point runway 23"):
        assert parse(text, "DLH4AB").kind == "holding_short", text
    assert parse("taxi to holding point runway 33, via Zulu 1, Lufthansa 4AB", "DLH4AB").kind == "readback"
    assert parse("holding point runway 33, ready for departure, Lufthansa 4AB", "DLH4AB").kind == "ready_departure"


def test_ground_hands_over_to_tower_once_and_tower_keeps_the_aircraft(eddh, eddm):
    """C2: Ground's "contact Tower" was a plain redirect, its readback not recognised ("continue taxi"), Tower sent
    the check-in back to Ground and Ground handed over again two minutes later."""
    from tests.test_ground_flow import GROUND, TOWER, confirmed
    from tests.test_tower import taxiing

    s = taxiing(eddh, eddm)
    beside_the_route_end(s)
    assert s.say(GROUND, "On holding point, Lufthansa 4AB") == [
        f"{CS}, contact Hamburg Tower one two one decimal two eight zero"]
    assert confirmed(s.say(GROUND, "Hamburg Tower 121.280, Lufthansa 4AB"))
    assert s.atc.expected_station().name == "Hamburg Tower"
    [cleared] = s.say(TOWER, "Lufthansa 4AB, Hamburg Tower, good day, on holding point, runway 23")
    assert cleared.endswith("runway two tree, cleared for takeoff")
    assert s.tick() == []  # and no second handoff from Ground


def test_tower_takes_a_check_in_near_the_holding_point(eddh, eddm):
    from tests.test_ground_flow import TOWER
    from tests.test_tower import taxiing

    s = taxiing(eddh, eddm)
    beside_the_route_end(s)
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB") == [f"{CS}, Hamburg Tower, report when ready for departure"]
    assert s.atc.expected_station().name == "Hamburg Tower"


def test_far_from_the_holding_point_tower_still_sends_the_aircraft_to_ground(eddh, eddm):
    from tests.test_ground_flow import TOWER
    from tests.test_tower import taxiing

    s = taxiing(eddh, eddm)  # still at the gate
    [call] = s.say(TOWER, "Hamburg Tower, Lufthansa 4AB")
    assert call.startswith(f"{CS}, contact Hamburg Ground")


def test_an_unknown_request_gets_say_again(eddh, eddm):
    """C3: "request ground services" got no answer at all."""
    from tests.test_ground_flow import GROUND
    from tests.test_tower import taxiing

    s = taxiing(eddh, eddm)
    assert s.say(GROUND, "Lufthansa 4AB request ground services") == [f"{CS}, say again"]


def test_parked_at_the_stand_apron_says_goodbye(eddh, eddm):
    """C6: at the gate nothing more came (user: "just a bye from ATC")."""
    from tests.test_apron import APRON, MUNICH_GROUND
    from tests.test_air_flow import cleared_for_takeoff

    s = cleared_for_takeoff(eddh, eddm)
    s.atc.phase = "vacating"
    s.atc.cleared_runways.add(s.atc._runway_key(eddm, s.atc.arrival_runway))
    s.sim.landed(eddm, eddm.runway_end(s.atc.arrival_runway))
    s.say(MUNICH_GROUND, "Munich Ground, Lufthansa 4AB, request taxi to the gate")
    s.atc.pending = ()
    stand = s.atc.stand_in
    s.sim.update(lat=stand.lat, lon=stand.lon, ground_speed_kt=10)
    assert s.tick() == [f"{CS}, contact Munich Apron one two one decimal seven one zero"]
    s.say(MUNICH_GROUND, "contact Munich Apron 121.710, Lufthansa 4AB")
    assert s.tick() == []  # not yet with Apron: nobody to say goodbye
    s.say(APRON, "Munich Apron, Lufthansa 4AB, with you")
    assert s.tick() == []  # still rolling onto the stand
    s.sim.update(ground_speed_kt=0)
    assert s.tick() == [f"{CS}, {farewell('EDDM', 'Munich Apron')}"]
    assert s.tick() == []  # once

