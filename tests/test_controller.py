from atc.controller.controller import Controller
from atc.flightplan.model import FlightPlan
from atc.sim.fake import FakeSim
from atc.weather.metar import parse_metar

PLAN = FlightPlan(callsign="DLH4AB", departure="EDDH")


def tuned(eddh, khz):
    sim = FakeSim.parked_at(eddh)
    sim.update(com1_khz=khz)
    return sim.read()


METAR = parse_metar("METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG")


def controller(eddh, **kwargs):
    return Controller(eddh, PLAN, METAR, **kwargs)


def test_controller_picks_runway_and_atis_from_the_metar(eddh):
    c = controller(eddh)
    assert c.runway == "23" and c.atis.letter == "A"
    assert c.broadcast(124325).startswith("Hamburg information Alfa")
    assert c.broadcast(121280) is None  # tower doesn't broadcast


def test_controller_answers_on_its_frequency(eddh):
    understood, reply = controller(eddh).handle("Hamburg Tower, DLH4AB, radio check", tuned(eddh, 121280))
    assert not understood.spoken
    assert understood.text == "understood: radio_check, callsign DLH4AB (yours)"
    assert reply.spoken
    assert reply.text.startswith("Lufthansa four Alfa Bravo, Hamburg Tower")


def test_wrong_frequency_gives_an_unspoken_hint(eddh):
    [response] = controller(eddh).handle("anyone?", tuned(eddh, 122800))
    assert not response.spoken
    assert "Nobody on 122.800" in response.text
    assert "Hamburg Tower 121.280, 126.855" in response.text


def test_atis_frequency_is_not_a_controller(eddh):
    [response] = controller(eddh).handle("hello", tuned(eddh, 124325))
    assert not response.spoken
    assert "not a controller" in response.text


def test_strict_mode_is_silent_on_wrong_frequency(eddh):
    assert controller(eddh, strict_freq=True).handle("anyone?", tuned(eddh, 122800)) == []
