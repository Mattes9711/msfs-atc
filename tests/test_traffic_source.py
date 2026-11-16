"""S2: the list of other aircraft (AI / FSLTL traffic) from SimConnect, against a fake DLL."""
import struct

from atc.sim.native import FLOAT64, OBJECT_DATA, RECV_SIMOBJECT_DATA_BYTYPE, NativeSimConnect
from atc.sim.simconnect import SimConnectSource
from atc.sim.traffic import TRAFFIC_VARS, FakeTraffic, Traffic
from tests.test_native_simconnect import Clock, FakeDll

DEFINE = 1


def aircraft(object_id, entry, out_of, user=False, airline="Lufthansa", number="123", atc_id="D-AIZA",
             model="A320", lat=53.63, on_ground=True, gs=12.0, title="FSLTL A320 Lufthansa"):
    numbers = [lat, 9.99, 60.0, gs, 225.0, float(on_ground), float(user)]
    body = (struct.pack("<7d", *numbers) + b"".join(s.encode().ljust(32, b"\0") for s in (atc_id, airline, number, model))
            + title.encode().ljust(256, b"\0"))
    return OBJECT_DATA.pack(OBJECT_DATA.size + len(body), 6, RECV_SIMOBJECT_DATA_BYTYPE, DEFINE, object_id, DEFINE, 0,
                            entry, out_of, len(TRAFFIC_VARS)) + body


class TrafficDll(FakeDll):
    def __init__(self, messages):
        super().__init__(answer=False)
        self.messages, self.radius = messages, None

    def request_by_type(self, request, define, radius_m):
        self.radius = radius_m
        self.queue += self.messages


def source(messages):
    dll, clock = TrafficDll(messages), Clock()
    native = NativeSimConnect(dll, {"traffic": TRAFFIC_VARS}, clock=clock, sleep=clock.sleep)
    return SimConnectSource(requests=native, close=native.close), dll, clock


def test_other_aircraft_without_our_own():
    sim, dll, _ = source([aircraft(1, 0, 3, user=True), aircraft(7, 1, 3),
                          aircraft(9, 2, 3, airline="", number="", atc_id="D-EFGH", model="C172", on_ground=False,
                                   gs=95.0)])
    first, second = sim.traffic()
    assert dll.radius == 40 * 1852
    assert first == Traffic(7, 53.63, 9.99, 60.0, 12.0, 225.0, True, "D-AIZA", "Lufthansa", "123", "A320",
                            "FSLTL A320 Lufthansa")
    assert first.callsign == "Lufthansa 123" and second.callsign == "D-EFGH" and not second.on_ground


def test_parked_ai_that_says_it_is_flying_is_on_the_ground():
    # MSFS's own parked AI at EDDH: 0 kt at 55 ft with SIM ON GROUND = 0 (the user's sim check, 2026-11-15)
    sim, _, _ = source([aircraft(7, 1, 1, on_ground=False, gs=0.0)])
    [parked] = sim.traffic()
    assert parked.on_ground


def test_no_aircraft_around():
    empty = OBJECT_DATA.pack(OBJECT_DATA.size, 6, RECV_SIMOBJECT_DATA_BYTYPE, DEFINE, 0, DEFINE, 0, 0, 0, 0)
    assert source([empty])[0].traffic() == []


def test_no_answer_is_an_empty_list_not_an_error():
    sim, _, clock = source([aircraft(7, 0, 2)])  # the second of two never comes
    assert sim.traffic() == [] and clock.t >= 1.0


def test_numbers_and_strings_are_packed_in_definition_order():
    assert [v.kind for v in TRAFFIC_VARS[:7]] == [FLOAT64] * 7
    assert struct.calcsize("<7d") + 4 * 32 + 256 == len(aircraft(1, 0, 1)) - OBJECT_DATA.size  # TITLE: 256


def test_fake_traffic_for_tests_and_practice():
    plane = Traffic(3, 53.6, 10.0, 2000, 140, 230, False, "D-AIZA", "Lufthansa", "1", "A320")
    assert FakeTraffic([plane]).traffic() == [plane]
    assert SimConnectSource(requests=object(), close=None).traffic() == []  # a fake without traffic support


def test_the_check_command_prints_state_and_traffic(monkeypatch, capsys):
    from atc.sim import check
    from atc.sim.fake import FakeSim
    from atc.airport.json_data import JsonAirportData
    from atc.config import ROOT

    class Fake(FakeSim):
        stale = False

        def weather(self):
            return None

        def traffic(self):
            return [Traffic(7, 53.6, 10.0, 3000, 180, 230, False, "D-AIZA", "Lufthansa", "123", "A320")]

        def gsx_values(self):
            return {"L:FSDT_GSX_COUATL_STARTED": 1, "L:FSDT_GSX_BOARDING_STATE": 6}

        def close(self):
            pass

    eddh = JsonAirportData(ROOT / "data" / "airports").get("EDDH")
    monkeypatch.setattr(check, "SimConnectSource", lambda dll_path: Fake.parked_at(eddh))
    monkeypatch.setattr(check.time, "sleep", lambda s: None)
    assert check.main(["--reads", "1"]) == 0
    out = capsys.readouterr().out
    assert "on ground" in out and "1 other aircraft within 40 nm" in out and "Lufthansa 123" in out
    assert "GSX: COUATL_STARTED=1, BOARDING_STATE=6" in out


def test_the_check_command_without_msfs(monkeypatch, capsys):
    from atc.sim import check
    from atc.sim.simconnect import NOT_RUNNING, SimUnavailable

    def refuse(dll_path):
        raise SimUnavailable(NOT_RUNNING)
    monkeypatch.setattr(check, "SimConnectSource", refuse)
    assert check.main([]) == 1 and capsys.readouterr().out.startswith("MSFS is not running")
