"""Radar vectors to the final approach (Milestone 8, part H), as an approach controller gives them.

Found in the first full test flight: Approach gave one heading towards a point 14 NM out and then waited until the
aircraft came within 3 NM of it. Missing it (wind, or after the go-around) meant no more instructions: 8 minutes on
heading 075. Now the controller flies the aircraft through a pattern and watches it on the way:

    downwind   to a point BASE_ALONG_NM out on the extended centreline, DOWNWIND_NM to the side the aircraft is on,
               with a corrected heading whenever its way to that point drifts off by CORRECT_DEG or more;
    base       near that point: a heading at right angles towards the centreline;
    intercept  within INTERCEPT_ACROSS_NM of the centreline (or across it): 30 degrees onto the localizer and the
               approach clearance (atc/controller/air.py _approach_clearance).

An aircraft far out in front of the runway and near enough to the final skips the downwind: a 30-degree intercept
heading at once, when it meets the centreline at least ESTABLISHED_BY_NM out (Milestone 10 F). Far beside the
final it flies to the base point first (from in front a long base), never 45 degrees straight at the final: the
2026-11-17 flight was turned in from 20 NM beside and met the localizer at the threshold.

The frame: "along" is how far out the aircraft is on the extended centreline (positive in front of the threshold,
on the approach side), "across" how far beside it, positive on the left when facing the runway.
"""
import math

from atc.airport.geo import bearing_deg, destination_point, distance_nm

BASE_ALONG_NM = 12  # where the base leg is: far enough out to be established by about 10 NM
DOWNWIND_NM = 5  # the downwind's distance beside the centreline
BASE_WITHIN_NM = 2  # this close to the base point: turn base
BASE_TURN_LEAD_NM = 1  # out on the downwind the base turn this much before BASE_ALONG_NM: the turn takes it there
INTERCEPT_ACROSS_NM = 2.5  # this close beside the centreline on base: intercept and cleared
STRAIGHT_IN_ALONG_NM = 14  # farther out in front than this: no downwind, straight towards the final
ESTABLISHED_BY_NM = 8  # a straight-in intercept must meet the centreline at least this far out
CORRECT_DEG = 20  # the way to the base point this far off the assigned heading: a corrected heading
CORRECT_EVERY_S = 30  # not more often than this


def frame(end, lat: float, lon: float) -> tuple[float, float]:
    """(along, across) in nm for a runway end with .lat, .lon, .heading_true."""
    dist = distance_nm(end.lat, end.lon, lat, lon)
    outbound = (end.heading_true + 180) % 360
    rel = math.radians(bearing_deg(end.lat, end.lon, lat, lon) - outbound)
    return dist * math.cos(rel), dist * math.sin(rel)


def point(end, along: float, across: float) -> tuple[float, float]:
    """(lat, lon) of a point in the frame."""
    outbound = (end.heading_true + 180) % 360
    lat, lon = destination_point(end.lat, end.lon, outbound, along)
    return destination_point(lat, lon, (outbound + 90) % 360, across) if across >= 0 else \
        destination_point(lat, lon, (outbound - 90) % 360, -across)


def side_of(across: float) -> int:
    """+1 left of the final (facing the runway), -1 right; on the centreline the left."""
    return 1 if across >= 0 else -1


def base_point(end, across_now: float) -> tuple[float, float]:
    return point(end, BASE_ALONG_NM, side_of(across_now) * DOWNWIND_NM)


def base_heading_true(end, across_now: float) -> float:
    """At right angles towards the centreline: from the left side (facing the runway) that is a turn to the right
    of the final course."""
    return (end.heading_true + 90 * side_of(across_now)) % 360


def straight_in(along: float, across: float) -> bool:
    """Far enough out in front, and near enough to the final, that a 30-degree intercept heading meets the
    centreline ESTABLISHED_BY_NM out or farther."""
    met = along - abs(across) / math.tan(math.radians(30))
    return along >= STRAIGHT_IN_ALONG_NM and met >= ESTABLISHED_BY_NM


def path_nm(end, lat: float, lon: float) -> float:
    """The miles these vectors fly from here to the threshold: straight in on a 30-degree intercept, else to the
    base point, along the base and the final."""
    along, across = frame(end, lat, lon)
    if straight_in(along, across):
        return abs(across) / math.sin(math.radians(30)) + along - abs(across) / math.tan(math.radians(30))
    return distance_nm(lat, lon, *base_point(end, across)) + DOWNWIND_NM + BASE_ALONG_NM


def turn_direction(from_heading: float, to_heading: float) -> str:
    return "right" if (to_heading - from_heading + 540) % 360 - 180 > 0 else "left"
