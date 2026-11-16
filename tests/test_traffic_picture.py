"""T1: what each other aircraft is doing, from its position, at EDDH."""
from dataclasses import replace

from atc.airport.geo import destination_point
from atc.sim.traffic import Traffic
from tests.test_ground_flow import Session
from tests.test_safety import midpoint, rwy_05_23


def plane(lat, lon, alt=60.0, gs=0.0, hdg=0.0, ground=True, oid=7):
    return Traffic(oid, lat, lon, alt, gs, hdg, ground, "D-AIZA", "Lufthansa", "123", "A320")


def on_final(airport, end_name, nm, oid=7):
    end = airport.runway_end(end_name)
    lat, lon = destination_point(end.lat, end.lon, (end.heading_true + 180) % 360, nm)
    return plane(lat, lon, airport.elevation_ft + nm * 300, 140, end.heading_true, False, oid)


def states(s, *traffic):
    s.atc.update_traffic(list(traffic))
    return {i: st for i, st in s.atc.picture.states.items()}


def test_states_on_the_ground_and_in_the_air(eddh):
    s = Session(eddh)
    gate = eddh.default_parking()
    rwy = rwy_05_23(eddh)
    got = states(s, plane(gate.lat, gate.lon, oid=1), plane(gate.lat, gate.lon, gs=12, oid=2),
                 plane(*midpoint(rwy), oid=3), on_final(eddh, "23", 6, oid=4),
                 plane(eddh.lat + 0.5, eddh.lon, 9000, 300, 0, False, oid=5))
    assert [(g.kind, g.runway) for g in got.values()] == [
        ("parked", None), ("taxiing", None), ("on_runway", "05"), ("final", "23"), ("airborne", None)]
    assert got[4].distance_nm == 6.0 and got[4].airport == "EDDH"


def test_a_departure_climbing_out_after_the_runway(eddh):
    s = Session(eddh)
    rwy = rwy_05_23(eddh)
    states(s, plane(*midpoint(rwy), gs=140))
    end = eddh.runway_end("23")
    lat, lon = destination_point(end.lat, end.lon, end.heading_true, 1)
    assert states(s, plane(lat, lon, 1500, 160, end.heading_true, False))[7].kind == "departing"
    # The same position without having been on the runway is just "airborne" (e.g. a missed approach)
    assert states(Session(eddh), plane(lat, lon, 1500, 160, end.heading_true, False))[7].kind == "airborne"


def test_transitions_tell_what_changed(eddh):
    s = Session(eddh)
    final = on_final(eddh, "23", 2)
    s.atc.update_traffic([final])
    assert [(t.before, t.after.kind) for t in s.atc.transitions] == [(None, "final")]
    s.atc.update_traffic([replace(final, lat=final.lat + 0.001)])  # still on final, a bit closer
    assert s.atc.transitions == []
    rwy = rwy_05_23(eddh)
    s.atc.update_traffic([replace(final, lat=midpoint(rwy)[0], lon=midpoint(rwy)[1], on_ground=True)])
    [landed] = s.atc.transitions
    assert (landed.before.kind, landed.after.kind, landed.after.runway) == ("final", "on_runway", "05")


def test_runway_and_final_queries(eddh):
    s = Session(eddh)
    rwy = rwy_05_23(eddh)
    s.atc.update_traffic([plane(*midpoint(rwy), oid=1), on_final(eddh, "05", 3, oid=2), on_final(eddh, "05", 9, oid=3)])
    key = lambda end: s.atc._runway_key(eddh, end)[1]
    assert [t.object_id for t in s.atc.picture.on_runway("EDDH", "05")] == [1]
    assert [t.object_id for t in s.atc.picture.on_final("EDDH", "05", 4, key)] == [2]
    assert s.atc.picture.on_runway("EDDH", "15") == []


def test_the_live_loop_reads_traffic_every_3_seconds(eddh):
    from atc.events import ConsoleSink
    from atc.runtime import LiveSession
    from atc.sim.fake import FakeSim
    from tests.test_simconnect import Collect

    class TrafficSim(FakeSim):
        reads = 0

        def traffic(self):
            TrafficSim.reads += 1
            return [plane(53.6, 10.0, oid=9)]

    s, now, out = Session(eddh), [0.0], Collect()
    session = LiveSession(TrafficSim.parked_at(eddh), ConsoleSink(out, out.show), s.atc, clock=lambda: now[0])
    for now[0] in (0.0, 1.0, 2.0, 3.0, 4.0, 6.5):
        session.step()
    assert TrafficSim.reads == 3 and 9 in s.atc.picture.states


def test_an_aircraft_recreated_after_a_dropout_keeps_its_state(eddh):
    """B4: the sim re-creates it under a new ID; the ADS-B callsign tells it is the same, so a landing is seen."""
    s = Session(eddh)
    final = replace(on_final(eddh, "23", 2, oid=1), atc_id="DLH1AL")
    s.atc.update_traffic([final])
    rwy = rwy_05_23(eddh)
    s.atc.update_traffic([replace(final, object_id=2, lat=midpoint(rwy)[0], lon=midpoint(rwy)[1], on_ground=True)])
    [landed] = s.atc.transitions
    assert (landed.before.kind, landed.after.kind) == ("final", "on_runway")
