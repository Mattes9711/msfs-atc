"""SimBrief flight plans by username.

DATA SOURCE: SimBrief's public XML fetcher with the user's own username; the plan is the user's data. It is cached
in the user's data folder only. Check SimBrief's terms before a public release (BUILD.md).
"""
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from atc.flightplan.model import FlightPlan, Waypoint

URL = "https://www.simbrief.com/api/xml.fetcher.php?username={}"
FLIGHT_RULES = {"I": "IFR", "V": "VFR"}  # Y (IFR then VFR) and Z (VFR then IFR) are kept as their letter


class SimbriefError(Exception):
    pass


def _http_get(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def load_simbrief(username: str, cache_dir: Path,
                  fetch: Callable[[str, float], bytes] = _http_get) -> tuple[FlightPlan, bool]:
    """Latest SimBrief plan for this user; returns (plan, came_from_cache).
    The raw OFP holds the user's ID and crew names, so the cache stays in the git-ignored cache/ folder."""
    cache = cache_dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', username)}.xml"
    try:
        data = fetch(URL.format(urllib.parse.quote(username)), 15)
    except urllib.error.HTTPError as e:
        # SimBrief answers 400 with a readable reason, e.g. "No flight plan on file for the specified user"
        raise SimbriefError(_status(e.read()) or f"SimBrief HTTP {e.code}") from None
    except OSError:
        if cache.exists():
            return parse_simbrief(cache.read_bytes()), True
        raise SimbriefError("SimBrief is unreachable and there is no cached flight plan") from None
    plan = parse_simbrief(data)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return plan, False


def parse_simbrief(data: bytes) -> FlightPlan:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise SimbriefError("SimBrief answer is not valid XML") from None

    def text(path: str) -> str | None:
        value = root.findtext(path)
        return value.strip() if value and value.strip() else None

    callsign = text("atc/callsign")
    departure = text("origin/icao_code")
    if not callsign or not departure:
        raise SimbriefError("SimBrief flight plan has no callsign or departure airport")
    cruise = text("general/initial_altitude")
    rules = text("atc/flight_rules") or "I"
    sid, star = text("general/sid_ident"), text("general/star_ident")
    return FlightPlan(
        callsign=callsign.upper(),
        departure=departure,
        destination=text("destination/icao_code"),
        cruise_ft=int(cruise) if cruise and cruise.isdigit() else None,
        route=text("general/route") or "",
        aircraft=text("aircraft/icaocode"),
        rules=FLIGHT_RULES.get(rules, rules),
        waypoints=navlog_waypoints(root, sid, star),
        sid=sid,
        star=star,
        tod=top_of_descent(root),
    )


def top_of_descent(root: ET.Element) -> tuple[float, float] | None:
    """SimBrief's computed top of descent: the navlog's "TOD" point (type ltlg)."""
    for fix in root.findall("navlog/fix"):
        if (fix.findtext("ident") or "").upper() == "TOD":
            try:
                return float(fix.findtext("pos_lat")), float(fix.findtext("pos_long"))
            except (TypeError, ValueError):
                return None
    return None


def navlog_waypoints(root: ET.Element, sid: str | None, star: str | None) -> tuple[Waypoint, ...]:
    """The plan's waypoints with their positions. Left out: TOC/TOD (computed points, type "ltlg") and the
    airports. A point flown "via" the SID or STAR belongs to it.
    DATA SOURCE: the user's own SimBrief plan (fetched with their username, never shipped)."""
    points = []
    for fix in root.findall("navlog/fix"):
        ident, kind, via = fix.findtext("ident"), fix.findtext("type"), fix.findtext("via_airway")
        try:
            lat, lon = float(fix.findtext("pos_lat")), float(fix.findtext("pos_long"))
        except (TypeError, ValueError):
            continue
        if not ident or kind in ("ltlg", "apt"):
            continue
        leg = "sid" if sid and via == sid else "star" if star and via == star else "route"
        points.append(Waypoint(ident.upper(), lat, lon, leg))
    return tuple(points)


def _status(body: bytes) -> str | None:
    try:
        return ET.fromstring(body).findtext("fetch/status")
    except ET.ParseError:
        return None
