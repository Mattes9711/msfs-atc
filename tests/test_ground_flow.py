"""The departure from gate to takeoff clearance, as a conversation with the controller."""
import random
from dataclasses import replace

import pytest

from atc.airport.model import Frequency
from atc.controller.controller import Controller
from atc.flightplan.model import FlightPlan
from atc.flightplan.route import spoken_sid
from atc.phraseology import spoken
from atc.sim.fake import FakeSim
from atc.weather.metar import parse_metar

METAR = parse_metar("METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG")
PLAN = FlightPlan(callsign="DLH4AB", departure="EDDH", destination="EDDM", cruise_ft=35000,
                  route="AMLU2G AMLUH M852 DENIX")
GROUND, TOWER = 121705, 121280  # EDDH has no Delivery: Ground does the clearance (fold-up)


EDDM_METAR = parse_metar("METAR EDDM 141450Z AUTO 08008KT CAVOK 06/00 Q1019 NOSIG")


class Session:
    def __init__(self, airport, plan=PLAN, metar=METAR, destination=None, centers=None):
        self.sim = FakeSim.parked_at(airport)
        self.atc = Controller(airport, plan, metar, destination=destination, destination_metar=EDDM_METAR,
                              rng=random.Random(7), centers=centers)

    def say(self, khz: int, text: str) -> list[str]:
        """What ATC transmitted (spoken) plus hints in brackets, including calls triggered afterwards."""
        self.sim.update(com1_khz=khz)
        return self._texts(self.atc.handle(text, self.sim.read())[1:] + self.atc.tick(self.sim.read()))

    def tick(self, now: float | None = None) -> list[str]:
        return self._texts(self.atc.tick(self.sim.read(), now))

    @staticmethod
    def _texts(responses) -> list[str]:
        return [r.text if r.spoken else f"({r.text})" for r in responses]


@pytest.fixture
def s(eddh, eddm):
    return Session(eddh, destination=eddm)


def test_full_ground_departure(s):
    [clearance] = s.say(GROUND, "Hamburg Ground, Lufthansa 4 alpha bravo, request IFR clearance to Munich, "
                                "information alpha")
    squawk = s.atc.squawk
    assert clearance.startswith("Lufthansa four Alfa Bravo, cleared to Munich via Amluh two Golf departure, "
                                "runway two tree, climb altitude fife thousand feet, squawk ")
    assert "information" not in clearance  # pilot has the current ATIS

    assert s.say(GROUND, f"cleared to Munich, Amluh 2G, runway 23, climb 5000 feet, squawk {squawk}, "
                         "Lufthansa 4AB") == ["(readback correct)", "Lufthansa four Alfa Bravo, readback correct"]
    assert s.say(GROUND, "Lufthansa 4AB, request push and start") == ["Lufthansa four Alfa Bravo, push and start approved, facing west"]

    [taxi] = s.say(GROUND, "Lufthansa 4AB, request taxi")
    assert taxi == "Lufthansa four Alfa Bravo, taxi to holding point runway two tree"
    assert confirmed(s.say(GROUND, "taxi to holding point runway 23, Lufthansa 4AB"))

    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, holding point runway 23, ready for departure") == \
        ["Lufthansa four Alfa Bravo, wind two two zero degrees seven knots, runway two tree, cleared for takeoff"]
    assert confirmed(s.say(TOWER, "runway 23, cleared for takeoff, Lufthansa 4AB"))
    assert s.atc.phase == "takeoff"


def test_outdated_atis_gets_current_letter_and_qnh(s):
    [clearance] = s.say(GROUND, "Lufthansa 4AB, request clearance with information Zulu")
    assert clearance.endswith("information Alfa is now current, QNH one zero one eight")
    squawk = s.atc.squawk
    # QNH is now part of the readback
    assert s.say(GROUND, f"runway 23, 5000 feet, squawk {squawk}, Lufthansa 4AB") == \
        ["Lufthansa four Alfa Bravo, read back QNH"]
    assert s.say(GROUND, f"runway 23, 5000 feet, squawk {squawk}, QNH 1018, Lufthansa 4AB")[0] == "(readback correct)"


def test_no_atis_given_gets_qnh_and_taxi_does_not_repeat_it(s):
    [clearance] = s.say(GROUND, "Lufthansa 4AB, request clearance")
    assert clearance.endswith("information Alfa is current, QNH one zero one eight")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, QNH 1018, Lufthansa 4AB")
    assert "QNH" not in s.say(GROUND, "request taxi, Lufthansa 4AB")[0]


