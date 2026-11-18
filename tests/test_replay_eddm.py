"""Milestone 10 G: the 2026-11-17 flight's arrival flown again, Munich runway 26R, by a small simulated pilot.

On that flight Approach turned the aircraft off LAND2B with "heading 215", 45 degrees at the final from far beside
it, and the approach clearance would have come about 4 NM before the threshold. Here the pilot flies what ATC
says: the FMC's fixes (the STAR or the transition) until a heading, the heading, down at 2000 ft/min to the
cleared altitude, the speed, and the localizer once cleared. Twice: without procedure data (the plan's STAR points
LANDU, MIQ) and with Munich-like procedures built in code (made up, not the real data: transition LANDU to a
downwind north of the field, vectors from DM429, FAF GUDEG 11 NM out at 5000 ft)."""
from atc.airport.geo import bearing_deg, destination_point, distance_nm
from atc.airport.procedures import Leg, Procedure, Procedures, Transition
from atc.controller import vectors
from atc.weather.metar import parse_metar
from tests.test_air_flow import HAMBURG_APPROACH, MUNICH_APPROACH
from tests.test_arrival import descending
from tests.test_enroute import CS, SIMBRIEF

FLIGHT_METAR = parse_metar("METAR EDDM 171350Z 24021KT 9999 FEW030 08/02 Q0992")  # as on 2026-11-17
LANDU = next(w for w in SIMBRIEF.waypoints if w.ident == "LANDU")
MIQ = next(w for w in SIMBRIEF.waypoints if w.ident == "MIQ")
STEP_S = 5


def procedures_26r(eddm):
    end = eddm.runway_end("26R")
    downwind = round((end.heading_true + 180 - eddm.mag_var) % 360)

    def fix(ident, along, across, path="TF", alt=None, alt_ft=None, speed=None, course=None):
        return Leg(ident, *vectors.point(end, along, across), path, alt, alt_ft, speed_kt=speed, course=course)

    landu = Leg("LANDU", LANDU.lat, LANDU.lon, "IF", "at_or_below", 10000, speed_kt=250)
    miq = Leg("MIQ", MIQ.lat, MIQ.lon, "TF")
    star = Procedure("LAND2B", "star", "26R", (landu, miq))
    to_downwind = Transition("LANDU", (
        Leg("LANDU", LANDU.lat, LANDU.lon, "IF"), fix("DM411", 8, -12),
        fix("DM422", 0, -10, alt="at_or_above", alt_ft=6000, speed=220),
        fix("DM429", 4, -5, "FM", "at_or_above", 5000, course=downwind),
        fix("DM438", 14, 0, "CF", "at_or_above", 5000)))
    from_miq = Transition("MIQ", (Leg("MIQ", MIQ.lat, MIQ.lon, "IF"), fix("DM438", 14, 0, "TF", "at_or_above", 5000)))
    ils = Procedure("I26R", "approach", "26R", (fix("DM438", 14, 0, "IF"), fix("GUDEG", 11, 0, alt="at", alt_ft=5000)),
                    (to_downwind, from_miq), "ILS")
    return Procedures("EDDM", (star,), (ils,))


