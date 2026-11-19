"""The flight emulator (atc/emulator.py): a simulated aircraft flies gate to gate, the co-pilot works the radio.

Its first runs found three bugs, each with its own test here: the co-pilot asked for taxi to the gate while still
on the runway (the route started on it: back onto the runway), no "holding short" call when the taxi-in crossed a
runway (stuck at EDDH), and the readback "via T, B12W, S7, W2" was refused (taxiway B12W heard as B12, W).
"""
from atc.controller.readback import same
from atc.airport.geo import bearing_deg, destination_point, distance_nm
from atc.emulator import Emulator, Taxi
from atc.intent.parser import parse
from tests.test_centers import SECTORS
from tests.test_ground_flow import Session
from tests.test_info import Flight
from tests.test_safety import at_the_crossing
from tests.test_vfr_controlled import DEST, NO_POINTS, ORIGIN


def fly(departure, destination):
    s = Session(departure, destination=destination, centers=SECTORS)
    return Emulator(s.atc, s.sim).run()


def test_hamburg_to_munich_gate_to_gate(eddh, eddm):
    report = fly(eddh, eddm)
    assert report.finished, report.text()
    assert not report.findings, report.text()


def test_munich_to_hamburg_gate_to_gate(eddm, eddh):
    report = fly(eddm, eddh)
    assert report.finished, report.text()
    assert not report.findings, report.text()


def test_a_taxiway_with_a_letter_after_the_number_reads_back_as_one():
    assert same("taxiways", ["T", "B12", "W", "S7", "W2"], ["T", "B12W", "S7", "W2"])
    assert same("taxiways", ["E2", "N4", "N", "A13", "A13"], ["E2", "N4", "N", "A13"])  # the holding point again
    assert not same("taxiways", ["T", "B12", "S7", "W2"], ["T", "B12W", "S7", "W2"])


def test_a_written_taxiway_with_a_letter_after_the_number_is_one_taxiway():
    intent = parse("taxi to stand G201 via T, B12W, S7, W2, Lufthansa 4AB")
    assert intent.items["taxiways"] == ["T", "B12W", "S7", "W2"]


def fly_vfr(origin, dest):
    f = Flight(origin, dest)
    emulator = Emulator(f.atc, f.sim)
    return emulator.run(), [e.text for e in emulator.sink.events if e.kind in ("copilot", "atc", "pilot")]


def test_vfr_gate_to_gate_out_via_the_point_in_via_the_point_round_the_circuit():
    report, radio = fly_vfr(ORIGIN, DEST)
    assert report.finished, report.text()
    assert not report.findings, report.text()
    said = "\n".join(radio)
    for call in ("leave the control zone via November", "Tango Tower, Delta Bravo Charlie, November",
                 "leaving the control zone, frequency change approved", "for landing",
                 "enter the control zone via Sierra", "overhead Sierra", "join right downwind runway",
                 "right downwind runway", "cleared to land", "taxi to parking"):
        assert call in said, said
    assert any(c.startswith("reported November") for c in report.checks), report.text()


def test_vfr_into_a_zone_without_reporting_points_straight_into_the_circuit():
    report, radio = fly_vfr(ORIGIN, NO_POINTS)
    assert report.finished, report.text()
    assert not report.findings, report.text()
    said = "\n".join(radio)
    assert "join right downwind runway" in said and "cleared to land" in said, said


def test_joining_the_taxi_route_short_of_a_hold_rolls_up_to_it():
    # EDDF 07C: joined 40 m before the hold short, the emulator stopped where it was, too far to report holding short
    s = at_the_crossing()
    graph, route = s.atc.taxi, s.atc.route_out
    [(_, hold)] = s.atc.crossing_points(route)
    before = next(e.a for e in route.edges if e.b == hold)
    lat, lon = destination_point(*graph.latlon[hold], bearing_deg(*graph.latlon[hold], *graph.latlon[before]),
                                 40 / 1852)
    taxi = Taxi(route, graph, s.atc.airport.ident, here=(lat, lon))
    for _ in range(10):
        lat, lon, _, _ = taxi.move(lat, lon, 1, 15, set())
    assert distance_nm(lat, lon, *graph.latlon[hold]) * 1852 < 1
