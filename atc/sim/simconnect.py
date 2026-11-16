"""Live aircraft state from MSFS through our own SimConnect client (atc/sim/native.py, step S1).

Units as found in the Milestone 0 spike: heading comes in radians, COM1 as a MHz float (126.85499999999999),
wind direction is degrees true, PLANE_ALT_ABOVE_GROUND is ~9 ft while parked.
"""
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from atc.sim import gsx
from atc.sim.base import AircraftState
from atc.sim.native import Dll, NativeSimConnect, SimConnectError, Var, find_dll
from atc.sim.traffic import M_PER_NM, RADIUS_NM, TRAFFIC_VARS, Traffic, traffic_from_simvars
from atc.units import COM_MAX_KHZ, COM_MIN_KHZ, mhz_to_khz

# simvar -> units, as Python-SimConnect asked for them (so state_from_simvars stays the same)
STATE_UNITS = {
    "PLANE_LATITUDE": "degrees", "PLANE_LONGITUDE": "degrees", "PLANE_ALTITUDE": "feet",
    "PLANE_ALT_ABOVE_GROUND": "feet", "SIM_ON_GROUND": "bool", "PLANE_HEADING_DEGREES_MAGNETIC": "radians",
    "GROUND_VELOCITY": "knots", "COM_ACTIVE_FREQUENCY:1": "MHz",
    "AMBIENT_WIND_DIRECTION": "degrees", "AMBIENT_WIND_VELOCITY": "knots", "LIGHT_BEACON": "bool",
}
STATE_VARS = tuple(STATE_UNITS)
NOT_RUNNING = ("MSFS is not running or SimConnect can't connect: start MSFS and load a flight, then try again "
               "(to practise without MSFS, use the fake sim)")
WEATHER_UNITS = {"AMBIENT_TEMPERATURE": "celsius", "SEA_LEVEL_PRESSURE": "millibars", "AMBIENT_VISIBILITY": "meters"}
WEATHER_VARS = tuple(WEATHER_UNITS)
GSX_TRIES = 3


class SimUnavailable(Exception):
    pass


class Requests(Protocol):
    """get(simvar) -> value, or None while the sim has no data (NativeSimConnect, or a fake in tests)."""

    def get(self, name: str) -> float | None: ...


@dataclass(frozen=True)
class SimWeather:
    temp_c: float
    sea_level_hpa: float
    visibility_m: float


def state_from_simvars(v: dict[str, float]) -> AircraftState:
    khz = mhz_to_khz(v["COM_ACTIVE_FREQUENCY:1"])
    return AircraftState(
        lat=v["PLANE_LATITUDE"], lon=v["PLANE_LONGITUDE"],
        alt_msl_ft=v["PLANE_ALTITUDE"], alt_agl_ft=v["PLANE_ALT_ABOVE_GROUND"],
        on_ground=v["SIM_ON_GROUND"] >= 0.5,
        heading_mag=math.degrees(v["PLANE_HEADING_DEGREES_MAGNETIC"]) % 360,
        ground_speed_kt=v["GROUND_VELOCITY"],
        com1_khz=khz if COM_MIN_KHZ <= khz <= COM_MAX_KHZ else 0,
        wind_dir_true=v["AMBIENT_WIND_DIRECTION"] % 360, wind_speed_kt=v["AMBIENT_WIND_VELOCITY"],
        beacon=v.get("LIGHT_BEACON", 0.0) >= 0.5,
    )


class SimConnectSource:
    """SimSource for the real sim. Keeps the last good state when MSFS briefly returns no data (loading,
    pause menu), and says so in `stale`, so one missing value never crashes the ATC."""

    name = "MSFS"

    def __init__(self, requests: Requests | None = None, close: Callable[[], None] | None = None,
                 dll_path: Path | None = None):
        if requests is None:
            try:
                dll = Dll(find_dll(dll_path))  # loads SimConnect.dll and connects: only with a real sim
            except ConnectionError:
                raise SimUnavailable(NOT_RUNNING) from None
            except SimConnectError as e:  # SimConnect.dll not found
                raise SimUnavailable(str(e)) from None
            except OSError as e:  # a broken DLL, the wrong bitness
                raise SimUnavailable(f"SimConnect.dll could not be loaded ({e})") from None
            native = NativeSimConnect(dll, {
                "state": tuple(Var(k, u) for k, u in STATE_UNITS.items()),
                "weather": tuple(Var(k, u) for k, u in WEATHER_UNITS.items()),
                "traffic": TRAFFIC_VARS,
                "gsx": tuple(Var(name, "number") for name in gsx.STATE_LVARS.values()),
                "gsx_menu_open": (Var(gsx.MENU_OPEN, "number"),), "gsx_menu_choice": (Var(gsx.MENU_CHOICE, "number"),)})
            requests, close = native, native.close
        self._requests, self._close = requests, close
        self._last: AircraftState | None = None
        self.stale = False
        self.gsx_failures = 0  # GSX L-vars without an answer: after a few, stop asking (each try waits a second)

    def _get(self, names) -> dict[str, float] | None:
        try:
            values = {n: self._requests.get(n) for n in names}
        except OSError:
            return None
        return None if any(v is None for v in values.values()) else values

    def read(self) -> AircraftState:
        values = self._get(STATE_VARS)
        self.stale = values is None
        if values is not None:
            self._last = state_from_simvars(values)
        if self._last is None:
            raise SimUnavailable("no data from MSFS yet: wait until the flight has loaded, or use --nosim")
        return self._last

    def weather(self) -> SimWeather | None:
        values = self._get(WEATHER_VARS)
        if values is None:
            return None
        return SimWeather(values["AMBIENT_TEMPERATURE"], values["SEA_LEVEL_PRESSURE"], values["AMBIENT_VISIBILITY"])

    def traffic(self) -> list[Traffic]:
        """Other aircraft within RADIUS_NM (LiveTraffic, FSLTL, MSFS AI); an empty list when the sim doesn't answer."""
        objects = getattr(self._requests, "objects", None)  # fakes in tests may not have it
        if objects is None:
            return []
        try:
            found = objects("traffic", RADIUS_NM * M_PER_NM)
        except OSError:
            return []
        return [t for object_id, values in found or [] if (t := traffic_from_simvars(object_id, values))]

    def gsx_values(self) -> dict[str, float] | None:
        """GSX's L-vars (C3), or None without an answer. Gives up after GSX_TRIES silent tries: an older MSFS
        without L-vars in SimConnect would cost a second on every try."""
        if self.gsx_failures >= GSX_TRIES:
            return None
        values = self._get(tuple(gsx.STATE_LVARS.values()))
        self.gsx_failures = 0 if values is not None else self.gsx_failures + 1
        return values

    def set_lvar(self, name: str, value: float) -> None:
        """Write an L-var (the GSX menu, C4)."""
        try:
            self._requests.set(name, value)
        except (AttributeError, OSError) as e:
            raise SimUnavailable(f"could not set {name} ({e})") from None

    def set_com1(self, khz: int) -> None:
        """The co-pilot tunes COM1 (C2): the COM_RADIO_SET_HZ key event. To be checked in MSFS."""
        send = getattr(self._requests, "send_event", None)
        if send is None:
            raise SimUnavailable("this sim connection can't tune the radio")
        try:
            send("COM_RADIO_SET_HZ", khz * 1000)
        except OSError as e:
            raise SimUnavailable(f"could not tune COM1 ({e})") from None

    def close(self) -> None:
        if self._close:
            self._close()
