"""The start screen (Milestone 7): the briefing of the loaded plan, without network or MSFS."""
from atc.config import Config
from atc.flightplan.model import FlightPlan
from atc.preflight import brief
from atc.session import PlanRequest, SessionOptions
from tests.test_app import INJECT, post, server  # noqa: F401  (the server fixture)

PRACTICE = SessionOptions(nosim=True)


def test_a_manual_plan_is_briefed_with_weather_and_runway():
    b = brief(PlanRequest(callsign="dlh4ab", departure="EDDH", destination="EDDM", route="AMLU2G AMLUH M852 DENIX"),
              PRACTICE, Config(), **INJECT)
    assert b["callsign"] == "DLH4AB" and b["spoken_callsign"] == "Lufthansa four Alfa Bravo"
    assert b["sid"] == "AMLU2G" and b["star"] is None
    dep, dest = b["departure"], b["destination"]
    assert (dep["ident"], dep["name"], dep["runway"]) == ("EDDH", "Hamburg", "23")
    assert dep["metar"].startswith("METAR EDDH") and "headwind" in dep["wind"]
    assert dest["name"] == "Munich" and dest["metar"] is None and dest["note"].startswith("no METAR")


def test_a_simbrief_plan_is_briefed():
    plan = FlightPlan(callsign="EJU93KF", departure="EDDH", destination="XXXX", aircraft="A320", cruise_ft=36000,
                      sid="AMLU2G", star="LAND2A")
    b = brief(PlanRequest(simbrief="pilot"), SessionOptions(), Config(), **INJECT, simbrief=lambda user: (plan, False))
    assert b["spoken_callsign"] == "Alpine niner tree Kilo Foxtrot" and b["source"] == "SimBrief"
    assert b["star"] == "LAND2A" and b["destination"]["name"] is None  # no airport data for it
    assert any("stands at" in n for n in b["notes"])  # with MSFS the aircraft's airport counts


def test_the_endpoints(server):  # noqa: F811
    _, base = server
    status, b = post(base + "/api/briefing", {"callsign": "dlh4ab", "departure": "EDDH", "destination": "EDDM",
                                              "nosim": True})
    assert status == 200 and b["departure"]["runway"] == "23"
    assert post(base + "/api/briefing", {"departure": "EDDH", "nosim": True})[0] == 400
