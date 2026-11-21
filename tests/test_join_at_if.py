"""The vectors join the final at the published approach's first fix, not at a made-up 10 nm (the user, 2026-11-21:
"auf dem genauen SID/STAR, so wie man einen echten Anflug fliegt"). EDDM ILS 08R: IF DM441 16.9 nm out; EDDH ILS 23:
HHW13 13 nm out. The fixture's approach starts at DX002, 12 nm out on the centreline."""
from dataclasses import replace

from atc.airport.procedures import Procedures
from atc.controller import vectors
from tests.test_transition import procedures, with_approach


def test_the_join_is_the_approach_s_first_fix(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm))
    assert abs(s.atc._join_nm() - 12) < 0.1


def test_without_procedures_the_join_is_10_nm(eddh, eddm):
    s = with_approach(eddh, eddm, procedures(eddm))
    s.atc.procedures = None
    assert s.atc._join_nm() == vectors.ESTABLISHED_BY_NM


def test_a_first_fix_beside_the_centreline_is_no_join(eddh, eddm):
    """An IF off the final (a T-bar approach's corner, say) is not where the localizer is met."""
    p = procedures(eddm)
    ils = p.approaches[0]
    end = eddm.runway_end("08R")
    off = replace(ils.legs[0], lat=vectors.point(end, 12, 3)[0], lon=vectors.point(end, 12, 3)[1])
    p = Procedures(p.airport, p.stars, (replace(ils, legs=(off, *ils.legs[1:])),))
    s = with_approach(eddh, eddm, p)
    assert s.atc._join_nm() == vectors.ESTABLISHED_BY_NM


def test_the_intercept_meets_the_final_before_the_join():
    for join in (10, 12, 13, 16.9):
        base = vectors.base_along_nm(join)
        assert join < base - vectors.INTERCEPT_RUN_NM < join + 1


def test_a_straight_in_is_judged_against_the_join():
    assert vectors.straight_in(20, 5, 10) and not vectors.straight_in(20, 5, 12)
    assert vectors.straight_in(26, 5, 16.9) and not vectors.straight_in(26, 8, 16.9)
