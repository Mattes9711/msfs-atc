"""Milestone 8, D1: the co-pilot flies the radio of a whole flight in the live loop, gate to gate, with Centers.

In the test flight he "did nothing": from 13:14 he had the radio and didn't read back Berlin's "contact Frankfurt"
in 45 s. Here the test only moves the aircraft (push, taxi, fly, land, park), like the pilot in MSFS; every call,
readback, frequency change and check-in is his.
"""
from atc.airport.geo import distance_nm
from atc.events import Collector
from atc.runtime import LiveSession
from tests.test_centers import SECTORS
from tests.test_ground_flow import Session

CS = "Lufthansa four Alfa Bravo"


class Flight:
    def __init__(self, eddh, eddm):
        self.s = Session(eddh, destination=eddm, centers=SECTORS)
        self.sink, self.t = Collector(), [0.0]
        self.live = LiveSession(self.s.sim, self.sink, self.s.atc, clock=lambda: self.t[0])
        self.live.step("/copilot on")

    @property
    def atc(self):
        return self.s.atc

    def step(self, seconds=1.0, **sim):
        if sim:
            self.s.sim.update(**sim)
        self.t[0] += seconds
        self.live.step()

    def until(self, done, what, limit=120, seconds=1.0, **sim):
        """Steps until done() is true; fails with the radio log after `limit` steps."""
        for _ in range(limit):
            if done():
                return
            self.step(seconds, **sim)
        raise AssertionError(f"stuck waiting for {what} (phase {self.atc.phase}, pending "
                             f"{[i.key for i in self.atc.pending]}, call_next "
                             f"{self.atc.call_next.name if self.atc.call_next else None}, co-pilot "
                             f"{'on' if self.atc.copilot_on else 'off'}):\n" + self.log(12))

    def tuned_to(self, role):
        here, wanted = self.atc.station_at(self.s.sim.read().com1_khz), self.atc.station(role)
        return here is not None and wanted is not None and here.key == wanted.key

    def radio(self):
        return [(e.kind, e.text) for e in self.sink.events if e.kind in ("atc", "copilot", "pilot", "notice")]

    def log(self, last=None):
        return "\n".join(f"  {k:8} {t}" for k, t in self.radio()[-(last or 0):])

    def said_by(self, kind):
        return [t for k, t in self.radio() if k == kind]

    def taxi_along(self, route, graph):
        """At taxi speed from node to node of the cleared route, a step each, then stop at its end."""
        for e in route.edges:
            lat, lon = graph.latlon[e.b]
            self.step(5, lat=lat, lon=lon, ground_speed_kt=15, on_ground=True)
        self.step(1, ground_speed_kt=0)


def test_the_copilot_works_the_radio_gate_to_gate(eddh, eddm):
    f = Flight(eddh, eddm)
    atc = f.atc

    f.until(lambda: atc.phase == "cleared" and not atc.pending, "the IFR clearance read back")
    f.until(lambda: atc.phase == "pushback" and not atc.pending, "push and start", beacon=True)
    for _ in range(20):
        f.step(ground_speed_kt=3)  # pushing
    f.until(lambda: atc.phase == "taxi" and not atc.pending, "the taxi clearance read back", ground_speed_kt=0)
    f.taxi_along(atc.route_out, atc.taxi)
    f.until(lambda: atc.phase == "takeoff" and not atc.pending, "the takeoff clearance read back")

    total = distance_nm(eddh.lat, eddh.lon, eddm.lat, eddm.lon)
    nm = 1.0
    while atc.phase not in ("approach",) and nm < total - 20:
        f.s.sim.fly(eddh, eddm, nm, atc.plan.cruise_ft)
        f.step(10)
        nm += 1.2  # 420 kt: 1.2 nm in 10 s
        if atc.copilot_on is False:
            raise AssertionError("he gave the radio back:\n" + f.log(12))
    f.until(lambda: f.tuned_to("approach") and not atc.pending and atc.call_next is None,
            "checked in with Munich Approach and read back", limit=60, seconds=10)

    end = eddm.runway_end(atc.arrival_runway)
    f.s.sim.on_final(eddm, end, 10)  # flew the vectors
    f.until(lambda: f.tuned_to("arrival_tower") and not atc.pending and atc.call_next is None,
            "cleared to land and read back", limit=60, seconds=5)
    assert any(t.startswith(f"{CS}, wind") and t.endswith("cleared to land") for t in f.said_by("atc"))

    f.s.sim.landed(eddm, end)
    f.until(lambda: atc.phase == "taxi_in" and not atc.pending, "the taxi-in clearance read back", ground_speed_kt=0)
    f.taxi_along(atc.route_in, atc._arrival_graph())
    stand = atc.stand_in
    f.until(lambda: atc.said_goodbye, "the goodbye at the stand", limit=60,
            lat=stand.lat, lon=stand.lon, ground_speed_kt=0)
    assert atc.copilot_on
    assert not any(k == "pilot" for k, _ in f.radio())  # the pilot never said a word on the radio
