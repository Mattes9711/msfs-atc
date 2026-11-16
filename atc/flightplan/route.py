import re

from atc.phraseology.spoken import ALPHABET, DIGITS

# SID identifiers are the (often truncated) fix name + digit + letter, e.g. AMLU2G = AMLUH two golf
SID = re.compile(r"([A-Z]{2,5})(\d)([A-Z])")
FIX = re.compile(r"[A-Z]{2,5}")  # waypoint names have no digits; airways (M852, UL610) and procedures do


def first_fix(route: str) -> str | None:
    """First waypoint of the route, the end of the SID if there is one: 'AMLU2G AMLUH M852' -> 'AMLUH'."""
    tokens = route.upper().split()
    if tokens and SID.fullmatch(tokens[0]):
        tokens = tokens[1:]
    return next((t for t in tokens if t != "DCT" and FIX.fullmatch(t)), None)


def spoken_star(route: str, star: str | None = None) -> str | None:
    """'... LANDU LAND2A' -> 'Landu two Alfa arrival': the STAR is the last route token that looks like a procedure
    (or `star` from SimBrief). Its fix is the waypoint before it, when that starts the same way."""
    tokens = route.upper().split()
    name = star.upper() if star else (tokens[-1] if tokens and SID.fullmatch(tokens[-1]) else None)
    if not name or not (m := SID.fullmatch(name)):
        return None
    i = tokens.index(name) if name in tokens else len(tokens)
    fix = tokens[i - 1] if i > 0 and tokens[i - 1].startswith(m[1]) else m[1]
    return f"{fix.title()} {DIGITS[m[2]]} {ALPHABET[m[3]]} arrival"


def spoken_sid(route: str) -> str | None:
    """'AMLU2G AMLUH M852 ...' -> 'Amluh two Golf departure'; None if the route doesn't start with a SID."""
    tokens = route.upper().split()
    if not tokens or not (m := SID.fullmatch(tokens[0])):
        return None
    fix = tokens[1] if len(tokens) > 1 and tokens[1].startswith(m[1]) else m[1]
    return f"{fix.title()} {DIGITS[m[2]]} {ALPHABET[m[3]]} departure"
