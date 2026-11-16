"""Milestone 9, part A: a VFR flight in a small aircraft with a registration callsign (A1-A5)."""
import json
from dataclasses import replace

import pytest

from atc.airport.littlenavmap import _parking_name
from atc.airport.model import Parking
from atc.config import Config
from atc.controller.ground import stand_words
from atc.controller.suggest import suggestion, written_callsign
from atc.intent.parser import parse
from atc.phraseology import spoken
from atc.session import PlanRequest, SessionOptions, SetupError, airport_metar, borrows, build_session
from atc.weather.source import LiveWeather, StaticWeather, nearest_report
from tests.test_events import AIRPORTS, WEATHER
from tests.test_ground_flow import EDDM_METAR, GROUND, PLAN, TOWER, Session

VFR = replace(PLAN, callsign="DMABC", rules="VFR", aircraft="C172", route="")
FULL, SHORT = "Delta Mike Alfa Bravo Charlie", "Delta Bravo Charlie"


@pytest.fixture
def v(eddh, eddm):
    return Session(eddh, plan=VFR, destination=eddm)


def test_registrations_are_spelled_and_shortened_the_icao_way():
    assert spoken.callsign("D-MABC") == FULL and spoken.short_callsign("D-MABC") == SHORT
    assert spoken.short_callsign("DLH4AB") is None and spoken.short_callsign("N123AB") is None
    assert written_callsign("DMABC") == FULL and written_callsign("DMABC", short=True) == SHORT


@pytest.mark.parametrize("text", [
    "Hamburg Ground, D-MABC, request taxi", "Delta Mike Alpha Bravo Charlie, request taxi", "DMABC request taxi",
    "d m a b c request taxi", "Delta Bravo Charlie, request taxi",
    "Delta Mike Alpha Victor Charlie, request taxi"])  # one letter misheard in the full form
def test_the_parser_hears_the_registration_in_any_form(text):
    intent = parse(text, "DMABC")
    assert intent.addressed_to_us and intent.kind == "request_taxi"


def test_three_letters_of_a_taxi_route_are_no_callsign():
    assert parse("taxi via delta bravo", "DMABC").callsign is None
    assert parse("Delta Bravo Charlie", "DMABC").callsign == "DMABC"  # but the short form itself is
    assert parse("Lufthansa 4AB request taxi", "DLH4AB").callsign == "DLH4AB"  # airlines as before


def test_vfr_needs_no_clearance_and_no_pushback(v):
    assert v.atc.phase == "cleared" and v.atc.squawk == "7000"
    assert v.say(GROUND, f"Hamburg Ground, {FULL}, request push and start") == [
        f"{FULL}, no pushback required, report ready to taxi"]
    assert v.say(GROUND, f"{SHORT}, request clearance") == [
        f"{SHORT}, VFR, no clearance required, squawk seven zero zero zero, report ready to taxi"]


def test_the_controller_uses_the_short_form_first_then_the_pilot(v):
    v.sim.update(com1_khz=GROUND)
    v.tick()
    sug = suggestion(v.atc)
    assert sug["title"] == "Request taxi"
    assert sug["text"] == f"Hamburg Ground, {FULL}, C172, VFR to Munich, information alfa, request taxi"
    [taxi] = v.say(sug["khz"], sug["text"])
    assert taxi.startswith(f"{FULL}, taxi to holding point")  # the first call: in full
    readback = suggestion(v.atc)
    assert readback["text"].endswith(f", {SHORT}")  # the controller said it, so now we may
    assert v.say(readback["khz"], readback["text"]) == ["(readback correct)", f"{SHORT}, readback correct"]
    assert not v.atc.short_form_used(v.atc.station_at(TOWER))  # each controller starts in full


def test_a_small_aircraft_gets_no_cabin_crew_and_no_gsx():
    def session(rules):
        return build_session(PlanRequest(callsign="DMABC", departure="EDDH", rules=rules),
                             SessionOptions(nosim=True), Config(), weather=WEATHER, airports=AIRPORTS)

    assert session("IFR").cabin() is not None
    vfr = session("vfr")
    assert vfr.plan.rules == "VFR" and vfr.cabin() is None and vfr.gsx() is None
    with pytest.raises(SetupError):
        session("SVFR")


EDHI = "METAR EDHI 161650Z 24012KT 210V280 9999 FEW029 08/04 Q0998 RMK BLU"


def test_a_field_without_a_metar_borrows_the_nearest_one(eddh):
    weather = StaticWeather({"EDHI": EDHI, "EDDM": EDDM_METAR.raw},
                            {"EDHI": (53.536, 9.837), "EDDM": (48.354, 11.786)})
    metar = airport_metar(weather, eddh)  # no METAR for EDDH in this weather: Finkenwerder's, 8 NM away
    assert metar.raw == "EDDH 161650Z 24012KT 210V280 9999 FEW029 08/04 Q0998 RMK FROM EDHI"
    assert metar.station == "EDDH" and metar.qnh_hpa == 998 and borrows(metar)
    with_sim = airport_metar(weather, eddh, winds=[(300, 6), (300, 6)])  # the sim's wind at the field
    assert with_sim.raw == "EDDH 161650Z 30006KT 9999 FEW029 08/04 Q0998 RMK FROM EDHI WIND MSFS"
    assert (with_sim.wind_dir, with_sim.wind_kt) == (300, 6)
    assert airport_metar(StaticWeather({"EDDM": EDDM_METAR.raw}, {"EDDM": (48.354, 11.786)}), eddh) is None  # too far
    assert not borrows(airport_metar(StaticWeather({"EDDH": EDHI.replace("EDHI", "EDDH")}), eddh))  # its own


def test_live_weather_asks_for_the_box_around_the_field_and_keeps_the_last_answer(tmp_path):
    asked = []

    def fetch(url, timeout):
        asked.append(url)
        return json.dumps([{"icaoId": "EDHI", "lat": 53.536, "lon": 9.837, "rawOb": EDHI}])

    found = nearest_report(LiveWeather(tmp_path, fetch=fetch), 53.64, 9.70, "EDHE")
    assert found[0].station == "EDHI" and round(found[1]) == 8
    assert asked == ["https://aviationweather.gov/api/data/metar?bbox=53.223,8.997,54.057,10.403&format=json"]

    def offline(url, timeout):
        raise OSError("no network")

    assert LiveWeather(tmp_path, fetch=offline).nearby(53.64, 9.70, 25)[0].raw == EDHI  # from the cache
    assert LiveWeather(tmp_path / "new", fetch=offline).nearby(53.64, 9.70, 25) == []


def test_a_small_aircraft_parks_on_a_ga_ramp_with_a_plain_name(v, eddm):
    stand = v.atc._stand()
    assert stand.is_ga and stand_words(stand) == f"parking {spoken.spell(stand.name.split()[-1])}"
    assert stand_words(Parking("27", "RGAS", 0, 0, 0, ())) == "parking two seven"  # Little Navmap's "NONE 27"
    assert stand_words(Parking("P 707A", "RGAM", 0, 0, 0, ())) == "parking seven zero seven Alfa"
    assert stand_words(Parking("", "RGAS", 0, 0, 0, ())) == stand_words(None) == "the apron"
    assert stand_words(Parking("G 201", "GM", 0, 0, 0, ())) == "stand Golf two zero one"  # airliners as before
    assert Session(eddm, destination=eddm).atc._stand().is_gate
    assert [_parking_name(n) for n in ("NONE", None, "P", "G")] == ["", "", "P", "G"]
