"""Our own small SimConnect client, with ctypes (step S1). It replaces Python-SimConnect (AGPL-3.0, see BUILD.md).

SimConnect is MSFS's C interface in SimConnect.dll. The few calls we need:
- SimConnect_Open / SimConnect_Close: connect to the running sim;
- SimConnect_AddToDataDefinition: a "data definition" is a list of simvars with units, numbered by us;
- SimConnect_RequestDataOnSimObject: ask once for a definition's values of the user aircraft;
- SimConnect_RequestDataOnSimObjectType: the same for every aircraft within a radius (AI traffic, step S2);
- SimConnect_GetNextDispatch: fetch the next message from the sim, if there is one (we poll; no window messages).
The answer to a request is a SIMCONNECT_RECV_SIMOBJECT_DATA: a header and then the values, packed in the order of
the definition (FLOAT64 = 8 bytes, STRING32 = 32 bytes).

`Dll` is the only part that touches SimConnect.dll; `NativeSimConnect` does the rest and is tested with a fake.

DATA SOURCE / LICENCE: SimConnect.dll is Microsoft's (MSFS SDK). It is not in the repository; find_dll() looks for
it (settings, next to the app, the MSFS SDK, the old Python-SimConnect package). See BUILD.md.
"""
import ctypes
import importlib.util
import os
import struct
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from atc import paths
from atc.sim.msfs_addons import addons, exe_xml_files

# SIMCONNECT_RECV_ID: what kind of message GetNextDispatch returned
RECV_EXCEPTION, RECV_OPEN, RECV_QUIT, RECV_SIMOBJECT_DATA, RECV_SIMOBJECT_DATA_BYTYPE = 1, 2, 3, 8, 9
FLOAT64, STRING32, STRING256 = 4, 6, 9  # SIMCONNECT_DATATYPE
PERIOD_ONCE = 1  # SIMCONNECT_PERIOD
OBJECT_USER = 0  # SIMCONNECT_OBJECT_ID_USER
SIMOBJECT_AIRCRAFT = 2  # SIMCONNECT_SIMOBJECT_TYPE
UNUSED = 0xFFFFFFFF
GROUP_PRIORITY_HIGHEST = 1  # SIMCONNECT_GROUP_PRIORITY_HIGHEST
EVENT_FLAG_GROUPID_IS_PRIORITY = 0x10
HEADER = struct.Struct("<3I")  # dwSize, dwVersion, dwID
OBJECT_DATA = struct.Struct("<3I7I")  # header + request, object, define, flags, entry, out of, define count
SIZES = {FLOAT64: 8, STRING32: 32, STRING256: 256}

NOT_FOUND = ("SimConnect.dll was not found: not from the MSFS SDK, nor from an add-on that brings one along (GSX, "
             "the programs MSFS starts). Install the MSFS SDK (free: MSFS Developer Mode → Help → SDK Installer), or "
             "set its path in Settings → Simulator")


class SimConnectError(OSError):
    pass


SDK_FOLDERS = (Path("C:/MSFS SDK"), Path("C:/MSFS 2024 SDK"))  # the SDK installer's default folders
PE_AMD64 = 0x8664


