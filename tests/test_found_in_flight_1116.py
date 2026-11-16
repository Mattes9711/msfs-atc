"""Found in the first full test flight, EDDH → EDDM on 2026-11-16 (Milestone 8, part B: the runway at the
destination, the sequence, traffic information and the landing)."""
from dataclasses import replace

from atc.intent.parser import parse
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
