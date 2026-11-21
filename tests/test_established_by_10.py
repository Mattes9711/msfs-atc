"""Established on the localizer by about 10 nm (emulator, 2026-11-21: the base leg 12 nm out and the intercept 2.5 nm
beside the centreline met the localizer only 7.9 nm out, 3536 ft above the field at 10 nm, off the localizer)."""
import math

from atc.controller import vectors
from tests.test_air_flow import MUNICH_APPROACH
from tests.test_vectors import arriving, at


def test_the_intercept_from_the_base_leg_meets_the_localizer_10_nm_out():
    met = vectors.BASE_ALONG_NM - vectors.INTERCEPT_ACROSS_NM / math.tan(math.radians(30))
    assert met >= 9.5


def test_a_straight_in_meets_the_localizer_10_nm_out():
    assert vectors.straight_in(20, 5) and not vectors.straight_in(16, 4)


def test_outbound_in_the_cone_in_front_is_not_on_final(eddh, eddm):
    """A downwind 4 nm beside the centreline is in the final cone 15 nm out: flying away, no approach clearance."""
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 15, 4, (end.heading_true + 180) % 360)
    assert not s.atc._on_final(s.sim.read())
    at(s, eddm, 15, 4, end.heading_true)
    assert s.atc._on_final(s.sim.read())


def test_checking_in_outbound_in_the_cone_brings_vectors(eddh, eddm):
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 15, 4, (end.heading_true + 180) % 360)
    [call] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    assert ", vectors ILS approach runway " in call and "cleared ILS" not in call
