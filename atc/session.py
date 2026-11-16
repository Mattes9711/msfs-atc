"""Setting up a session: flight plan, airports, sim, weather, Center sectors, controller.

Shared by the console (atc/main.py) and the app window (Milestone 3b), so both start a flight the same way.
Every problem a user can fix becomes a SetupError with a readable message.
"""
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable

from atc.airport.json_data import JsonAirportData
from atc.airport import lnm_files
from atc.airport.littlenavmap import LittleNavmapAirportData
from atc.airport.model import Airport, AirportData, RunwayEnd
from atc.airspace.centers import CenterSectors, CentersError, load_centers, with_imported
from atc.airspace.littlenavmap import load_littlenavmap_centers

VATSIM_SOURCE = "VATSIM data (Germany)"
from atc import paths
from atc.config import Config
from atc.controller.controller import Controller, frequency_list
from atc.flightplan.model import FlightPlan
from atc.flightplan.simbrief import SimbriefError, load_simbrief
from atc.sim.base import SimSource
from atc.sim.fake import FakeSim
from atc.sim.simconnect import SimConnectSource, SimUnavailable
from atc.weather.metar import Metar, parse_metar
from atc.weather.runway_choice import wind_components
from atc.weather.sim_weather import metar_from_sim
from atc.weather.source import LiveWeather, WeatherSource

DETECT_AIRPORT_NM = 5  # the aircraft is "at" the nearest airport within this distance
SIM_WIND_SAMPLES, SIM_WIND_INTERVAL_S = 6, 0.5  # averaged at startup for weather "sim"

SimbriefLoader = Callable[[str], tuple[FlightPlan, bool]]


class SetupError(Exception):
    pass


@dataclass(frozen=True)
class PlanRequest:
    """Where the flight plan comes from. simbrief: None = don't use SimBrief, "" = the configured username.
    The other fields override the SimBrief plan, or make up the whole plan without it."""
    simbrief: str | None = None
    callsign: str | None = None
    departure: str | None = None
    destination: str | None = None
    cruise_ft: int | None = None
    route: str = ""
    aircraft: str | None = None


@dataclass(frozen=True)
class SessionOptions:
    nosim: bool = False
    weather: str = "live"  # "live" (METAR) or "sim" (built from MSFS at the aircraft)
    strict_freq: bool = False


@dataclass
class Session:
    config: Config
    options: SessionOptions
    plan: FlightPlan
    plan_source: str
    airport: Airport
    source_name: str
    destination: Airport | None
    metar: Metar | None
    destination_metar: Metar | None
    centers: CenterSectors
    sim: SimSource
    controller: Controller
    weather: WeatherSource
    notices: list[str] = field(default_factory=list)
    winds: deque = field(default_factory=lambda: deque(maxlen=60))  # last minute of sim wind

    def refresh_weather(self) -> tuple[Metar | None, Metar | None]:
        return (origin_metar(self.options.weather, self.sim, self.weather, self.airport.ident, self.winds),
                load_metar(self.weather, self.destination.ident) if self.destination else None)

    def banner(self) -> list[str]:
        """What the console prints before the first transmission."""
        plan, airport, metar, c = self.plan, self.airport, self.metar, self.controller
        lines = list(self.notices)
        if isinstance(self.sim, FakeSim):
            parking = airport.default_parking()
            lines.append(f"{plan.callsign} parked at {airport.ident} {airport.name}" + (
                f", {parking.name}" if parking else "") + f" (fake sim, airport data: {self.source_name}). "
                                                          "COM1 not tuned.")
        else:
            state = self.sim.read()
            lines.append(f"{plan.callsign} at {airport.ident} {airport.name} (MSFS, airport data: {self.source_name}), "
                         + ("on the ground" if state.on_ground else f"airborne at {state.alt_msl_ft:.0f} ft") + ".")
            if not state.on_ground:
                lines.append("Note: ATC starts with the IFR clearance, so start the flight parked at the gate.")
        lines.append(f"Flight plan ({self.plan_source}): {describe_plan(plan)}")
        lines.append(f"Weather: {metar.raw if metar else 'no METAR available, assuming calm wind'}"
                     + (" (built from MSFS at the aircraft)" if self.options.weather == "sim" else ""))
        lines.append(f"Runway in use: {describe_runway(airport.runway_end(c.runway), metar)}, "
                     f"ATIS information {c.atis.letter}")
        lines.append(f"Frequencies: {frequency_list(airport)}")
        if self.destination:
            dm = self.destination_metar
            lines.append(f"Destination: {self.destination.ident} {self.destination.name}, "
                         f"{dm.raw if dm else 'no METAR'}, landing runway {c.arrival_runway}")
            lines.append(f"Destination frequencies: {frequency_list(self.destination)}")
        elif plan.destination:
            lines.append(f"Destination {plan.destination}: no airport data, so no arrival phases")
        lines.append(describe_centers(self.centers))
        return lines

    def cabin(self):
        """The cabin crew for this flight (C1), or None when switched off in Settings."""
        from atc.cabin import Cabin

        if not self.config.cabin.announcements:
            return None
        return Cabin.for_flight(self.plan.callsign, self.destination.name if self.destination else None)

    def gsx(self):
        """The link to GSX Pro (C3/C4): only with MSFS, and when reading GSX is on in Settings."""
        from atc.gsx_link import GsxLink

        if not self.config.gsx.read or not hasattr(self.sim, "gsx_values"):
            return None
        return GsxLink(self.sim, control=self.config.gsx.control)

    def close(self) -> None:
        getattr(self.sim, "close", lambda: None)()


