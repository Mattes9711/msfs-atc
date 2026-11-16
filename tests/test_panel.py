"""R1: the airport card, NEXT in the radio box, the flight line, the push-to-talk light."""
import json

from atc.flightplan.model import FlightPlan
from tests.test_app import PLAN, get, post, server  # noqa: F401 (the server fixture)
from tests.test_apron import DELIVERY
from tests.test_ground_flow import EDDM_METAR, GROUND, Session


def test_airport_card_one_frequency_per_job_in_flight_order(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.tick()
    a = s.atc.status()["airport"]
    assert (a["ident"], a["name"], a["runway"], a["qnh"], a["wind"]) == ("EDDH", "Hamburg", "23", 1018, "220/07")
    assert [(f["label"], f["khz"]) for f in a["frequencies"]] == [
        ("ATIS", 124325), ("GND", 121705), ("TWR", 121280), ("APP", 118205)]
    munich = Session(eddm, plan=FlightPlan("DLH4AB", "EDDM"), metar=EDDM_METAR)
    munich.tick()
    assert [f["label"] for f in munich.atc.status()["airport"]["frequencies"]] == [
        "ATIS", "DEL", "APRON", "GND", "TWR", "APP"]


def test_next_is_whom_to_call_else_the_one_after(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.tick()
    assert s.atc.status()["next"] == {"name": "Hamburg Ground", "khz": GROUND}  # not tuned yet
    s.sim.update(com1_khz=GROUND)
    s.tick()
    assert s.atc.status()["next"] == {"name": "Hamburg Tower", "khz": 121280}  # Ground does Delivery here too
    munich = Session(eddm, plan=FlightPlan("DLH4AB", "EDDM"), metar=EDDM_METAR)
    munich.sim.update(com1_khz=DELIVERY)
    munich.tick()
    assert munich.atc.status()["next"]["name"] == "Munich Apron"


def test_flight_line_and_callsign(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.tick()
    st = s.atc.status()
    assert st["flight"] == {"sid": "AMLU2G", "star": None, "destination": "EDDM"}
    assert st["callsign"] == "Lufthansa 4AB"


def test_the_push_to_talk_light(server):  # noqa: F811
    app, base = server
    post(base + "/api/start", PLAN)
    st = json.loads(get(base + "/api/status")[2])
    assert st["ptt"] in ("loading", "off") and st["ptt_key"] == "Right Ctrl"  # tests have no microphone
