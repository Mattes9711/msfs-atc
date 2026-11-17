"""Milestone 9, part B: small fields without a controller, where an Info station informs (B1-B3), or nobody
answers at all (B4)."""
import math
import random
from dataclasses import replace

from atc.airport.geo import destination_point
from atc.airport.model import Airport, Frequency, Parking, Runway, RunwayEnd, TaxiPath
from atc.controller.controller import Controller
from atc.controller.suggest import suggestion
from atc.intent.parser import parse
from atc.sim.fake import FakeSim
from atc.sim.traffic import Traffic
from tests.test_ground_flow import EDDM_METAR, METAR, PLAN

LON0 = 9.0
FULL, SHORT = "Delta Mike Alfa Bravo Charlie", "Delta Bravo Charlie"
INFO_A, INFO_B, UNICOM = 122705, 127110, 123500


def field(ident: str, name: str, lat0: float, frequencies: tuple[Frequency, ...], circuit: str = "L") -> Airport:
    """Runway 09/27, 800 m long along y=0, a taxiway at y=100 and one parking spot north of it."""
    def ll(x: float, y: float) -> tuple[float, float]:
        return lat0 + y / 111_195, LON0 + x / (111_195 * math.cos(math.radians(lat0)))

    def path(p, q, name="A", type="PT", start="N", end="N"):
        return TaxiPath(*ll(*p), *ll(*q), name, type, start, end)

    runway = Runway(2600, 65, (RunwayEnd("09", 90, *ll(0, 0), 0, None, circuit),
                               RunwayEnd("27", 270, *ll(800, 0), 0, None, circuit)))
    paths = (path((400, 200), (400, 100), "", type="P", start="P"), path((0, 100), (400, 100)),
             path((400, 100), (800, 100)), path((0, 100), (0, 30), "A1", end="HSND"),
             path((800, 100), (800, 30), "A2", end="HSND"))
    parking = (Parking("P 1", "RGAS", *ll(400, 200), 0, ()),)
    return Airport(ident, name, *ll(400, 0), 0, 0, frequencies, (runway,), parking, paths)


ORIGIN = field("EDXA", "Alpha", 53.0, (Frequency("FSS", "Alpha", INFO_A), Frequency("UC", "Langen", 125100)))
DEST = field("EDXB", "Bravo", 53.0 + 20 / 60, (Frequency("FSS", "Bravo", INFO_B),), circuit="R")
SILENT = field("EDXC", "Charlie", 53.0, (Frequency("UC", "Charlie", UNICOM),))
VFR = replace(PLAN, callsign="DMABC", rules="VFR", aircraft="C172", route="", departure="EDXA",
              destination="EDXB")


class Flight:
    def __init__(self, origin=ORIGIN, dest=DEST):
        self.origin, self.dest = origin, dest
        self.sim = FakeSim.parked_at(origin, ga=True)
        plan = replace(VFR, departure=origin.ident, destination=dest.ident)
        self.atc = Controller(origin, plan, METAR, destination=dest, destination_metar=EDDM_METAR,
                              rng=random.Random(7))

    def say(self, khz: int, text: str) -> list[str]:
        self.sim.update(com1_khz=khz)
        return self._texts(self.atc.handle(text, self.sim.read())[1:] + self.atc.tick(self.sim.read()))

    def tick(self) -> list[str]:
        return self._texts(self.atc.tick(self.sim.read()))

    @staticmethod
    def _texts(responses) -> list[str]:
        return [r.text if r.spoken else f"({r.text})" for r in responses]

    def airborne(self, nm: float) -> list[str]:
        self.sim.fly(self.origin, self.dest, nm, 2500)
        return self.tick()


def test_info_station_and_uncontrolled_fields():
    assert ORIGIN.frequencies[0].station == "Alpha Info"
    assert not ORIGIN.controlled and not SILENT.controlled


def test_b1_taxi_information_with_readback():
    f = Flight()
    assert f.say(INFO_A, f"Alpha Info, {FULL}, C172, at the apron, VFR to Bravo, request taxi information") == [
        f"{FULL}, Alpha Info, runway two seven, wind two two zero degrees seven knots, QNH one zero one eight, "
        "left hand circuit"]
    assert f.atc.phase == "taxi"
    assert f.say(INFO_A, f"runway 27, QNH 1018, {FULL}") == ["(readback correct)", f"{SHORT}, readback correct"]


def test_b1_taxiing_without_a_call_moves_the_phase_on():
    f = Flight()
    f.sim.update(ground_speed_kt=10)
    assert f.tick() == [] and f.atc.phase == "taxi"


def test_b2_ready_for_departure_and_leaving_the_frequency():
    f = Flight()
    f.say(INFO_A, f"Alpha Info, {FULL}, request taxi information")
    f.say(INFO_A, f"runway 27, QNH 1018, {FULL}")
    assert f.say(INFO_A, f"Alpha Info, {SHORT}, ready for departure runway 27") == [
        f"{SHORT}, wind two two zero degrees seven knots, runway two seven free"]
    assert f.atc.phase == "takeoff"
    assert f.airborne(2) == [] and f.atc.phase == "enroute"
    assert f.atc._info_role() == "info"  # still close to the field
    [bye] = f.say(INFO_A, f"Alpha Info, {SHORT}, leaving the circuit, leaving the frequency")
    assert bye.startswith(SHORT)
    assert f.atc._info_role() is None