def build_session(request: PlanRequest, options: SessionOptions, config: Config, *,
                  weather: WeatherSource | None = None, airports: list[AirportData] | None = None,
                  simbrief: SimbriefLoader | None = None, centers: CenterSectors | None = None,
                  connect_sim: Callable[[], SimSource] | None = None) -> Session:
    if options.weather == "sim" and options.nosim:
        raise SetupError("--weather sim reads the weather from MSFS, so it needs the sim (leave out --nosim)")
    try:
        plan, plan_source = build_plan(request, options, config,
                                       simbrief or (lambda user: load_simbrief(user, paths.cache_dir("simbrief"))))
        if centers is None:
            centers = center_sectors(config)
    except (SimbriefError, CentersError) as e:
        raise SetupError(str(e)) from None

    sources = airports if airports is not None else airport_sources(config)
    notices: list[str] = []
    sim: SimSource | None = None
    if not options.nosim:
        try:
            sim = connect_sim() if connect_sim else SimConnectSource(dll_path=config.simconnect_dll)
            state = sim.read()
        except SimUnavailable as e:
            raise SetupError(str(e)) from None
        plan, notice = departure_from_position(sources, plan, state)
        if notice:
            notices.append(notice)
        if not plan.departure:
            raise SetupError(f"no airport within {DETECT_AIRPORT_NM} nm of the aircraft: give --from")
    found = find_airport(sources, plan.departure)
    if found is None:
        raise SetupError(f"no airport data for {plan.departure} (searched: {', '.join(s.name for s in sources)})")
    airport, source_name = found
    sim = sim or FakeSim.parked_at(airport)
    weather = weather or LiveWeather(paths.cache_dir("metar"))
    winds: deque = deque(maxlen=60)
    if options.weather == "sim":
        winds.extend(sample_wind(sim, SIM_WIND_SAMPLES, SIM_WIND_INTERVAL_S))
    metar = origin_metar(options.weather, sim, weather, airport.ident, winds)
    found_dest = find_airport(sources, plan.destination) if plan.destination else None
    destination = found_dest[0] if found_dest else None
    dest_metar = load_metar(weather, destination.ident) if destination else None
    controller = Controller(airport, plan, metar, strict_freq=options.strict_freq, destination=destination,
                            destination_metar=dest_metar, centers=centers, chatter=config.traffic.chatter,
                            strict_readback=config.atc.strict_readback)
    return Session(config, options, plan, plan_source, airport, source_name, destination, metar, dest_metar,
                   centers, sim, controller, weather, notices, winds)


def build_plan(request: PlanRequest, options: SessionOptions, config: Config,
               simbrief: SimbriefLoader) -> tuple[FlightPlan, str]:
    """SimBrief plan with the given values on top, or a purely manual plan."""
    overrides = {name: value for name, value in {
        "callsign": request.callsign and request.callsign.upper(),
        "departure": request.departure and request.departure.upper(),
        "destination": request.destination and request.destination.upper(),
        "cruise_ft": request.cruise_ft,
        "route": request.route,
        "aircraft": request.aircraft and request.aircraft.upper(),
    }.items() if value}
    if request.simbrief is None:
        if "callsign" not in overrides:
            raise SetupError("--callsign is required (or use --simbrief)")
        if "departure" not in overrides and options.nosim:
            raise SetupError("--from is required with --nosim (or use --simbrief)")
        return FlightPlan(**{"departure": "", **overrides}), "manual"
    username = request.simbrief or config.simbrief_username
    if not username:
        raise SetupError("--simbrief needs a username, or set simbrief_username in settings.toml")
    plan, cached = simbrief(username)
    return replace(plan, **overrides), "SimBrief, cached copy (offline)" if cached else "SimBrief"


