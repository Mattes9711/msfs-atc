"""Radar vectors to the ILS (Milestone 8, part H): downwind, base, intercept, with corrections on the way.

The test flight got one heading towards a point 14 NM out and nothing more when it missed that point: 8 minutes on
heading 075 after the go-around."""
from atc.controller import vectors
from tests.test_air_flow import MUNICH_APPROACH
from tests.test_ground_flow import confirmed

CS = "Lufthansa four Alfa Bravo"


def arriving(eddh, eddm):
    from tests.test_air_flow import cleared_for_takeoff

    s = cleared_for_takeoff(eddh, eddm)
    s.sim.fly(eddh, eddm, 2, 35000)
    s.tick()
    s.say(118205, "Hamburg Approach, Lufthansa 4AB, passing 2000 climbing 5000")
    s.say(118205, "climb flight level 350, direct Amluh, Lufthansa 4AB")
    s.atc.phase, s.atc.descent_given = "arrival", True
    return s


def at(s, eddm, along, across, heading_true, alt=5000):
    """Put the aircraft into the final's frame: along nm out in front of the threshold, across nm to its left."""
    end = eddm.runway_end(s.atc.arrival_runway)
    lat, lon = vectors.point(end, along, across)
    s.sim.update(lat=lat, lon=lon, alt_msl_ft=alt, alt_agl_ft=alt - eddm.elevation_ft, on_ground=False,
                 ground_speed_kt=220, heading_mag=(heading_true - eddm.mag_var) % 360)


def magnetic(eddm, true):
    return round((true - eddm.mag_var) / 5) * 5 % 360 or 360


def check_in(s, eddm):
    [vectors_call] = s.say(MUNICH_APPROACH, "Munich Approach, Lufthansa 4AB, descending flight level 100")
    heading = s.atc.pending[-1].value
    assert confirmed(s.say(MUNICH_APPROACH, f"descend 4500 feet, QNH 1019, speed 220 knots, heading {heading}, "
                                            "Lufthansa 4AB"))
    return vectors_call, heading


def test_downwind_base_and_intercept(eddh, eddm):
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 0, 8, (end.heading_true + 180) % 360)  # abeam the threshold, 8 nm to the left
    call, heading = check_in(s, eddm)
    assert ", vectors ILS approach runway " in call
    assert s.atc.vector_leg == "downwind"
    # On the way to the base point: no new call while the heading still leads there
    at(s, eddm, 6, 6, (end.heading_true + 180) % 360)
    assert s.tick(now=100) == []
    # At the base point: turn base, at right angles towards the centreline (a left turn from a left downwind)
    at(s, eddm, vectors.BASE_ALONG_NM, vectors.DOWNWIND_NM, (end.heading_true + 180) % 360)
    [base] = s.tick(now=200)
    base_heading = magnetic(eddm, end.heading_true + 90)
    assert base == f"{CS}, turn left heading {spoken_heading(base_heading)}"
    assert confirmed(s.say(MUNICH_APPROACH, f"left heading {base_heading:03d}, Lufthansa 4AB"))
    # Close to the centreline: intercept heading and the ILS clearance
    at(s, eddm, vectors.BASE_ALONG_NM, 2, (end.heading_true + 90) % 360)
    [cleared] = s.tick(now=260)
    assert "cleared ILS approach runway" in cleared and "heading" in cleared and s.atc.vectoring is None


def test_a_drift_gets_a_corrected_heading_but_not_too_often(eddh, eddm):
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 0, 8, (end.heading_true + 180) % 360)
    check_in(s, eddm)
    at(s, eddm, 2, 16, (end.heading_true + 180) % 360)  # blown far off to the side
    [correction] = s.tick(now=100)
    assert correction.startswith(f"{CS}, turn ") and " heading " in correction
    s.say(MUNICH_APPROACH, f"heading {s.atc.pending[0].value:03d}, Lufthansa 4AB")
    at(s, eddm, 10, 25, (end.heading_true + 180) % 360)  # still drifting: the way to the base point turned again
    assert s.tick(now=110) == []  # 10 s later: not yet another one
    assert s.tick(now=140) != []  # after 30 s: corrected again


def test_far_out_in_front_straight_towards_the_final(eddh, eddm):
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 25, -8, end.heading_true)  # 25 nm out, 8 nm to the right, flying towards the runway
    check_in(s, eddm)
    assert s.atc.vector_leg == "base"
    at(s, eddm, 18, -2, end.heading_true)
    [cleared] = s.tick(now=100)
    assert "cleared ILS approach runway" in cleared


def test_after_overshooting_the_centreline_turned_back_onto_it(eddh, eddm):
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, 25, 8, end.heading_true)
    check_in(s, eddm)
    at(s, eddm, 17, -3, end.heading_true + 60)  # flew through the localizer to the other side
    [cleared] = s.tick(now=100)
    assert "cleared ILS approach runway" in cleared and "turn left heading" in cleared


def test_after_a_go_around_vectored_again_not_left_on_one_heading(eddh, eddm):
    """Beyond the far end of the runway (the missed approach), nearly on the centreline: a downwind, then base."""
    s = arriving(eddh, eddm)
    end = eddm.runway_end(s.atc.arrival_runway)
    at(s, eddm, -3, 0.5, end.heading_true)
    check_in(s, eddm)
    assert s.atc.vector_leg == "downwind"
    for along in range(-2, vectors.BASE_ALONG_NM):  # the pilot flies the headings: along the downwind
        at(s, eddm, along, vectors.DOWNWIND_NM, (end.heading_true + 180) % 360)
        out = s.tick(now=1000 + along * 30)
        if out:
            s.say(MUNICH_APPROACH, f"heading {s.atc.pending[0].value:03d}, Lufthansa 4AB")
    assert s.atc.vector_leg == "base"


def spoken_heading(degrees):
    from atc.phraseology import spoken

    return spoken.heading(degrees)
