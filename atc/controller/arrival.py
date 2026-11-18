"""The arrival planned with the descent (Milestone 10 B): the landing runway, the STAR that fits it, the approach and
the transition from the STAR's last fix to it.

Munich, landing 26R, filed "... LANDU LAND2A" (the STAR for 08): Center says "descend flight level one hundred,
cleared Landu two Bravo arrival, expect ILS approach runway two six right", and the ILS 26R's transition LANDU is
kept for Approach (part E). Without Little Navmap's procedures: the filed STAR and an ILS or RNAV approach, as
before."""
from dataclasses import dataclass

from atc.airport.model import Airport
from atc.airport.procedures import Procedure, Procedures, Transition
from atc.flightplan.model import FlightPlan
from atc.flightplan.route import FIX, SID, spoken_star

APPROACH_WORDS = {"VORDME": "VOR DME", "NDBDME": "NDB DME"}


@dataclass(frozen=True)
class Arrival:
    runway: str
    star: Procedure | None = None  # from Little Navmap; None: the filed STAR (if any) is said as filed
    approach: Procedure | None = None
    transition: Transition | None = None
    approach_kind: str = "ILS"  # "ILS", "RNAV", "VOR DME", …: what is said

    @property
    def star_name(self) -> str | None:
        return self.star.name if self.star else None


def filed_star(plan: FlightPlan) -> str | None:
    """The STAR in the flight plan: SimBrief's, else the last route token that looks like one."""
    if plan.star:
        return plan.star.upper()
    tokens = plan.route.upper().split()
    return tokens[-1] if tokens and SID.fullmatch(tokens[-1]) else None


def entry_fix(plan: FlightPlan, procedures: Procedures | None) -> str | None:
    """Where the arrival starts: the filed STAR's first fix (LANDU for LAND2A), else the route's last fix."""
    name = filed_star(plan)
    star = procedures.star(name) if procedures and name else None
    if star and star.first_fix:
        return star.first_fix
    tokens = [t for t in plan.route.upper().split() if t != "DCT"]
    if name and name in tokens:
        tokens = tokens[:tokens.index(name)]
    return next((t for t in reversed(tokens) if FIX.fullmatch(t)), None)


def plan_arrival(destination: Airport, runway: str, plan: FlightPlan, procedures: Procedures | None) -> Arrival:
    """The STAR for the runway from the plan's entry fix, the approach to fly (an ILS first) and the transition
    from the STAR's last fix. What isn't in the data stays None."""
    end = destination.runway_end(runway)
    kind = "ILS" if end is not None and end.ils else "RNAV"
    if procedures is None:
        return Arrival(runway, approach_kind=kind)
    fix = entry_fix(plan, procedures)
    star = procedures.star_from(fix, runway) if fix else None
    approach = procedures.approach(runway)
    transition = None
    if approach and star:
        # From the last of the STAR's fixes that has one, and one that ends in vectors first (Milestone 10 E): Munich
        # LAND2B ends at MIQ, whose transition has none, so LANDU's is flown from the STAR's first fix, with the
        # vectors from DM429 on the downwind
        fixes = [leg.ident for leg in reversed(star.legs) if leg.ident]
        found = [t for f in fixes if (t := approach.transition(f))]
        transition = next((t for t in found if t.vectors_from), found[0] if found else None)
    if approach:
        kind = APPROACH_WORDS.get(approach.approach_type, approach.approach_type)
    return Arrival(runway, star, approach, transition, kind)


def spoken_arrival(arrival: Arrival, plan: FlightPlan) -> str | None:
    """'Landu two Bravo arrival': the STAR from the data, else the filed one."""
    if arrival.star:
        return spoken_star(arrival.star.first_fix or "", arrival.star.name)
    return spoken_star(plan.route, plan.star) if plan.route or plan.star else None