class Pilot:
    """Flies and reads back. Records every ATC call with where it came (nm out, nm beside, feet)."""

    def __init__(self, s, eddm, start, route, alt_ft, course=None):
        self.s, self.eddm, self.end = s, eddm, eddm.runway_end("26R")
        (self.lat, self.lon), self.route, self.course = start, list(route), course  # course: an FM leg at the end
        self.heading = bearing_deg(self.lat, self.lon, *self.route[0])  # true
        self.alt, self.cleared_ft, self.speed, self.target_kt = alt_ft, alt_ft, 250.0, 250
        self.assigned = None  # magnetic heading from ATC
        self.approach_cleared = self.on_localizer = self.handed_off = False
        self.descends, self.t = True, 0  # descends: False = stays level after reading back a descent
        self.calls: list[tuple[str, float, float, float]] = []
        self.heard_at: list[int] = []  # the seconds of each call
        self.track: list[tuple[float, float, float]] = []
        self._update()

    def where(self):
        return vectors.frame(self.end, self.lat, self.lon)

    def check_in(self, text):
        self._heard(self.s.say(MUNICH_APPROACH, text))

    def fly(self, seconds):
        for _ in range(int(seconds // STEP_S)):
            self.t += STEP_S
            self._move()
            self._heard(self.s.tick(now=self.t))

    def fly_until(self, done, limit_s=3600):
        while not done():
            assert self.t < limit_s, "the replay never got there"
            self.fly(STEP_S)

    def _heard(self, out):
        spoken = [c for c in out if not c.startswith("(") and not c.endswith("readback correct")]
        along, across = self.where()
        self.calls += [(c, along, across, self.alt) for c in spoken]
        self.heard_at += [self.t for _ in spoken]
        if spoken and self.s.atc.pending:
            self._read_back(self.s.atc.pending)

    def _read_back(self, items):
        words = []
        for i in items:
            if i.key == "altitude_ft":
                words.append(f"descend {i.value} feet")
                self.cleared_ft = i.value
            elif i.key == "flight_level":
                words.append(f"descend flight level {i.value}")
                self.cleared_ft = i.value * 100
            elif i.key == "heading":
                words.append(f"heading {i.value:03d}")
                self.assigned = i.value
            elif i.key == "speed_kt":
                words.append(f"speed {i.value} knots")
                self.target_kt = i.value
            elif i.key == "qnh":
                words.append(f"QNH {i.value}")
            elif i.key == "runway":
                words.append(f"cleared ILS runway {i.value}")
                self.approach_cleared = True
            elif i.key == "frequency_khz":
                words.append(f"Munich Tower {i.value / 1000:.3f}")
                self.handed_off = True
            else:
                raise AssertionError(f"the pilot can't read back {i}")
        self._heard(self.s.say(MUNICH_APPROACH, ", ".join(words) + ", Lufthansa 4AB"))

    def _move(self):
        along, across = self.where()
        if self.approach_cleared and not self.on_localizer and abs(across) < 0.7:
            self.on_localizer = True
        if self.on_localizer:
            want = self.end.heading_true
        elif self.assigned is not None:
            want = (self.assigned + self.eddm.mag_var) % 360
        else:
            while self.route and distance_nm(self.lat, self.lon, *self.route[0]) < 1.5:  # fly-by
                self.route.pop(0)
            want = bearing_deg(self.lat, self.lon, *self.route[0]) if self.route else self.course or self.heading
        turn = (want - self.heading + 540) % 360 - 180
        self.heading = (self.heading + max(-3 * STEP_S, min(3 * STEP_S, turn))) % 360  # rate one
        self.speed += max(-STEP_S, min(STEP_S, self.target_kt - self.speed))
        self.lat, self.lon = destination_point(self.lat, self.lon, self.heading, self.speed * STEP_S / 3600)
        floor = self.cleared_ft
        if self.on_localizer:
            floor = min(floor, self.eddm.elevation_ft + max(0.0, along) * 318)  # the glide slope
        if self.descends and self.alt > floor:
            self.alt = max(floor, self.alt - 2000 / 60 * STEP_S)
        self.track.append((along, across, self.alt))
        self._update()

    def _update(self):
        self.s.sim.update(lat=self.lat, lon=self.lon, alt_msl_ft=self.alt, alt_agl_ft=self.alt - self.eddm.elevation_ft,
                          on_ground=False, ground_speed_kt=round(self.speed),
                          heading_mag=(self.heading - self.eddm.mag_var) % 360)


def arriving_26r(eddh, eddm, p):
    """The Center's descent read back (FL100 with LAND2B), handed to Munich Approach 3 nm before LANDU."""
    s, [descent] = descending(eddh, eddm, "26R", procedures=p)
    s.atc.destination_metar = FLIGHT_METAR
    assert "descend flight level one hundred" in descent and "runway two six right" in descent
    s.say(HAMBURG_APPROACH, "descend flight level 100, Lufthansa 4AB")
    s.atc.phase = "arrival"
    before = next(w for i, w in enumerate(SIMBRIEF.waypoints[1:]) if SIMBRIEF.waypoints[i + 2].ident == "LANDU")
    start = destination_point(LANDU.lat, LANDU.lon, bearing_deg(LANDU.lat, LANDU.lon, before.lat, before.lon), 3)
    return s, start


def heading_digits(text):
    words = {"zero": "0", "one": "1", "two": "2", "tree": "3", "four": "4", "fife": "5", "six": "6", "seven": "7",
             "eight": "8", "niner": "9"}
    return int("".join(words[w] for w in text.replace(",", " ").split()[:3]))


def headings(pilot):
    return [(heading_digits(c.split(" heading ")[1]), along, across) for c, along, across, _ in pilot.calls
            if " heading " in c]


def assert_flown_well(pilot, alt_ft):  # the approach altitude: the FAF's, else 3000 ft above the field
    texts = [c for c, *_ in pilot.calls]
    assert not any("direct" in c for c in texts), texts
    course = pilot.end.heading_true
    for heading, along, across in headings(pilot):  # never 45 degrees at the final from far beside it
        off = abs((heading + pilot.eddm.mag_var - course + 540) % 360 - 180)
        assert abs(across) <= 6 or not 35 < off < 60, (heading, along, across, texts)
    times = [t for t, (c, *_) in zip(pilot.heard_at, pilot.calls) if " heading " in c]
    assert all(b - a >= 30 for a, b in zip(times, times[1:])), texts  # no heading right after another
    [(cleared, along, _, alt)] = [c for c in pilot.calls if "cleared ILS approach" in c[0]]
    assert along >= 9 and abs(alt - alt_ft) <= 300, (cleared, along, alt)  # not 4 nm out
    pilot.fly_until(lambda: pilot.on_localizer)
    along, _ = pilot.where()
    assert along >= 8, (along, texts)  # established 8 nm out or farther, at the FAF's altitude
    assert abs(pilot.alt - alt_ft) <= 300, pilot.alt


def test_replay_without_procedure_data_the_star_then_vectors(eddh, eddm):
    s, start = arriving_26r(eddh, eddm, None)
    pilot = Pilot(s, eddm, start, [(LANDU.lat, LANDU.lon), (MIQ.lat, MIQ.lon)], 10000)
    pilot.check_in("Munich Approach, Lufthansa 4AB, flight level 100")
    first = pilot.calls[0][0]
    assert "descend altitude" in first and "niner niner two" in first, first  # the flight's QNH 992
    assert "expect vectors ILS approach runway two six right" in first and " heading " not in first
    miq_along, _ = vectors.frame(pilot.end, MIQ.lat, MIQ.lon)
    pilot.fly_until(lambda: pilot.where()[0] < miq_along + 2)  # along the STAR to MIQ (fly-by): no heading
    assert not headings(pilot)
    pilot.fly_until(lambda: pilot.approach_cleared)
    assert_flown_well(pilot, 4500)


def test_replay_with_munich_like_procedures_the_transition_then_vectors(eddh, eddm):
    p = procedures_26r(eddm)
    s, start = arriving_26r(eddh, eddm, p)
    fixes = [(leg.lat, leg.lon) for leg in p.approaches[0].transitions[0].legs[:4]]
    pilot = Pilot(s, eddm, start, fixes, 10000, course=(eddm.runway_end("26R").heading_true + 180) % 360)
    pilot.check_in("Munich Approach, Lufthansa 4AB, flight level 100")
    first = pilot.calls[0][0]
    assert "cleared transition Landu" in first and "descend altitude six thousand feet" in first, first
    pilot.fly_until(lambda: pilot.approach_cleared)
    texts = [c for c, *_ in pilot.calls]
    assert any(c.endswith("reduce speed two two zero knots") for c in texts), texts
    assert any("descend altitude fife thousand feet" in c for c in texts), texts
    assert_flown_well(pilot, 5000)


def test_replay_the_aircraft_stays_high_and_approach_notices(eddh, eddm):
    """On the flight the aircraft stayed at 6700 ft, cleared to 4500 ft, and nobody said anything."""
    s, start = arriving_26r(eddh, eddm, None)
    pilot = Pilot(s, eddm, start, [(LANDU.lat, LANDU.lon), (MIQ.lat, MIQ.lon)], 6700)
    pilot.descends = False
    pilot.check_in("Munich Approach, Lufthansa 4AB, 6700 feet")
    pilot.fly(150)
    confirm = [c for c, *_ in pilot.calls if "confirm descending" in c]
    assert confirm == [f"{CS}, confirm descending altitude four thousand fife hundred feet"]
    pilot.descends = True
    pilot.fly(120)
    assert pilot.alt == 4500 and [c for c, *_ in pilot.calls].count(confirm[0]) == 1
