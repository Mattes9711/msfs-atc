"""The flight emulator (atc/emulator.py): a simulated aircraft flies gate to gate, the co-pilot works the radio.

Its first runs found three bugs, each with its own test here: the co-pilot asked for taxi to the gate while still
on the runway (the route started on it: back onto the runway), no "holding short" call when the taxi-in crossed a
runway (stuck at EDDH), and the readback "via T, B12W, S7, W2" was refused (taxiway B12W heard as B12, W).
"""
from atc.controller.readback import same
from atc.emulator import Emulator
from atc.intent.parser import parse
from tests.test_centers import SECTORS
from tests.test_ground_flow import Session


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