def test_b2_traffic_on_final_instead_of_runway_free():
    f = Flight()
    f.say(INFO_A, f"Alpha Info, {FULL}, request taxi information")
    f.say(INFO_A, f"runway 27, QNH 1018, {FULL}")
    end = ORIGIN.runway_end("27")
    lat, lon = destination_point(end.lat, end.lon, 90, 2)
    f.atc.update_traffic([Traffic(1, lat, lon, 600, 90, 270, False, "DEFGH", "", "", "C152")])
    [said] = f.say(INFO_A, f"Alpha Info, {SHORT}, ready for departure runway 27")
    assert said.endswith("traffic on final runway two seven")


def test_b3_inbound_final_and_vacated():
    f = Flight()
    f.sim.update(com1_khz=INFO_B)
    f.atc.phase = "enroute"
    assert f.airborne(10) == []  # 10 nm out: not yet Info's
    assert f.atc._info_role() == "arrival_info"  # within 15 nm
    [info] = f.say(INFO_B, f"Bravo Info, {FULL}, 10 miles south, 2500 feet, for landing")
    assert info == (f"{FULL}, Bravo Info, runway zero niner, wind zero eight zero degrees eight knots, "
                    "QNH one zero one niner, right hand circuit, no reported traffic")
    assert f.atc.phase == "approach"
    assert f.say(INFO_B, f"runway 09, QNH 1019, {FULL}") == ["(readback correct)", f"{SHORT}, readback correct"]

    end = DEST.runway_end("09")
    f.sim.on_final(DEST, end, 2)
    assert f.say(INFO_B, f"Bravo Info, {SHORT}, on final runway 09") == [
        f"{SHORT}, wind zero eight zero degrees eight knots, runway zero niner free"]
    f.sim.landed(DEST, end)
    f.sim.update(ground_speed_kt=20)
    assert f.tick() == [] and f.atc.phase == "vacating"
    assert f.say(INFO_B, f"Bravo Info, {SHORT}, runway vacated") == [f"{SHORT}, roger"]
    assert f.atc.phase == "taxi_in"
    spot = DEST.parking[0]
    f.sim.update(lat=spot.lat, lon=spot.lon, ground_speed_kt=0)
    assert f.tick() == ["(parked, flight complete)"]
    assert f.tick() == []


def test_b3_circuit_traffic_is_counted():
    f = Flight()
    f.atc.phase = "enroute"
    f.sim.fly(ORIGIN, DEST, 12, 2500)
    f.atc.update_traffic([Traffic(1, DEST.lat + 0.01, DEST.lon, 1000, 90, 90, False, "DEFGH", "", "", "C152"),
                          Traffic(2, DEST.lat - 0.01, DEST.lon, 1000, 90, 270, False, "DEIJK", "", "", "C152"),
                          Traffic(3, DEST.lat, DEST.lon, 9000, 300, 0, False, "DLH1", "DLH", "1", "A320")])
    [info] = f.say(INFO_B, f"Bravo Info, {FULL}, 8 miles south, 2500 feet, for landing")
    assert info.endswith("right hand circuit, two aircraft in the circuit")


def test_b4_blind_calls_get_no_answer():
    f = Flight(origin=SILENT)
    assert f.say(UNICOM, f"Charlie traffic, {FULL}, taxiing to runway 27") == [
        "(blind call on 123.500: Charlie has no Info station, nobody answers)"]
    f.airborne(2)
    f.say(UNICOM, f"Charlie traffic, {FULL}, leaving the circuit, leaving the frequency")
    assert "EDXC" in f.atc.info_left


def test_suggestions_at_small_fields():
    f = Flight()
    sug = suggestion(f.atc)
    assert sug["khz"] == INFO_A and sug["text"] == (
        f"Alpha Info, {FULL}, C172, at the apron, VFR to Bravo, request taxi information")
    f.say(INFO_A, f"Alpha Info, {FULL}, request taxi information")
    f.say(INFO_A, f"runway 27, QNH 1018, {FULL}")
    assert suggestion(f.atc)["text"].endswith("ready for departure runway 27")

    blind = Flight(origin=SILENT)
    blind.sim.update(com1_khz=UNICOM)
    blind.tick()  # the blind call goes on the frequency tuned: known from the sim
    sug = suggestion(blind.atc)
    assert sug["station"] == "Charlie traffic" and sug["khz"] == UNICOM
    assert sug["text"] == f"Charlie traffic, {FULL}, taxiing to runway 27"


def test_parser_hears_the_small_field_calls():
    assert parse("Bravo Info, DMABC, leaving the circuit, leaving the frequency", "DMABC").kind == "leaving_frequency"
    assert parse("Bravo Info, DMABC, 10 miles south, 2500 feet, for landing", "DMABC").kind == "inbound"
    assert parse("Bravo Info, DMABC, on final runway 09", "DMABC").kind == "on_final"
