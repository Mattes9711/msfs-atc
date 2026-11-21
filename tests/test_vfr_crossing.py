"""Milestone 9 E3: VFR through the control zone of another field on the way ("request crossing of the control zone
from Sierra to November")."""
from dataclasses import replace

from atc.airport.model import Frequency
from atc.controller.suggest import phrase_book, suggestion
from atc.controller.vfr import zones_along
from atc.intent.parser import parse
from tests.test_info import FULL, SHORT, Flight
from tests.test_vfr_controlled import ORIGIN, TWR_B, airborne_at, controlled

TWR_V = 120100
CROSS = controlled("EDXV", "Victor", 53.0 + 20 / 60, (Frequency("T", "Victor", TWR_V),),
                   (("NOVMR", 0, 5), ("SIERA", 180, 5)))
DEST = controlled("EDXU", "Uniform", 53.0 + 40 / 60, (Frequency("T", "Uniform", TWR_B),), (("SIERA", 180, 5),))
REQUEST = "request crossing of the control zone from Sierra to November"


def on_the_way(cross=CROSS) -> Flight:
    f = Flight(ORIGIN, DEST)
    f.atc.crossing_fields = (cross,)
    f.atc.phase = "enroute"
    airborne_at(f, 180, 13, 1400, field=cross)
    return f


def cleared(f: Flight) -> None:
    f.say(TWR_V, f"Victor Tower, {FULL}, {REQUEST}")
    assert f.say(TWR_V, f"Cleared to cross the control zone via Sierra and November, 1500 feet or below, {SHORT}")[0] \
        == "(readback correct)"


def test_the_request_and_the_clearance_parsed():
    request = parse(f"Victor Tower, {FULL}, {REQUEST}")
    assert request.kind == "request_crossing" and request.items == {"vfr_point": "S", "vfr_exit": "N"}
    readback = parse("cleared to cross the control zone via Sierra and November, 1500 feet or below")
    assert readback.items == {"altitude_ft": 1500, "vfr_point": "S", "vfr_exit": "N"}
    assert parse("request crossing of the control zone from the south to the north").items == {
        "vfr_point": "SOUTH", "vfr_exit": "NORTH"}


def test_only_the_zones_on_the_way_once_each():
    finkenwerder = replace(CROSS, ident="EDXW", runways=(replace(CROSS.runways[0], length_ft=1000),))
    aside = controlled("EDXX", "Xray", 53.0 + 20 / 60, (Frequency("T", "Xray", 121100),), ())
    aside = replace(aside, lon=aside.lon + 1, control_zone=replace(
        aside.control_zone, polygon=tuple((lat, lon + 1) for lat, lon in aside.control_zone.polygon)))
    assert zones_along([ORIGIN, finkenwerder, CROSS, aside, DEST], ORIGIN, DEST) == (CROSS,)


def test_the_clearance_via_the_points_named():
    f = on_the_way()
    [answer] = f.say(TWR_V, f"Victor Tower, {FULL}, {REQUEST}")
    assert answer == (f"{f.atc.cs}, Victor Tower, cleared to cross the control zone via Sierra and November, one "
                      "thousand fife hundred feet or below, report Sierra")
    assert f.atc.ctr_stage == "crossing"


def test_without_points_named_the_ones_toward_the_aircraft_and_the_destination():
    f = on_the_way()
    [answer] = f.say(TWR_V, f"Victor Tower, {FULL}, request crossing of the control zone")
    assert "via Sierra and November" in answer


def test_over_the_points_tower_lets_the_flight_go():
    f = on_the_way()
    cleared(f)
    assert airborne_at(f, 180, 6, 1400, field=CROSS) == []
    assert airborne_at(f, 180, 4.5, 1400, field=CROSS) == []
    assert airborne_at(f, 180, 3, 1400, field=CROSS) == [] and f.atc.ctr_point.code == "N"  # Sierra passed
    assert airborne_at(f, 0, 4, 1400, field=CROSS) == []
    assert airborne_at(f, 0, 7, 1400, field=CROSS) == [
        f"{SHORT}, leaving the control zone, frequency change approved"]
    assert f.atc.ctr_stage is None and f.atc.crossing is None and f.atc.phase == "enroute"


def test_the_pilot_reports_the_points():
    f = on_the_way()
    cleared(f)
    airborne_at(f, 180, 5, 1400, field=CROSS)
    assert f.say(TWR_V, f"Victor Tower, {SHORT}, Sierra") == [f"{SHORT}, roger, report November"]
    airborne_at(f, 0, 5, 1400, field=CROSS)
    assert f.say(TWR_V, f"Victor Tower, {SHORT}, November") == [
        f"{SHORT}, leaving the control zone, frequency change approved"]


def test_too_high_in_the_zone():
    f = on_the_way()
    cleared(f)
    assert airborne_at(f, 180, 2, 2000, field=CROSS) == [
        f"{SHORT}, check altitude, one thousand fife hundred feet or below"]