def test_wrong_squawk_readback_is_corrected(s):
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    [correction] = s.say(GROUND, "runway 23, 5000 feet, squawk 1234, Lufthansa 4AB")
    assert correction == f"Lufthansa four Alfa Bravo, negative, I say again, squawk {spoken.squawk(s.atc.squawk)}"


def test_after_a_correction_only_the_corrected_items_are_needed(s):
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, "runway 23, 4000 feet, squawk 1234, Lufthansa 4AB")  # runway right, altitude and squawk wrong
    assert s.say(GROUND, f"5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB") == [
        "(readback correct)", "Lufthansa four Alfa Bravo, readback correct"]


def test_taxi_before_clearance(s):
    assert s.say(GROUND, "Lufthansa 4AB, request taxi") == ["Lufthansa four Alfa Bravo, request IFR clearance first"]


def test_wrong_station_hands_off(s):
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, request clearance") == \
        ["Lufthansa four Alfa Bravo, contact Hamburg Ground one two one decimal seven zero fife"]
    assert s.say(GROUND, "Lufthansa 4AB, ready for departure") == \
        ["Lufthansa four Alfa Bravo, contact Hamburg Tower one two one decimal two eight zero"]


def test_ready_for_departure_without_taxi_clearance(s):
    s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    s.say(GROUND, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert s.say(TOWER, "Lufthansa 4AB, ready for departure") == \
        ["Lufthansa four Alfa Bravo, contact Hamburg Ground one two one decimal seven zero fife for taxi"]


def test_say_again_radio_check_and_unknown_callsign(s):
    [clearance] = s.say(GROUND, "Lufthansa 4AB, request clearance information alpha")
    assert s.say(GROUND, "say again, Lufthansa 4AB") == [clearance]
    assert s.say(TOWER, "Hamburg Tower, Lufthansa 4AB, radio check") == \
        ["Lufthansa four Alfa Bravo, Hamburg Tower, read you fife"]
    assert s.say(GROUND, "request taxi") == ["station calling Hamburg Ground, say again your callsign"]


def test_airport_with_delivery_hands_off_to_ground_after_clearance(eddh, eddm):
    with_delivery = replace(eddh, frequencies=(*eddh.frequencies, Frequency("C", "Hamburg", 121980 + 5)))
    s = Session(with_delivery, destination=eddm)
    assert s.say(GROUND, "Lufthansa 4AB, request clearance").__getitem__(0).endswith(
        "contact Hamburg Delivery one two one decimal niner eight fife")
    s.say(121985, "Lufthansa 4AB, request clearance information alpha")
    out = s.say(121985, f"runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert out[1] == "Lufthansa four Alfa Bravo, readback correct, contact Hamburg Ground one two one decimal seven zero fife"
    # Switching to Ground without reading back the frequency is accepted
    assert s.say(GROUND, "Lufthansa 4AB, request taxi")[0].startswith("Lufthansa four Alfa Bravo, taxi to holding point")


def test_apron_frequencies_are_not_used_as_ground(eddh):
    apron = replace(eddh, frequencies=(Frequency("G", "Hamburgapron", 121500), *eddh.frequencies))
    assert Session(apron).atc.station("ground").freq.khz == GROUND


def test_without_destination_data_the_clearance_spells_the_icao_code(eddh):
    s = Session(eddh)
    assert "cleared to Echo Delta Delta Mike via" in s.say(GROUND, "Lufthansa 4AB, request clearance")[0]


def test_initial_climb_never_above_cruise(eddh):
    s = Session(eddh, plan=replace(PLAN, cruise_ft=4000))
    assert "climb altitude four thousand feet" in s.say(GROUND, "Lufthansa 4AB, request clearance")[0]


def test_squawk_is_octal_and_not_reserved(eddh):
    for seed in range(200):
        code = Controller(eddh, PLAN, METAR, rng=random.Random(seed))._new_squawk()
        assert len(code) == 4 and set(code) <= set("01234567") and code[0] != "7"


@pytest.mark.parametrize("route, words", [
    ("AMLU2G AMLUH M852 DENIX", "Amluh two Golf departure"),
    ("DENIX2A DENIX T700", "Denix two Alfa departure"),
    ("DCT DENIX M852", None),
    ("", None),
])
def test_spoken_sid(route, words):
    assert spoken_sid(route) == words


def confirmed(out: list[str]) -> bool:
    """A correct readback: the app's tick, then ATC says "readback correct", or its goodbye after a handoff."""
    from atc.phraseology.farewell import BY_COUNTRY, DEFAULT
    goodbyes = {p for _, phrases in [*BY_COUNTRY.values(), DEFAULT] for p in phrases}
    return len(out) == 2 and out[0] == "(readback correct)" and (
        out[1] == "Lufthansa four Alfa Bravo, readback correct" or out[1] in goodbyes)
