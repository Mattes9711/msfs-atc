"""Before the flight (Milestone 7, start screen): the briefing of the loaded flight plan.

brief(): the plan (from SimBrief or typed in) with both airports, their weather and the runway in use, without
starting anything, so the pilot sees what ATC will work with before pressing Start.
"""

from atc import paths
from atc.airport.model import AirportData
from atc.config import Config
from atc.flightplan.route import spoken_sid, spoken_star
from atc.flightplan.simbrief import SimbriefError, load_simbrief
from atc.phraseology import spoken
from atc.session import (PlanRequest, SessionOptions, SetupError, SimbriefLoader, airport_sources, build_plan,
                         airport_metar, describe_runway, find_airport)
from atc.weather.runway_choice import choose_runway
from atc.weather.source import LiveWeather, WeatherSource


def brief(request: PlanRequest, options: SessionOptions, config: Config, *, weather: WeatherSource | None = None,
          airports: list[AirportData] | None = None, simbrief: SimbriefLoader | None = None, **_) -> dict:
    """The flight as the start screen shows it. Raises SetupError like starting the flight would."""
    try:
        plan, source = build_plan(request, options, config,
                                  simbrief or (lambda user: load_simbrief(user, paths.cache_dir("simbrief"))))
    except SimbriefError as e:
        raise SetupError(str(e)) from None
    sources = airports if airports is not None else airport_sources(config)
    weather = weather or LiveWeather(paths.cache_dir("metar"))
    notes = []
    if not options.nosim:
        notes.append("With MSFS the airport your aircraft stands at is the departure airport.")
    if options.weather == "sim":
        notes.append("The departure weather will come from MSFS at the start; shown here is the real METAR.")
    return {
        "callsign": plan.callsign, "spoken_callsign": _spoken_callsign(plan.callsign),
        "aircraft": plan.aircraft, "rules": plan.rules, "cruise_ft": plan.cruise_ft, "route": plan.route, "source": source,
        "sid": plan.sid or _procedure(plan.route, 0, spoken_sid),
        "star": plan.star or _procedure(plan.route, -1, spoken_star),
        "departure": _airport(sources, weather, plan.departure) if plan.departure else None,
        "destination": _airport(sources, weather, plan.destination) if plan.destination else None,
        "notes": notes,
    }


def _spoken_callsign(callsign: str) -> str:
    try:
        return spoken.callsign(callsign)
    except ValueError:
        return callsign


def _procedure(route: str, at: int, spoken_name) -> str | None:
    """The SID (first route token) or STAR (last) when the route has one: "AMLU2G"."""
    tokens = route.upper().split()
    return tokens[at] if tokens and spoken_name(route) else None


def _airport(sources: list[AirportData], weather: WeatherSource, ident: str) -> dict:
    found = find_airport(sources, ident)
    if found is None:
        return {"ident": ident, "name": None, "metar": None, "runway": None,
                "note": "no airport data: ATC has no ground or arrival phases there"}
    airport, _ = found
    metar = airport_metar(weather, airport)
    end = choose_runway(airport, metar) if airport.runways else None
    return {"ident": airport.ident, "name": airport.name, "metar": metar.raw if metar else None,
            "runway": end.name if end else None, "wind": describe_runway(end, metar) if end else None,
            "note": None if metar else "no METAR: ATC assumes calm wind"}