def test_a_field_without_points_by_directions_out_of_the_zone():
    f = on_the_way(replace(CROSS, vfr_points=()))
    [answer] = f.say(TWR_V, f"Victor Tower, {FULL}, request crossing of the control zone")
    assert answer.endswith("cleared to cross the control zone from the south to the north, one thousand fife "
                           "hundred feet or below, report leaving the control zone")
    f.say(TWR_V, f"Cleared to cross the control zone from the south to the north, 1500 feet or below, {SHORT}")
    assert airborne_at(f, 180, 4, 1400, field=CROSS) == []
    assert airborne_at(f, 0, 9, 1400, field=CROSS) == [
        f"{SHORT}, leaving the control zone, frequency change approved"]


def test_the_request_on_another_frequency_goes_to_the_zones_tower():
    f = on_the_way()
    [answer] = f.say(TWR_B, f"Uniform Tower, {FULL}, {REQUEST}")
    assert "Victor Tower" in answer and f.atc.ctr_stage is None


def test_the_towered_fields_near_the_line(eddh, eddm):
    from tests.test_main import AIRPORTS

    [source] = AIRPORTS
    near = source.towered_near((eddh.lat, eddh.lon), (eddm.lat, eddm.lon), 15)
    assert "EDDH" in near and "EDDM" in near
    assert zones_along([eddh, eddm], eddh, eddm) == ()


def test_e3b_the_suggestions_fly_the_crossing():
    f = on_the_way()
    airborne_at(f, 180, 20, 1400, field=CROSS)  # 12 nm before the zone: not yet
    assert f.atc.crossing_ahead() is None
    airborne_at(f, 180, 17, 1400, field=CROSS)  # 9 nm before it
    sug = suggestion(f.atc)
    assert sug == {"title": "Request crossing", "station": "Victor Tower", "khz": TWR_V,
                   "text": f"Victor Tower, {FULL}, 17 miles south, 1400 feet, request crossing of the control zone "
                           "from Sierra to November"}
    assert f.atc.expected_station().name == "Victor Tower"
    f.say(TWR_V, sug["text"])
    sug = suggestion(f.atc)
    assert sug["text"] == f"cleared to cross the control zone via Sierra and November, 1500 feet or below, {SHORT}"
    assert f.say(TWR_V, sug["text"])[0] == "(readback correct)"
    airborne_at(f, 180, 5, 1400, field=CROSS)
    assert suggestion(f.atc)["text"] == f"Victor Tower, {SHORT}, Sierra"
    f.say(TWR_V, suggestion(f.atc)["text"])
    airborne_at(f, 0, 5, 1400, field=CROSS)
    assert f.say(TWR_V, suggestion(f.atc)["text"]) == [
        f"{SHORT}, leaving the control zone, frequency change approved"]
    assert f.atc.crossing_ahead() is None and "EDXV" in f.atc.crossed


def test_e3b_the_phrase_book_marks_the_zone_group():
    f = on_the_way()
    airborne_at(f, 180, 15, 1400, field=CROSS)
    [first, *_] = phrase_book(f.atc)
    assert first["group"] == "Control zone (VFR)"
    request = next(p for p in first["phrases"] if p["title"] == "Request crossing")
    assert request["pilot"].startswith(f"Victor Tower, {FULL}, ")


def test_e3b_into_the_zone_without_a_clearance_a_hint_once():
    f = on_the_way()
    assert airborne_at(f, 180, 7, 1400, field=CROSS) == [
        "(you are in the control zone of Victor without a clearance: call Victor Tower 120.100 and request "
        "crossing)"]
    assert airborne_at(f, 180, 5, 1400, field=CROSS) == []
    airborne_at(f, 0, 9, 1400, field=CROSS)  # out again
    assert "EDXV" in f.atc.crossed and f.atc.crossing_ahead() is None


def test_an_exit_point_outside_the_zone_is_still_reported():
    # Hamburg's Whiskey one, 1 nm outside its zone: Tower let the flight go at the zone's edge, before W1
    far = controlled("EDXV", "Victor", 53.0 + 20 / 60, (Frequency("T", "Victor", TWR_V),),
                     (("NOVMR", 0, 10), ("SIERA", 180, 5)))
    f = on_the_way(far)
    cleared(f)
    airborne_at(f, 180, 5, 1400, field=far)
    assert airborne_at(f, 180, 3, 1400, field=far) == [] and f.atc.ctr_point.code == "N"  # Sierra passed
    assert airborne_at(f, 0, 8.5, 1400, field=far) == [] and f.atc.ctr_stage == "crossing"  # out, November ahead
    assert airborne_at(f, 0, 10, 1400, field=far) == []
    assert airborne_at(f, 0, 11, 1400, field=far) == [f"{SHORT}, leaving the control zone, frequency change approved"]
