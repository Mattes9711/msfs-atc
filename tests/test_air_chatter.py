"""Milestone 8, G: the other aircraft talk to Departure, Approach and Center, from what they really do."""
from dataclasses import replace

from atc.airport.geo import destination_point
from atc.controller.air_chatter import AIR_CHATTER_GAP_S, level_words
from atc.phraseology import spoken
from tests.test_air_flow import HAMBURG_APPROACH, MUNICH_APPROACH
from tests.test_centers import MIDDLE, NORTH, SECTORS
from tests.test_ground_flow import Session
from tests.test_traffic_picture import plane

THEM = "Lufthansa one two tree"


def tuned(eddh, eddm, khz):
    s = Session(eddh, destination=eddm, centers=SECTORS)
    s.sim.update(com1_khz=khz)
    s.tick()
    return s


def flying(lat, lon, alt, oid=7, hdg=180.0):
    return plane(lat, lon, alt, 450, hdg, False, oid)


def heard(s, traffic, now, last_radio=None):
    return [(r.station, r.text) for r in s.atc.update_traffic(traffic, now=now, last_radio=last_radio)
            if r.kind == "chatter"]


def test_entering_the_sector_checks_in_with_its_level(eddh, eddm):
    s = tuned(eddh, eddm, NORTH)
    assert heard(s, [flying(55.2, 10.0, 30000)], 0) == []  # still north of the sector
    assert heard(s, [flying(54.9, 10.0, 30000)], 3) == [
        ("Lufthansa 123", f"North Radar, {THEM}, flight level tree hundred"),
        ("North Radar", f"{THEM}, North Radar, radar contact")]
    assert heard(s, [flying(54.8, 10.0, 30000)], 30) == []  # once


def test_climbing_it_is_cleared_on_and_again_near_that_level(eddh, eddm):
    s = tuned(eddh, eddm, NORTH)
    assert heard(s, [flying(54.5, 10.0, 20000)], 0) == []  # first seen in the sector: already with it
    assert heard(s, [flying(54.5, 10.0, 20150)], 3) == [  # 3000 ft/min
        ("North Radar", f"{THEM}, climb flight level two fife zero"),
        ("Lufthansa 123", f"climb flight level two fife zero, {THEM}")]
    assert heard(s, [flying(54.4, 10.0, 22000)], 40) == []  # on its way
    assert heard(s, [flying(54.3, 10.0, 24200)], 80) == [
        ("North Radar", f"{THEM}, climb flight level two niner zero"),
        ("Lufthansa 123", f"climb flight level two niner zero, {THEM}")]


def test_leaving_the_sector_is_handed_over_to_the_next(eddh, eddm):
    s = tuned(eddh, eddm, NORTH)
    heard(s, [flying(52.6, 10.0, 30000)], 0)
    freq = spoken.frequency(MIDDLE)
    assert heard(s, [flying(52.4, 10.0, 30000)], 3) == [
        ("North Radar", f"{THEM}, contact Middle Radar {freq}"), ("Lufthansa 123", f"{freq}, {THEM}")]


def test_the_terminal_area_is_not_the_centers(eddh, eddm):
    s = tuned(eddh, eddm, NORTH)
    near = destination_point(eddh.lat, eddh.lon, 0, 10)
    heard(s, [flying(*near, 8000)], 0)
    assert heard(s, [flying(*near, 8200)], 3) == []  # climbing out of Hamburg: Hamburg's, not North Radar's


def test_departure_clears_its_climb_and_hands_over_to_the_center(eddh, eddm):
    s = tuned(eddh, eddm, HAMBURG_APPROACH)
    near = destination_point(eddh.lat, eddh.lon, 0, 20)
    heard(s, [flying(*near, 6000, hdg=0)], 0)
    assert heard(s, [flying(*near, 6150, hdg=0)], 3)[0] == (
        "Hamburg Approach", f"{THEM}, climb flight level one one zero")
    out = destination_point(eddh.lat, eddh.lon, 0, 32)
    assert heard(s, [flying(*out, 9000, hdg=0)], 30) == [
        ("Hamburg Approach", f"{THEM}, contact North Radar {spoken.frequency(NORTH)}"),
        ("Lufthansa 123", f"{spoken.frequency(NORTH)}, {THEM}")]


def test_an_arrival_checks_in_with_approach_and_hears_the_runway(eddh, eddm):
    s = tuned(eddh, eddm, MUNICH_APPROACH)
    runway = spoken.runway(s.atc.arrival_runway)
    heard(s, [flying(*destination_point(eddm.lat, eddm.lon, 0, 32), 12000)], 0)
    [(_, call), (station, answer), (_, readback)] = heard(
        s, [flying(*destination_point(eddm.lat, eddm.lon, 0, 29), 11900)], 3)
    assert call == f"Munich Approach, {THEM}, passing flight level one one niner, descending"
    assert station == "Munich Approach"
    assert answer.startswith(f"{THEM}, Munich Approach, radar contact, expect vectors ILS approach runway {runway}, "
                             f"descend flight level seven zero")
    assert readback.startswith("descend flight level seven zero") and readback.endswith(THEM)


def test_one_exchange_at_a_time_with_a_gap(eddh, eddm):
    s = tuned(eddh, eddm, NORTH)
    a, b = flying(55.2, 10.0, 30000), flying(55.2, 11.0, 34000, oid=8)
    heard(s, [a, b], 0)
    a, b = replace(a, lat=54.9), replace(b, lat=54.9)
    assert len(heard(s, [a, b], 3)) == 2
    assert heard(s, [a, b], 3 + AIR_CHATTER_GAP_S - 1) == []
    assert heard(s, [a, b], 3 + AIR_CHATTER_GAP_S)[0][1] == f"North Radar, {THEM}, flight level tree four zero"


def test_never_while_the_pilot_owes_a_readback_or_on_a_busy_radio(eddh, eddm):
    s = tuned(eddh, eddm, NORTH)
    heard(s, [flying(55.2, 10.0, 30000)], 0)
    s.atc.pending = ["a readback"]
    assert heard(s, [flying(54.9, 10.0, 30000)], 3) == []
    s.atc.pending = []
    assert heard(s, [flying(54.9, 10.0, 30000)], 6, last_radio=4) == []  # ATC just spoke
    assert len(heard(s, [flying(54.9, 10.0, 30000)], 12, last_radio=4)) == 2  # the check-in, a little later


def test_without_chatter_nothing(eddh, eddm):
    s = tuned(eddh, eddm, NORTH)
    s.atc.chatter = False
    heard(s, [flying(55.2, 10.0, 30000)], 0)
    assert heard(s, [flying(54.9, 10.0, 30000)], 3) == []


def test_level_words():
    assert level_words(24030, 0) == "flight level two four zero"
    assert level_words(12340, 2000) == "passing flight level one two tree, climbing"
    assert level_words(3960, -900) == "passing four thousand feet, descending"
