"""Wake turbulence (Milestone 6, L5): ICAO wake categories and the time between two departures.

ICAO Doc 4444 sorts aircraft by maximum takeoff mass: J (super, the A380), H (heavy, 136 t or more), M (medium) and
L (light, 7 t or less). Behind a heavier aircraft on the same runway the next departure waits:
    behind J:  H 2 minutes, M and L 3 minutes
    behind H:  M and L 2 minutes
    behind M:  L 2 minutes
One minute more when the one behind takes off from an intersection (an intermediate part of the runway).

The category comes from the type designator ("A388", "B77W", "C172"). LiveTraffic gives the designator; MSFS's own
AI sometimes gives a text key or a name ("Skyhawk"), so a few names count too. Unknown types are medium, the most
common category at airliner airports.
"""
import math
import re
from dataclasses import dataclass

SUPER = re.compile(r"A38\d")
HEAVY = re.compile(r"A30\w|A310|A3[345]\w|A3ST|B?7[4678]\w*|BLCF|MD11|DC10|L101|IL[79]6|A124|A225|A400M?|C17|C5M?"
                   r"|K35R|KC10|B52")
LIGHT = re.compile(r"C1[5-9]\d\w*|C2[01]\d\w*|P28\w|PA\d\d\w*|SR2\d|S22T|DA[2-6]\d|DV20|BE(?:20|3\d|5\d|9L)|M20\w"
                   r"|TBM\d|PC(?:6|12|21)\w*|DR40|E300|EXTR|J3|CUB|ICON|XCUB|SAVG|Z42|VL3|SHRK|PITS|CAP\d+")
LIGHT_WORDS = ("SKYHAWK", "SKYLANE", "CARAVAN", "CUB", "BONANZA", "BARON", "CIRRUS", "DIAMOND", "PIPER",
               "EXTRA", "KING AIR", "TBM", "PILATUS", "MOONEY", "ROBIN", "ICON", "SAVAGE", "ZLIN", "SHARK", "PITTS")

DEPARTURE_S = {("J", "H"): 120, ("J", "M"): 180, ("J", "L"): 180, ("H", "M"): 120, ("H", "L"): 120,
               ("M", "L"): 120}
INTERSECTION_EXTRA_S = 60
NAMES = {"J": "super", "H": "heavy", "M": "medium", "L": "light"}
MINUTES = ["zero", "one", "two", "three", "four", "five"]


@dataclass(frozen=True)
class Departure:
    """A takeoff seen in the traffic: who, from which runway end, when (the live clock; None without one)."""
    object_id: int
    end: str
    at: float | None
    category: str
    name: str  # "the Emirates Boeing"


def designator(model: str) -> str:
    """"A388" from "A388", "a380-800" or an MSFS text key like "TT:ATCCOM.AC_MODEL_A388.0.text"."""
    m = model.upper()
    if key := re.search(r"AC_MODEL[_ ]?([A-Z0-9]+)", m):
        m = key[1]
    return m.replace("-", "").replace(" ", "")


def category(model: str, title: str = "") -> str:
    """"J", "H", "M" or "L" for a type designator (or a name, or the sim's title when the type says nothing)."""
    code = designator(model)
    if SUPER.fullmatch(code) or code.startswith("A380"):
        return "J"
    if HEAVY.fullmatch(code) or re.fullmatch(r"A3[345]0\w*|7[4678]7\w*", code):
        return "H"
    words = f"{model} {title}".upper()
    if LIGHT.fullmatch(code) or any(w in words for w in LIGHT_WORDS):
        return "L"
    return "M"


def departure_spacing_s(ahead: str, ours: str, intersection: bool = False) -> int:
    """Seconds our takeoff waits after the one ahead took off from the same runway; 0 when no wake spacing."""
    base = DEPARTURE_S.get((ahead, ours), 0)
    return base + INTERSECTION_EXTRA_S if base and intersection else base


def minutes(seconds: float) -> str:
    """"two minutes" for 61..120 seconds (rounded up, as a controller does)."""
    n = max(1, min(len(MINUTES) - 1, math.ceil(seconds / 60)))
    return f"{MINUTES[n]} minute" + ("s" if n > 1 else "")


# On approach (radar, ICAO Doc 4444 8.7.4): the distance behind the aircraft ahead on the same final. Without wake
# spacing the radar minimum.
APPROACH_NM = {("J", "H"): 6, ("J", "M"): 7, ("J", "L"): 8, ("H", "H"): 4, ("H", "M"): 5, ("H", "L"): 6,
               ("M", "L"): 5}
RADAR_MIN_NM = 3


def approach_spacing_nm(ahead: str, ours: str) -> int:
    """Nautical miles we keep behind the aircraft ahead on final."""
    return APPROACH_NM.get((ahead, ours), RADAR_MIN_NM)
