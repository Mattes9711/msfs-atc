"""Milestone 9, part C: the traffic circuit at a small field. Which leg an aircraft is on (C1), the other aircraft
in the circuit by leg and their position reports (C2), touch-and-go, go-around and full stop (C3)."""
from atc.airport.geo import destination_point
from atc.controller.circuit import circuit_leg, position_report
from atc.controller.suggest import phrase_book, suggestion
from atc.intent.parser import parse
from atc.sim.fake import FakeSim
from atc.sim.traffic import Traffic
from tests.test_info import DEST, FULL, INFO_A, INFO_B, ORIGIN, SHORT, Flight


def at(airport, runway, leg) -> Traffic:
    """Another aircraft on a leg, placed by the fake sim's own circuit."""
    sim = FakeSim.parked_at(airport)
    sim.circuit(airport, airport.runway_end(runway), leg)
    s = sim.read()
    return Traffic(hash(leg) % 1000, s.lat, s.lon, s.alt_msl_ft, s.ground_speed_kt,
                   (s.heading_mag + airport.mag_var) % 360, False, "DEFGH", "", "", "C152")


def leg_of(airport, runway, t: Traffic):
    return circuit_leg(airport, runway, t.lat, t.lon, t.heading_true, t.alt_ft)


def test_c1_every_leg_on_both_sides():
    for airport, runway in ((ORIGIN, "27"), (ORIGIN, "09"), (DEST, "09"), (DEST, "27")):  # left and right
        for leg in ("upwind", "crosswind", "downwind", "base", "final"):
            assert leg_of(airport, runway, at(airport, runway, leg)) == leg, (airport.ident, runway, leg)


def test_c1_no_leg_far_away_high_or_on_the_dead_side():
    end = ORIGIN.runway_end("27")
    t = at(ORIGIN, "27", "downwind")
    assert circuit_leg(ORIGIN, "27", t.lat, t.lon, t.heading_true, 4000) is None  # above the circuit
    lat, lon = destination_point(end.lat, end.lon, 90, 6)
    assert circuit_leg(ORIGIN, "27", lat, lon, 270, 1000) is None  # 6 nm out: no final
    # Runway 27 has a left hand circuit: downwind is south. Flying east north of the field is no downwind
    lat, lon = destination_point(ORIGIN.lat, ORIGIN.lon, 0, 1)
    assert circuit_leg(ORIGIN, "27", lat, lon, 90, 1000) is None
    assert circuit_leg(ORIGIN, "27", t.lat, t.lon, t.heading_true, 0, on_ground=True) is None
    assert position_report("downwind", "L", "27") == "left downwind runway two seven"
    assert position_report("final", "R", "09") == "final runway zero niner"


def test_c1_the_parser_hears_position_reports():
    assert parse("Bravo Info, DMABC, right downwind runway 09", "DMABC").kind == "circuit_report"
    assert parse("Bravo Info, DMABC, left base runway 27", "DMABC").kind == "circuit_report"
    assert parse("Bravo Info, DMABC, on final runway 27, touch and go", "DMABC").kind == "on_final"
    assert parse("report left downwind, DMABC", "DMABC").kind != "circuit_report"


def inbound() -> Flight:
    """At 8 nm from Bravo, after the inbound call and its readback."""
    f = Flight()
    f.atc.phase = "enroute"
    f.sim.fly(ORIGIN, DEST, 12, 2500)
    f.say(INFO_B, f"Bravo Info, {FULL}, 8 miles south, 2500 feet, for landing")
    f.say(INFO_B, f"runway 09, QNH 1019, {FULL}")
    return f


def test_c2_traffic_named_by_its_leg():
    f = Flight()
    f.atc.phase = "enroute"
    f.sim.fly(ORIGIN, DEST, 12, 2500)
    f.atc.update_traffic([at(DEST, "09", "downwind")])
    [info] = f.say(INFO_B, f"Bravo Info, {FULL}, 8 miles south, 2500 feet, for landing")
    assert info.endswith("right hand circuit, one aircraft on right downwind runway zero niner")


def test_c1_c2_our_downwind_report_and_the_traffic():
    f = inbound()
    f.sim.circuit(DEST, DEST.runway_end("09"), "downwind")
    assert f.tick() == []
    assert suggestion(f.atc)["text"] == f"Bravo Info, {SHORT}, right downwind runway 09"
    assert f.say(INFO_B, f"Bravo Info, {SHORT}, right downwind runway 09") == [f"{SHORT}, roger"]
    assert suggestion(f.atc)["text"] == f"Bravo Info, {SHORT}, on final runway 09, full stop"
    f.atc.update_traffic([at(DEST, "09", "final")])
    f.sim.circuit(DEST, DEST.runway_end("09"), "base")
    assert f.say(INFO_B, f"Bravo Info, {SHORT}, right base runway 09") == [
        f"{SHORT}, one aircraft on final runway zero niner"]


