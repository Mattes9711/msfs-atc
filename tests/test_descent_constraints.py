"""Milestone 10 D: the descent by the STAR's constraints. Center starts it in time for the STAR's "at or below"
fixes and descends to the first fix's level; Approach's altitude is the final approach fix's; and an aircraft that
doesn't leave its level is asked "confirm descending"."""
from atc.airport.procedures import Leg, Procedure, Procedures
from atc.controller.arrival import plan_arrival
from tests.test_air_flow import HAMBURG_APPROACH
from tests.test_arrival import PROCEDURES, descending, ils
from tests.test_descent import cruising
from tests.test_enroute import CS, SIMBRIEF
from tests.test_ground_flow import confirmed

LANDU = next(w for w in SIMBRIEF.waypoints if w.ident == "LANDU")


def low_star(ceiling_ft):
    """LAND2A with LANDU at or below `ceiling_ft`, at its place on the route."""
    first = Leg("LANDU", LANDU.lat, LANDU.lon, "IF", "at_or_below", ceiling_ft, speed_kt=250)
    last = Leg("OSCAR", 48.4, 12.0, "TF", "at_or_above", 5000)
    return Procedures("EDDM", (Procedure("LAND2A", "star", "08R", (first, last)),), (ils("08R", "OSCAR"),))


def test_the_descent_comes_in_time_for_the_first_fix(eddh, eddm):
    """LANDU 57 track miles out, at or below FL100: from FL300 that is 60 nm of descent before it, so Center
    descends 122 nm out, not at SimBrief's top of descent (83 nm, for the airport: LANDU would be crossed at about
    FL130)."""
    s = cruising(eddh, eddm, "ARMUT")  # 119 nm to go
    assert s.tick() == []  # without procedures: SimBrief's top of descent
    s = cruising(eddh, eddm, "TIPAM")  # 126 nm to go
    s.atc.procedures = low_star(10000)
    assert round(s.atc._top_of_descent_nm(s.sim.read())) == 122
    assert s.tick() == []
    s = cruising(eddh, eddm, "ARMUT")
    s.atc.procedures = low_star(10000)
    assert s.tick() == [f"{CS}, descend flight level one hundred, cleared Landu two Alfa arrival, expect ILS approach "
                        "runway zero eight right"]


def test_a_lower_first_fix_brings_an_earlier_and_lower_descent(eddh, eddm):
    s = cruising(eddh, eddm, "TIPAM")
    s.atc.procedures = low_star(6000)  # 12 nm more
    assert s.tick() == [f"{CS}, descend flight level six zero, cleared Landu two Alfa arrival, expect ILS approach "
                        "runway zero eight right"]


def test_approach_descends_to_the_final_approach_fix_altitude(eddh, eddm):
    s, _ = descending(eddh, eddm)
    assert s.atc._approach_altitude() == 5000  # the ILS's FAF at 5000 ft
    s.atc.arrival = plan_arrival(eddm, "08R", SIMBRIEF, None)
    assert s.atc._approach_altitude() == 4500  # without procedures: 3000 ft above the airport, rounded up
    high = Procedure("I08R", "approach", "08R", (Leg("DX002", 48.4, 12.0, "IF"),
                                                 Leg("FAFXX", 48.4, 11.9, "TF", "at", 9000)), approach_type="ILS")
    s.atc.arrival = plan_arrival(eddm, "08R", SIMBRIEF, Procedures("EDDM", PROCEDURES.stars, (high,)))
    assert s.atc._approach_altitude() == 4500  # 7500 ft above the airport: not a vectors altitude


def read_back_descent(eddh, eddm):
    s, _ = descending(eddh, eddm)
    assert confirmed(s.say(HAMBURG_APPROACH, "descend flight level 100, Landu 2A arrival, Lufthansa 4AB"))
    return s


def test_confirm_descending_when_the_aircraft_stays_level(eddh, eddm):
    s = read_back_descent(eddh, eddm)
    assert s.tick(now=0) == []
    assert s.tick(now=60) == []
    assert s.tick(now=95) == [f"{CS}, confirm descending flight level one hundred"]
    assert confirmed(s.say(HAMBURG_APPROACH, "descending flight level 100, Lufthansa 4AB"))
    assert s.tick(now=300) == []  # asked once


def test_no_question_while_it_descends(eddh, eddm):
    s = read_back_descent(eddh, eddm)
    alt = s.sim.read().alt_msl_ft
    for t in range(0, 600, 60):
        s.sim.update(alt_msl_ft=alt - t * 20)  # 1200 ft a minute
        assert s.tick(now=t) == []
    s.sim.update(alt_msl_ft=10100)  # there
    assert s.tick(now=700) == [] and s.atc.descent_watch is None


def test_a_climb_ends_the_watch(eddh, eddm):
    s = read_back_descent(eddh, eddm)
    from atc.controller import readback as rb
    s.atc._set_pending([rb.level(300)], s.atc.pending_key)
    assert s.atc.descent_watch is None


def test_no_question_without_the_live_clock(eddh, eddm):
    s = read_back_descent(eddh, eddm)
    for _ in range(5):
        assert s.tick() == []  # --text --nosim without a clock: nothing to time