def is_64bit(path: Path) -> bool:
    """A 64-bit Windows DLL (the app is 64-bit and can't load a 32-bit one)."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        return head[pe:pe + 4] == b"PE\0\0" and struct.unpack_from("<H", head, pe + 4)[0] == PE_AMD64
    except (OSError, struct.error):
        return False


def known_places() -> list[Path]:
    """SimConnect.dll copies already on the PC (2026-11-16): the SDK's default folders, and the ones other add-ons
    bring along: the folders of the programs in MSFS's EXE.xml, GSX's Couatl. Whether the DLL may be shipped is
    unclear (BUILD.md), so the app never ships it; it only uses a copy where it already is."""
    places = [folder / "SimConnect SDK" / "lib" / "SimConnect.dll" for folder in SDK_FOLDERS]
    for xml in exe_xml_files():
        places += [program.parent / "SimConnect.dll" for _, program in addons(xml)]
    if program_files := os.environ.get("ProgramFiles(x86)"):
        places.append(Path(program_files) / "Addon Manager" / "couatl" / "SimConnect.dll")  # GSX
    return places


def find_dll(setting: Path | None = None) -> Path:
    """Where SimConnect.dll is, in this order: the settings, next to the app (a release build), the MSFS SDK (its
    installer sets MSFS_SDK / MSFS2024_SDK), the Python-SimConnect package of older developer installs, copies other
    add-ons brought along (known_places, 64-bit only)."""
    candidates = [setting] if setting and setting != Path() else []
    if getattr(sys, "frozen", False):  # the release build: next to "MSFS ATC.exe"
        candidates.append(Path(sys.executable).parent / "SimConnect.dll")
    candidates.append(paths.resources() / "SimConnect.dll")
    for var in ("MSFS_SDK", "MSFS2024_SDK"):
        if sdk := os.environ.get(var):
            candidates.append(Path(sdk) / "SimConnect SDK" / "lib" / "SimConnect.dll")
    if (spec := importlib.util.find_spec("SimConnect")) and spec.origin:  # the package isn't imported, only found
        candidates.append(Path(spec.origin).parent / "SimConnect.dll")
    candidates += [place for place in known_places() if place.is_file() and is_64bit(place)]
    for path in candidates:
        if path.is_file():
            return path
    raise SimConnectError(NOT_FOUND)


class Dll:
    """The ctypes calls into SimConnect.dll. HRESULTs below 0 are errors."""

    def __init__(self, path: Path, name: str = "MSFS ATC"):
        self.lib = ctypes.WinDLL(str(path))
        self.handle = wintypes.HANDLE()
        hr = self.lib.SimConnect_Open(ctypes.byref(self.handle), name.encode(), None, 0, None, 0)
        if hr < 0:
            raise ConnectionError("SimConnect_Open failed: MSFS is not running")

    def add(self, define: int, name: str, units: str | None, kind: int) -> None:
        self._check(self.lib.SimConnect_AddToDataDefinition(
            self.handle, define, name.encode(), units.encode() if units else None, kind, ctypes.c_float(0), UNUSED),
            f"AddToDataDefinition {name}")

    def request(self, request: int, define: int) -> None:
        self._check(self.lib.SimConnect_RequestDataOnSimObject(
            self.handle, request, define, OBJECT_USER, PERIOD_ONCE, 0, 0, 0, 0), "RequestDataOnSimObject")

    def request_by_type(self, request: int, define: int, radius_m: int) -> None:
        self._check(self.lib.SimConnect_RequestDataOnSimObjectType(
            self.handle, request, define, radius_m, SIMOBJECT_AIRCRAFT), "RequestDataOnSimObjectType")

    def set_data(self, define: int, data: bytes) -> None:
        """Write a data definition's values on our aircraft (an L-var for GSX, C4)."""
        buffer = ctypes.create_string_buffer(data, len(data))
        self._check(self.lib.SimConnect_SetDataOnSimObject(self.handle, define, OBJECT_USER, 0, 0, len(data), buffer),
                    "SetDataOnSimObject")

    def map_event(self, event: int, name: str) -> None:
        self._check(self.lib.SimConnect_MapClientEventToSimEvent(self.handle, event, name.encode()),
                    f"MapClientEventToSimEvent {name}")

    def transmit_event(self, event: int, data: int) -> None:
        """A key event to our own aircraft, e.g. COM_RADIO_SET_HZ (C2)."""
        self._check(self.lib.SimConnect_TransmitClientEvent(
            self.handle, OBJECT_USER, event, wintypes.DWORD(data), GROUP_PRIORITY_HIGHEST,
            EVENT_FLAG_GROUPID_IS_PRIORITY), "TransmitClientEvent")

    def next_message(self) -> bytes | None:
        """The next message as bytes, or None when there is none waiting."""
        data, size = ctypes.c_void_p(), wintypes.DWORD()
        if self.lib.SimConnect_GetNextDispatch(self.handle, ctypes.byref(data), ctypes.byref(size)) < 0 \
                or not data.value:
            return None
        return ctypes.string_at(data.value, size.value)

    def close(self) -> None:
        if self.handle:
            self.lib.SimConnect_Close(self.handle)
            self.handle = wintypes.HANDLE()

    @staticmethod
    def _check(hr: int, what: str) -> None:
        if hr < 0:
            raise SimConnectError(f"SimConnect {what} failed ({hr & 0xFFFFFFFF:#010x})")


@dataclass(frozen=True)
class Var:
    key: str  # our name, e.g. "PLANE_LATITUDE" (the names Python-SimConnect used, so nothing else changes)
    units: str | None  # None for a string
    kind: int = FLOAT64

    @property
    def simvar(self) -> str:
        if self.key.startswith("L:"):  # an L-var keeps its name: "L:FSDT_GSX_BOARDING_STATE"
            return self.key
        return self.key.replace("_", " ")  # SimConnect's own name: "PLANE LATITUDE", "COM ACTIVE FREQUENCY:1"