def test_c2_the_others_report_their_legs():
    f = inbound()
    f.atc.chatter = True
    other = at(DEST, "09", "crosswind")
    assert f.atc.update_traffic([other], now=100.0, last_radio=50.0) == []  # first seen: nothing new
    downwind = at(DEST, "09", "downwind")
    other = Traffic(other.object_id, downwind.lat, downwind.lon, downwind.alt_ft, 90, downwind.heading_true, False,
                    "DEFGH", "", "", "C152")
    said = f.atc.update_traffic([other], now=105.0, last_radio=50.0)
    assert [(r.station, r.text) for r in said] == [
        ("DEFGH", "Bravo Info, Delta Echo Foxtrot Golf Hotel, right downwind runway zero niner"),
        ("Bravo Info", "Delta Echo Foxtrot Golf Hotel, roger")]
    assert f.atc.update_traffic([other], now=110.0, last_radio=50.0) == []  # once


def test_c3_touch_and_go_then_full_stop():
    f = inbound()
    end = DEST.runway_end("09")
    f.sim.on_final(DEST, end, 1.5)
    f.say(INFO_B, f"Bravo Info, {SHORT}, on final runway 09, touch and go")
    assert f.atc.phase == "landing"
    f.sim.landed(DEST, end)
    f.sim.update(ground_speed_kt=60)  # rolling fast
    assert f.tick() == [] and f.atc.touched
    f.sim.circuit(DEST, end, "upwind")
    assert f.tick() == ["(touch-and-go, back in the circuit (circuit 2))"]
    assert f.atc.phase == "approach" and f.atc.circuits == 1
    f.sim.circuit(DEST, end, "downwind")
    f.tick()
    assert suggestion(f.atc)["text"].endswith("right downwind runway 09")  # reported again
    f.sim.on_final(DEST, end, 1.5)
    f.say(INFO_B, f"Bravo Info, {SHORT}, on final runway 09, full stop")
    f.sim.landed(DEST, end)  # 30 kt: rolling out
    assert f.tick() == [] and f.atc.phase == "vacating"


def test_c3_going_around():
    f = inbound()
    end = DEST.runway_end("09")
    f.sim.on_final(DEST, end, 1.5)
    f.say(INFO_B, f"Bravo Info, {SHORT}, on final runway 09")
    assert f.say(INFO_B, f"Bravo Info, {SHORT}, going around") == [
        "(going around, back in the circuit (circuit 2))", f"{SHORT}, roger"]
    assert f.atc.phase == "approach"
    # Without a call: on crosswind after the final call
    f.say(INFO_B, f"Bravo Info, {SHORT}, on final runway 09")
    f.sim.circuit(DEST, end, "crosswind")
    assert f.tick() == ["(going around, back in the circuit (circuit 3))"]


def test_c3_a_local_flight_flies_circuits():
    f = Flight(dest=ORIGIN)
    f.say(INFO_A, f"Alpha Info, {FULL}, request taxi information")
    f.say(INFO_A, f"runway 27, QNH 1018, {FULL}")
    f.say(INFO_A, f"Alpha Info, {SHORT}, ready for departure runway 27")
    end = ORIGIN.runway_end("27")
    f.sim.circuit(ORIGIN, end, "upwind")
    assert f.tick() == [] and f.atc.phase == "enroute"
    assert f.atc._info_role() == "arrival_info"  # the same Info, now for the landing
    assert suggestion(f.atc) is None  # no "0 miles north, for landing", no "leaving the circuit"
    f.sim.circuit(ORIGIN, end, "crosswind")
    assert f.tick() == [] and f.atc.phase == "approach"  # no release to Info: never left it
    f.sim.circuit(ORIGIN, end, "downwind")
    f.tick()
    assert suggestion(f.atc)["text"] == f"Alpha Info, {SHORT}, left downwind runway 27"
    f.say(INFO_A, f"Alpha Info, {SHORT}, left downwind runway 27")
    assert suggestion(f.atc)["text"] == f"Alpha Info, {SHORT}, on final runway 27, touch and go"


def test_the_phrase_book_shows_the_small_field_first():
    f = Flight()
    book = phrase_book(f.atc)
    assert book[0]["group"] == "Small field (Info)" and book[0]["current"]
    assert not any(g["current"] for g in book[1:])
    assert book[0]["phrases"][0]["pilot"].startswith(f"Alpha Info, {FULL}, at the apron")
