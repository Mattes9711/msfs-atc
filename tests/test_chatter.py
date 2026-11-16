"""T4: the AI aircraft's radio calls on our frequency, from what they really do."""
import io
from dataclasses import replace

from atc.controller.traffic import runway_end_for, spoken_callsign
from atc.events import ConsoleSink, Event
from atc.flightlog import format_line
from atc.runtime import emit_responses
from tests.test_ground_flow import GROUND, TOWER, Session
from tests.test_safety import midpoint, rwy_05_23
from tests.test_traffic_picture import on_final, plane

WIND = "wind two two zero degrees seven knots"


def tuned(eddh, khz, chatter=True):
    s = Session(eddh)
    s.atc.chatter = chatter
    s.sim.update(com1_khz=khz)
    s.tick()
    return s


def chatter(s, traffic):
    return [(r.station, r.text) for r in s.atc.update_traffic(traffic) if r.kind == "chatter"]


def test_how_ai_aircraft_are_called():
    assert spoken_callsign(plane(0, 0)) == "Lufthansa one two tree"
    assert spoken_callsign(replace(plane(0, 0), airline="DLH")) == "Lufthansa one two tree"  # an ICAO code
    assert spoken_callsign(replace(plane(0, 0), airline="", flight_number="")) == "Delta Alfa India Zulu Alfa"


def test_livetraffic_callsigns_are_said_like_real_ones():
    # LiveTraffic: the ADS-B callsign in ATC ID, no airline or flight number (the user's sim check, 2026-11-15)
    live = replace(plane(0, 0), airline="", flight_number="", atc_id="AFR49KP")
    assert spoken_callsign(live) == "Airfrans four niner Kilo Papa"
    assert spoken_callsign(replace(live, atc_id="SAS1234")) == "Scandinavian one two tree four"
    assert spoken_callsign(replace(live, atc_id="NOZ26F")) == "November Oscar Zulu two six Foxtrot"  # unknown: spelled


def test_an_arrival_reports_on_final_and_gets_its_landing_clearance(eddh):
    s = tuned(eddh, TOWER)
    arrival = on_final(eddh, "23", 9)
    s.atc.update_traffic([replace(arrival, lat=arrival.lat + 0.3)])  # first seen far out: no call yet
    assert chatter(s, [arrival]) == [
        ("Lufthansa 123", "Hamburg Tower, Lufthansa one two tree, established ILS runway two tree"),
        ("Hamburg Tower", f"Lufthansa one two tree, {WIND}, runway two tree, cleared to land")]
    assert chatter(s, [replace(arrival, lat=arrival.lat + 0.01)]) == []  # still on final: said once


def test_a_departure_lining_up_is_cleared_for_takeoff(eddh):
    s = tuned(eddh, TOWER)
    gate = eddh.default_parking()
    s.atc.update_traffic([plane(gate.lat, gate.lon, gs=12)])
    lined_up = plane(*midpoint(rwy_05_23(eddh)), gs=0, hdg=230)
    assert runway_end_for(eddh, "05", 230) == "23"
    assert chatter(s, [lined_up]) == [
        ("Hamburg Tower", f"Lufthansa one two tree, {WIND}, runway two tree, cleared for takeoff"),
        ("Lufthansa 123", "runway two tree, cleared for takeoff, Lufthansa one two tree")]


def test_ground_hears_taxi_requests(eddh):
    s = tuned(eddh, GROUND)
    gate = eddh.default_parking()
    s.atc.update_traffic([plane(gate.lat, gate.lon)])
    assert chatter(s, [plane(gate.lat, gate.lon, gs=8)]) == [
        ("Lufthansa 123", "Hamburg Ground, Lufthansa one two tree, request taxi"),
        ("Hamburg Ground", "Lufthansa one two tree, taxi to holding point runway two tree")]


def test_an_aircraft_that_stops_and_goes_asks_for_taxi_once(eddh):
    # The user's flight: SUBURBAN 7534 asked three times, as it stopped and moved on while taxiing
    s = tuned(eddh, GROUND)
    gate = eddh.default_parking()
    s.atc.update_traffic([plane(gate.lat, gate.lon)])
    assert len(chatter(s, [plane(gate.lat, gate.lon, gs=8)])) == 2
    assert chatter(s, [plane(gate.lat, gate.lon, gs=0)]) == []
    assert chatter(s, [plane(gate.lat, gate.lon, gs=8)]) == []


def test_crossing_a_runway_is_not_lining_up(eddh):
    s = tuned(eddh, TOWER)
    gate = eddh.default_parking()
    s.atc.update_traffic([plane(gate.lat, gate.lon, gs=12)])
    across = (rwy_05_23(eddh).ends[0].heading_true + 90) % 360
    assert chatter(s, [plane(*midpoint(rwy_05_23(eddh)), gs=10, hdg=across)]) == []
    assert chatter(s, [plane(*midpoint(rwy_05_23(eddh)), gs=0, hdg=230)])[0][1].endswith(  # turned onto it: lined up
        "runway two tree, cleared for takeoff")


def test_silent_when_switched_off_or_on_another_frequency(eddh):
    for khz, on in ((TOWER, False), (GROUND, True)):  # off; Ground doesn't hear the Tower's arrivals
        s = tuned(eddh, khz, chatter=on)
        arrival = on_final(eddh, "23", 9)
        s.atc.update_traffic([replace(arrival, lat=arrival.lat + 0.3)])
        assert chatter(s, [arrival]) == []


def test_chatter_on_the_console_and_in_the_flight_log():
    spoken, out = [], io.StringIO()

    class Voice:
        def say(self, text, station=None, kind="atc"):
            raise AssertionError("chatter is not ATC talking to us")

        def speak(self, text, station=None, kind="atc"):
            spoken.append((text, station))

    lines = []
    emit_responses(ConsoleSink(Voice(), lines.append), [])
    ConsoleSink(Voice(), lines.append).emit(Event("chatter", "request taxi", "Lufthansa 123"))
    assert lines == ["       [Lufthansa 123] request taxi"] and spoken == [("request taxi", "Lufthansa 123")]
    assert format_line(Event("chatter", "request taxi", "Lufthansa 123", time=0)).endswith(
        "RADIO  Lufthansa 123: request taxi")
