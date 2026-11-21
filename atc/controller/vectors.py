"""Radar vectors to the final approach (Milestone 8, part H), as an approach controller gives them.

Found in the first full test flight: Approach gave one heading towards a point 14 NM out and then waited until the
aircraft came within 3 NM of it. Missing it (wind, or after the go-around) meant no more instructions: 8 minutes on
heading 075. Now the controller flies the aircraft through a pattern and watches it on the way:

    downwind   to a point BASE_ALONG_NM out on the extended centreline, DOWNWIND_NM to the side the aircraft is on,
               with a corrected heading whenever its way to that point drifts off by CORRECT_DEG or more;
    base       near that point: a heading at right angles towards the centreline (none when the downwind is so
               close to it that the base leg would be gone in the turn: the intercept at once);
    intercept  within INTERCEPT_ACROSS_NM of the centreline (or across it): 30 degrees onto the localizer and the
               approach clearance (atc/controller/air.py _approach_clearance).

Where the aircraft joins the final comes from the published approach: its intermediate fix (EDDM ILS 08R: DM441,
16.9 NM out; EDDH ILS 23: HHW13, 13 NM), where the approach as flown with the FMS begins (the user, 2026-11-21:
"not at 10 NM but exactly on the procedure"). The base leg lies so far out that the intercept meets the final there:
base_along_nm(join_nm). Without approach data ESTABLISHED_BY_NM.

An aircraft far out in front of the runway and near enough to the final skips the downwind: a 30-degree intercept
heading at once, when it meets the centreline at the join point or farther out (Milestone 10 F). Far beside the
final it flies to the base point first (from in front a long base), never 45 degrees straight at the final: the
2026-11-17 flight was turned in from 20 NM beside and met the localizer at the threshold.

The frame: "along" is how far out the aircraft is on the extended centreline (positive in front of the threshold,
on the approach side), "across" how far beside it, positive on the left when facing the runway.
"""
import math

from atc.airport.geo import bearing_deg, destination_point, distance_nm

INTERCEPT_DEG = 30
INTERCEPT_ACROSS_NM = 2.5  # this close beside the centreline on base: intercept and cleared
INTERCEPT_RUN_NM = INTERCEPT_ACROSS_NM / math.tan(math.radians(INTERCEPT_DEG))  # the 30-degree intercept meets the
# centreline this much farther in than where it starts
JOIN_MARGIN_NM = 0.5  # the base leg this much farther out still: the turns round the corners
ESTABLISHED_BY_NM = 10  # without approach data: the final joined at least this far out


def base_along_nm(join_nm: float = ESTABLISHED_BY_NM) -> float:
    """How far out the base leg lies for the intercept from it to meet the final join_nm out."""
    return join_nm + INTERCEPT_RUN_NM + JOIN_MARGIN_NM


BASE_ALONG_NM = base_along_nm()  # without approach data: 14.8 nm
DOWNWIND_NM = 5  # the downwind's distance beside the centreline
BASE_WITHIN_NM = 2  # this close to the base point: turn base
BASE_TURN_LEAD_NM = 1  # out on the downwind the base turn this much before BASE_ALONG_NM: the turn takes it there
BASE_LEG_MIN_NM = 2  # less than this left to INTERCEPT_ACROSS_NM when the base turn is due: no base leg, the
# intercept heading and the approach clearance at once (emulator, 2026-11-19: a downwind 3.8-4.1 nm beside the
# centreline, the turn took most of it, the intercept came 16-24 s after the base turn in the same direction)
STRAIGHT_IN_MORE_NM = 6  # this much farther out in front than the join point: no downwind, straight to the final
DESCENT_NM_PER_1000_FT = 3  # the 3:1 rule: 3 nm flown for each 1000 ft down
ENERGY_MARGIN_NM = 4  # and these miles more to slow down to the final speed
CORRECT_DEG = 20  # the way to the base point this far off the assigned heading: a corrected heading
CORRECT_EVERY_S = 30  # not more often than this
CORRECT_NEAR_NM = 5  # this close to the base point no correction: the bearing swings there, and the base turn
# comes within about a minute anyway (emulator, 2026-11-19: a correction 2-3.5 nm out, the base turn 2-28 s later)


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


def base_point(end, across_now: float, base_nm: float = BASE_ALONG_NM) -> tuple[float, float]:
    return point(end, base_nm, side_of(across_now) * DOWNWIND_NM)


def base_heading_true(end, across_now: float) -> float:
    """At right angles towards the centreline: from the left side (facing the runway) that is a turn to the right
    of the final course."""
    return (end.heading_true + 90 * side_of(across_now)) % 360


def base_too_short(across_now: float) -> bool:
    return abs(across_now) < INTERCEPT_ACROSS_NM + BASE_LEG_MIN_NM


def straight_in(along: float, across: float, join_nm: float = ESTABLISHED_BY_NM) -> bool:
    """Far enough out in front, and near enough to the final, that a 30-degree intercept heading meets the
    centreline at the join point or farther out."""
    met = along - abs(across) / math.tan(math.radians(INTERCEPT_DEG))
    return along >= join_nm + STRAIGHT_IN_MORE_NM and met >= join_nm


def path_nm(end, lat: float, lon: float, join_nm: float = ESTABLISHED_BY_NM) -> float:
    """The miles these vectors fly from here to the threshold: straight in on a 30-degree intercept, else to the
    base point, along the base and the final."""
    along, across = frame(end, lat, lon)
    if straight_in(along, across, join_nm):
        rad = math.radians(INTERCEPT_DEG)
        return abs(across) / math.sin(rad) + along - abs(across) / math.tan(rad)
    base = base_along_nm(join_nm)
    return distance_nm(lat, lon, *base_point(end, across, base)) + DOWNWIND_NM + base


def energy_along_nm(height_ft: float, across: float) -> float:
    """How far out the base turn must come at the least for the height still to lose (above the field): the base
    leg and the final are |across| + along miles, the 3:1 rule wants height/1000*3 and the slowing down."""
    return max(0.0, height_ft) / 1000 * DESCENT_NM_PER_1000_FT + ENERGY_MARGIN_NM - abs(across)


def turn_direction(from_heading: float, to_heading: float) -> str:
    return "right" if (to_heading - from_heading + 540) % 360 - 180 > 0 else "left"