def departure_from_position(sources: list[AirportData], plan: FlightPlan, state) -> tuple[FlightPlan, str | None]:
    """With MSFS, the airport the aircraft stands at is the departure airport, whatever the plan says."""
    if not state.on_ground:
        return plan, None
    ident = next((i for s in sources if (i := s.nearest(state.lat, state.lon, DETECT_AIRPORT_NM))), None)
    if ident is None or ident == plan.departure:
        return plan, None
    notice = (f"The aircraft is at {ident}, not at the flight plan's departure {plan.departure}: using {ident}."
              if plan.departure else f"Departure airport detected from the aircraft position: {ident}.")
    return replace(plan, departure=ident), notice


def sample_wind(sim: SimSource, n: int, interval_s: float, sleep: Callable[[float], None] = time.sleep):
    samples = []
    for i in range(n):
        if i:
            sleep(interval_s)
        state = sim.read()
        samples.append((state.wind_dir_true, state.wind_speed_kt))
    return samples


def origin_metar(mode: str, sim: SimSource, weather: WeatherSource, icao: str, winds) -> Metar | None:
    if mode == "sim":
        raw = metar_from_sim(icao, datetime.now(timezone.utc), list(winds), getattr(sim, "weather", lambda: None)())
        return parse_metar(raw)
    return load_metar(weather, icao)


def airport_sources(config: Config) -> list[AirportData]:
    """Little Navmap first (matches the installed scenery), JSON as the offline/portable fallback."""
    sources: list[AirportData] = []
    if (db := lnm_files.find(config.littlenavmap_db)) is not None:
        source = LittleNavmapAirportData(db)
        source.name = lnm_files.describe(db)  # which scenery: "Little Navmap (MSFS 2024)"
        sources.append(source)
    sources.append(JsonAirportData(config.airports_dir))
    return sources


def center_sectors(config: Config) -> CenterSectors:
    """The real sectors from the user's Little Navmap database (the MSFS ones, worldwide); without them the shipped
    VATSIM sectors (Germany only, atc/airspace/vatsim.py). Corrections in centers.json come first. A sector without
    a known frequency is never used, nor shown."""
    own = load_centers(config.centers_file) if config.centers_file.exists() else CenterSectors()
    own = CenterSectors([s for s in own.sectors if not s.placeholder], source=own.source)
    imported, source = [], "Little Navmap"
    if (db := lnm_files.find(config.littlenavmap_db)) is not None:
        try:
            imported = load_littlenavmap_centers(db)
        except (OSError, sqlite3.Error) as e:
            raise CentersError(f"Center sectors from Little Navmap: {e}") from None
    if not imported and config.vatsim_centers_file.exists():
        imported, source = list(load_centers(config.vatsim_centers_file).sectors), VATSIM_SOURCE
    return with_imported(own, imported, source)


def find_airport(sources: list[AirportData], ident: str) -> tuple[Airport, str] | None:
    for source in sources:
        if airport := source.get(ident):
            return airport, source.name
    return None


def load_metar(weather: WeatherSource, icao: str) -> Metar | None:
    raw = weather.metar(icao)
    if raw is None:
        return None
    try:
        return parse_metar(raw)
    except ValueError:
        return None


def describe_plan(plan: FlightPlan) -> str:
    cruise = "" if plan.cruise_ft is None else (
        f" FL{plan.cruise_ft // 100:03}" if plan.cruise_ft >= 10000 else f" {plan.cruise_ft} ft")
    text = f"{plan.callsign} {plan.aircraft or ''} {plan.rules} {plan.departure} -> {plan.destination or '?'}{cruise}"
    return " ".join(text.split()) + (f", route {plan.route}" if plan.route else "")


def describe_centers(centers: CenterSectors) -> str:
    if not centers:
        return "Center sectors: none, so Departure keeps you until Approach"
    return f"Center sectors: {len(centers.sectors)} from {centers.source}"


def describe_runway(end: RunwayEnd, metar: Metar | None) -> str:
    if metar is None or metar.wind_kt is None or metar.wind_dir is None or metar.wind_kt == 0:
        return f"{end.name} (calm or variable wind)"
    c = wind_components(end.heading_true, metar.wind_dir, metar.wind_kt)
    head = f"headwind {c.headwind:.0f} kt" if c.headwind >= 0 else f"tailwind {-c.headwind:.0f} kt"
    side = "right" if c.crosswind > 0 else "left"
    return f"{end.name} ({head}, crosswind {abs(c.crosswind):.0f} kt from the {side})"