def unpack(variables: tuple[Var, ...], data: bytes) -> dict[str, float | str]:
    """The values after the header, in the definition's order."""
    values, offset = {}, 0
    for var in variables:
        size = SIZES[var.kind]
        raw = data[offset:offset + size]
        values[var.key] = struct.unpack("<d", raw)[0] if var.kind == FLOAT64 else \
            raw.split(b"\0", 1)[0].decode("latin-1").strip()
        offset += size
    return values


class NativeSimConnect:
    """The `Requests` that SimConnectSource reads: get(simvar) → value, or None while the sim sends nothing.
    All variables of one group (the aircraft state, the weather) are fetched together and kept for `max_age`, so
    the ten get() calls of one tick cost one request."""

    def __init__(self, dll, groups: dict[str, tuple[Var, ...]], timeout: float = 1.0, max_age: float = 0.2,
                 clock=time.monotonic, sleep=time.sleep):
        self.dll, self.timeout, self.max_age, self.clock, self.sleep = dll, timeout, max_age, clock, sleep
        self.groups = list(groups.values())
        self.group_ids = {name: i for i, name in enumerate(groups, start=1)}
        self.group_of: dict[str, int] = {}
        for define, variables in enumerate(self.groups, start=1):
            for var in variables:
                dll.add(define, var.simvar, var.units, var.kind)
                self.group_of[var.key] = define
        self.cache: dict[int, tuple[float, dict]] = {}
        self.quit = False
        self.events: dict[str, int] = {}  # key event name -> our client event ID

    def set(self, key: str, value: float) -> None:
        """Write one variable that has a definition of its own (a writable L-var)."""
        self.dll.set_data(self.group_of[key], struct.pack("<d", value))

    def send_event(self, name: str, data: int) -> None:
        """A key event for our aircraft, e.g. ("COM_RADIO_SET_HZ", 121705000): the co-pilot tunes COM1 (C2)."""
        if name not in self.events:
            self.events[name] = len(self.events) + 1
            self.dll.map_event(self.events[name], name)
        self.dll.transmit_event(self.events[name], data)

    def get(self, key: str) -> float | str | None:
        define = self.group_of[key]
        cached = self.cache.get(define)
        if cached is None or self.clock() - cached[0] > self.max_age:
            values = self._fetch(define)
            if values is None:
                return None
            cached = self.cache[define] = (self.clock(), values)
        return cached[1][key]

    def _fetch(self, define: int) -> dict | None:
        if self.quit:
            raise SimConnectError("MSFS has closed")
        self.dll.request(define, define)  # request ID = define ID: one request per group
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            message = self.dll.next_message()
            if message is None:
                self.sleep(0.005)
                continue
            kind = HEADER.unpack_from(message)[2]
            if kind == RECV_QUIT:
                self.quit = True
                raise SimConnectError("MSFS has closed")
            if kind == RECV_SIMOBJECT_DATA:
                request = OBJECT_DATA.unpack_from(message)[3]
                if request == define:
                    return unpack(self.groups[define - 1], message[OBJECT_DATA.size:])
        return None  # loading, pause menu: SimConnectSource keeps the last state and says it is stale

    def objects(self, group: str, radius_m: int) -> list[tuple[int, dict]] | None:
        """A group's values for every aircraft within radius_m, as (object ID, values); None without an answer.
        The sim sends one SIMOBJECT_DATA_BYTYPE message per aircraft, numbered "entry of out of"; with no aircraft
        at all it sends one with "out of" 0."""
        if self.quit:
            raise SimConnectError("MSFS has closed")
        define = self.group_ids[group]
        self.dll.request_by_type(define, define, radius_m)
        found: dict[int, dict] = {}
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            message = self.dll.next_message()
            if message is None:
                self.sleep(0.005)
                continue
            kind = HEADER.unpack_from(message)[2]
            if kind == RECV_QUIT:
                self.quit = True
                raise SimConnectError("MSFS has closed")
            if kind != RECV_SIMOBJECT_DATA_BYTYPE:
                continue
            fields = OBJECT_DATA.unpack_from(message)
            request, object_id, out_of = fields[3], fields[4], fields[8]
            if request != define:
                continue
            if out_of == 0:
                return []
            found[object_id] = unpack(self.groups[define - 1], message[OBJECT_DATA.size:])
            if len(found) >= out_of:
                return list(found.items())
        return None

    def close(self) -> None:
        self.dll.close()
