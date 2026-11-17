"""Milestone 10 B: the landing runway fixed with the descent, with the STAR and the approach that fit it.

Munich-like procedures built in code (names as in the SimBrief sample, everything else made up): LAND2A for the 08
runways, LAND2B for the 26 runways, both from LANDU; ILS approaches with transitions from the STARs' last fixes."""
from atc.airport.procedures import Leg, Procedure, Procedures, Transition
from atc.controller.arrival import entry_fix, plan_arrival
from atc.flightplan.model import FlightPlan
from atc.session import find_procedures
from tests.test_air_flow import HAMBURG_APPROACH
from tests.test_descent import cruising
from tests.test_enroute import CS, SIMBRIEF
from tests.test_runway_use import land

LANDU = Leg("LANDU", 48.95, 12.50, "IF", "at_or_below", 10000, speed_kt=250)


def fix(ident, path="TF", alt=None, alt_ft=None):
    return Leg(ident, 48.4, 12.0, path, alt, alt_ft)


def star(name, runway, last):
    return Procedure(name, "star", runway, (LANDU, fix(last, alt="at_or_above", alt_ft=5000)))


def ils(runway, transition):
    legs = (fix(transition), fix("DX001", "FM"), fix("DX002", "CF", "at_or_above", 5000))
    return Procedure(f"I{runway}", "approach", runway, (fix("DX002", "IF"), fix("FAFXX", alt="at", alt_ft=5000)),
                     (Transition(transition, legs),), "ILS")


PROCEDURES = Procedures("EDDM", (
    star("LAND2A", "08R", "OSCAR"), star("LAND2A", "08L", "OSCAR"),
    star("LAND2B", "26R", "MIKEY"), star("LAND2B", "26L", "MIKEY"),
), (ils("08R", "OSCAR"), ils("08L", "OSCAR"), ils("26R", "MIKEY"), ils("26L", "MIKEY")))


def descending(eddh, eddm, runway=None, procedures=PROCEDURES):
    s = cruising(eddh, eddm, "EXUSI")  # just before the top of descent
    s.atc.procedures = procedures
    if runway:
        s.atc.arrival_runway = runway
    return s, s.tick()


def test_the_star_for_the_landing_runway_not_the_filed_one(eddh, eddm):
    s, calls = descending(eddh, eddm, "26R")  # filed: LAND2A, for the 08 runways
    assert calls == [f"{CS}, descend flight level one hundred, cleared Landu two Bravo arrival, expect ILS approach "
                     "runway two six right"]
    a = s.atc.arrival
    assert (a.runway, a.star.name, a.approach.name, a.transition.name) == ("26R", "LAND2B", "I26R", "MIKEY")
    assert a.transition.vectors_from.ident == "DX001"  # where Approach's vectors start (part E)


def test_the_filed_star_when_it_fits(eddh, eddm):
    s, calls = descending(eddh, eddm)  # the METAR: 08R
    assert calls[0].endswith("cleared Landu two Alfa arrival, expect ILS approach runway zero eight right")
    assert s.atc.arrival.transition.name == "OSCAR"


def test_without_procedures_the_filed_star(eddh, eddm):
    s, calls = descending(eddh, eddm, "26R", procedures=None)
    assert calls[0].endswith("cleared Landu two Alfa arrival, expect ILS approach runway two six right")
    assert s.atc.arrival.star is None and s.atc.arrival.approach_kind == "ILS"


def test_after_the_descent_the_parallel_runway_stays(eddh, eddm):
    """The 2026-11-17 flight: 26L, then ten minutes before landing 26R, only because the traffic used it."""
    s, _ = descending(eddh, eddm)
    s.say(HAMBURG_APPROACH, "descend flight level 100, Landu 2A arrival, Lufthansa 4AB")
    land(s, eddm, "08L", 1)
    land(s, eddm, "08L", 2)
    assert s.atc.arrival_runway == "08R" and s.atc.runway_change is None


def test_a_turned_runway_brings_the_new_star(eddh, eddm):
    s, _ = descending(eddh, eddm)
    s.say(HAMBURG_APPROACH, "descend flight level 100, Landu 2A arrival, Lufthansa 4AB")
    land(s, eddm, "26L", 1)
    land(s, eddm, "26L", 2)
    assert s.atc.arrival_runway == "26L"
    assert s.tick() == [f"{CS}, runway change, cleared Landu two Bravo arrival, expect ILS approach runway two six "
                        "left"]
    assert s.atc.arrival.star.name == "LAND2B" and s.atc.arrival.transition.name == "MIKEY"


def test_the_entry_fix_from_the_plan():
    plan = FlightPlan("DLH4AB", "EDDH", "EDDM", route="LULAR T105 LANDU")
    assert entry_fix(plan, PROCEDURES) == "LANDU"  # no STAR filed: the route's last fix
    assert entry_fix(SIMBRIEF, PROCEDURES) == "LANDU"  # LAND2A's first fix
    assert entry_fix(FlightPlan("DLH4AB", "EDDH", "EDDM", route="LULAR T105 LANDU LAND2A"), None) == "LANDU"
    assert entry_fix(FlightPlan("DLH4AB", "EDDH", "EDDM"), PROCEDURES) is None


def test_other_approach_kinds_are_said(eddm):
    vor = Procedure("D26L", "approach", "26L", (fix("DX003", "IF"), fix("FAFYY")), approach_type="VORDME")
    p = Procedures("EDDM", PROCEDURES.stars, (vor,))
    a = plan_arrival(eddm, "26L", SIMBRIEF, p)
    assert (a.star.name, a.approach_kind, a.transition) == ("LAND2B", "VOR DME", None)
    assert plan_arrival(eddm, "26L", SIMBRIEF, Procedures("EDDM", (), ())).star is None


class Source:
    def __init__(self, procedures):
        self._p = procedures

    def procedures(self, ident):
        return self._p


def test_the_procedures_from_the_first_source_that_has_them():
    assert find_procedures([Source(None), Source(PROCEDURES), Source(None)], "EDDM") is PROCEDURES
    assert find_procedures([Source(None)], "EDDM") is None
