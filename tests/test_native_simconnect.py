"""Our own SimConnect client (S1) against a fake SimConnect.dll that answers with real message layouts."""
import struct

import pytest

from atc.sim import native
from atc.sim.native import (FLOAT64, OBJECT_DATA, RECV_QUIT, RECV_SIMOBJECT_DATA, STRING32, NativeSimConnect,
                            SimConnectError, Var, find_dll, unpack)
from atc.sim.simconnect import STATE_UNITS, SimConnectSource, SimUnavailable

STATE = {"PLANE_LATITUDE": 53.63, "PLANE_LONGITUDE": 9.99, "PLANE_ALTITUDE": 53.0, "PLANE_ALT_ABOVE_GROUND": 9.0,
         "SIM_ON_GROUND": 1.0, "PLANE_HEADING_DEGREES_MAGNETIC": 3.0, "GROUND_VELOCITY": 0.0,
         "COM_ACTIVE_FREQUENCY:1": 121.705, "AMBIENT_WIND_DIRECTION": 220.0, "AMBIENT_WIND_VELOCITY": 7.0,
         "LIGHT_BEACON": 0.0}


def data_message(request: int, values: list[float]) -> bytes:
    """A SIMCONNECT_RECV_SIMOBJECT_DATA as the sim sends it."""
    body = struct.pack(f"<{len(values)}d", *values)
    return OBJECT_DATA.pack(OBJECT_DATA.size + len(body), 6, RECV_SIMOBJECT_DATA, request, 0, request, 0, 1, 1,
                            len(values)) + body


class FakeDll:
    def __init__(self, answer=True):
        self.definitions, self.requests, self.queue, self.answer, self.closed = [], [], [], answer, False

    def add(self, define, name, units, kind):
        self.definitions.append((define, name, units, kind))

    def request(self, request, define):
        self.requests.append(request)
        if self.answer:
            self.queue.append(b"\0" * 12)  # some other message first (e.g. RECV_NULL): ignored
            self.queue.append(data_message(request + 7, [0.0]))  # an answer to another request: ignored
            values = [STATE[d[1].replace(" ", "_")] for d in self.definitions if d[0] == define]
            self.queue.append(data_message(request, values))

    def next_message(self):
        return self.queue.pop(0) if self.queue else None

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def client(dll, clock=None):
    clock = clock or Clock()
    return NativeSimConnect(dll, {"state": tuple(Var(k, u) for k, u in STATE_UNITS.items())},
                            clock=clock, sleep=clock.sleep)


def test_simvars_are_defined_with_simconnect_names_and_units():
    dll = FakeDll()
    client(dll)
    assert dll.definitions[0] == (1, "PLANE LATITUDE", "degrees", FLOAT64)
    assert (1, "COM ACTIVE FREQUENCY:1", "MHz", FLOAT64) in dll.definitions
    assert (1, "PLANE HEADING DEGREES MAGNETIC", "radians", FLOAT64) in dll.definitions


def test_one_request_per_tick_for_all_values():
    dll, clock = FakeDll(), Clock()
    sc = client(dll, clock)
    assert [sc.get(k) for k in STATE] == list(STATE.values())
    assert dll.requests == [1]  # ten values, one request
    clock.t += 0.5
    sc.get("PLANE_LATITUDE")
    assert dll.requests == [1, 1]  # older than 0.2 s: fetched again


def test_no_answer_is_none_after_the_timeout():
    clock = Clock()
    assert client(FakeDll(answer=False), clock).get("PLANE_LATITUDE") is None
    assert 1.0 <= clock.t < 1.1


def test_msfs_closing_is_an_error_the_source_treats_as_stale():
    dll = FakeDll(answer=False)
    dll.queue.append(struct.pack("<3I", 12, 6, RECV_QUIT))
    sc = client(dll)
    with pytest.raises(SimConnectError, match="MSFS has closed"):
        sc.get("PLANE_LATITUDE")
    source = SimConnectSource(requests=sc, close=sc.close)
    source._last = "the last state"
    assert source.read() == "the last state" and source.stale
    source.close()
    assert dll.closed


def test_strings_are_cut_at_the_first_zero():
    data = struct.pack("<d", 3.5) + b"DLH4AB\0garbage".ljust(32, b"\0")
    assert unpack((Var("A", "feet"), Var("ATC_ID", None, STRING32)), data) == {"A": 3.5, "ATC_ID": "DLH4AB"}


def test_the_state_comes_through_as_before():
    sc = client(FakeDll())
    state = SimConnectSource(requests=sc, close=sc.close).read()
    assert (state.com1_khz, state.on_ground, round(state.heading_mag)) == (121705, True, 172)


# --- finding SimConnect.dll ----------------------------------------------------------------------------------------

@pytest.fixture
def nowhere(monkeypatch, tmp_path):
    """No DLL anywhere: an empty app folder, no SDK, no Python-SimConnect package."""
    monkeypatch.setattr(native.paths, "resources", lambda: tmp_path / "app")
    monkeypatch.setattr(native.importlib.util, "find_spec", lambda name: None)
    for var in ("MSFS_SDK", "MSFS2024_SDK"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def dll_at(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    return path


def test_dll_search_order(nowhere, monkeypatch):
    with pytest.raises(SimConnectError, match="MSFS SDK"):
        find_dll()
    sdk = dll_at(nowhere / "sdk" / "SimConnect SDK" / "lib" / "SimConnect.dll")
    monkeypatch.setenv("MSFS_SDK", str(nowhere / "sdk"))
    assert find_dll() == sdk
    app = dll_at(nowhere / "app" / "SimConnect.dll")
    assert find_dll() == app  # next to the app wins over the SDK
    mine = dll_at(nowhere / "mine" / "SimConnect.dll")
    assert find_dll(mine) == mine  # the setting wins over all


def test_a_missing_dll_is_a_clear_message(nowhere):
    with pytest.raises(SimUnavailable, match="SimConnect.dll was not found"):
        SimConnectSource()
