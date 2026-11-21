"""Milestone 9, part E: VFR flights out of and into the control zone of a controlled field (E1, E2)."""
from dataclasses import replace

from atc.airport.geo import destination_point
from atc.airport.model import ControlZone, Frequency, VfrPoint
from atc.controller.suggest import suggestion
from atc.controller.vfr import ctr_limit_ft, point_code, point_words, point_written, zone_point
from atc.intent.parser import parse
from tests.test_info import FULL, SHORT, Flight, field

TWR_A, GND_A, ATIS_A, TWR_B, ATIS_B = 118100, 121900, 123125, 119100, 124100


def controlled(ident, name, lat0, frequencies, points, circuit="L"):
    """A field with a Tower, its reporting points (ident, bearing, nm) and a control zone 8 nm around it."""
    a = field(ident, name, lat0, frequencies, circuit)
    vfr = tuple(VfrPoint(p, *destination_point(a.lat, a.lon, brg, nm)) for p, brg, nm in points)
    corners = tuple(destination_point(a.lat, a.lon, brg, 11.3) for brg in (45, 135, 225, 315))
    return replace(a, vfr_points=vfr, control_zone=ControlZone(name, 2500, corners))


ORIGIN = controlled("EDXT", "Tango", 53.0, (
    Frequency("T", "Tango", TWR_A), Frequency("G", "Tango", GND_A), Frequency("ATIS", "Tango", ATIS_A)),
    (("NOVMR", 0, 5), ("S1", 180, 3), ("S2", 180, 6)))
DEST = controlled("EDXU", "Uniform", 53.0 + 20 / 60, (
    Frequency("T", "Uniform", TWR_B), Frequency("ATIS", "Uniform", ATIS_B)),
    (("SIERA", 180, 5), ("WHISY", 270, 5)), circuit="R")
NO_POINTS = replace(DEST, vfr_points=())


def ready(f: Flight) -> list[str]:
    f.atc.phase, f.atc.at_holding_point = "taxi", True
    end = f.origin.runway_end(f.atc.runway)
    f.sim.update(lat=end.lat, lon=end.lon)
    return f.say(TWR_A, f"Tango Tower, {FULL}, ready for departure")


def airborne_at(f: Flight, brg: float, nm: float, alt_ft: float, field=None) -> list[str]:
    field = field or f.origin
    lat, lon = destination_point(field.lat, field.lon, brg, nm)
    f.sim.update(lat=lat, lon=lon, alt_msl_ft=alt_ft, alt_agl_ft=alt_ft, on_ground=False, ground_speed_kt=100)
    return f.tick()


def test_reporting_points_said_and_written():
    assert [point_words(p) for p in ("NOVMR", "N1", "S", "WHISY", "EWEST")] == [
        "November", "November one", "Sierra", "Whiskey", "Ewest"]
    assert [point_code(p) for p in ("NOVMR", "N1", "WHISY", "EWEST")] == ["N", "N1", "W", "EWEST"]
    assert [point_written(c) for c in ("N", "S1", "EWEST", "NORTH")] == ["November", "Sierra 1", "Ewest", "north"]
    assert ctr_limit_ft(ORIGIN) == 1500


def test_the_point_toward_the_destination_farthest_out():
    assert zone_point(ORIGIN, DEST.lat, DEST.lon).code == "N"
    assert zone_point(ORIGIN, 52.0, 9.0).code == "S2"  # of S1, S2 the outer one
    assert zone_point(replace(ORIGIN, vfr_points=()), 52.0, 9.0).words == "south"


def test_e1_the_takeoff_clearance_says_how_to_leave_the_zone():
    f = Flight(ORIGIN, DEST)
    [clearance] = ready(f)
    assert "leave the control zone via November, one thousand fife hundred feet or below, squawk seven zero zero " \
           "zero" in clearance
    assert clearance.endswith("cleared for takeoff, report November")
    assert f.atc.ctr_stage == "out"
    sug = suggestion(f.atc)
    assert sug["text"].startswith("leave the control zone via November, 1500 feet or below, squawk 7000")
    assert f.say(TWR_A, sug["text"])[0] == "(readback correct)"


def readback_departure(f: Flight) -> None:
    ready(f)
    f.say(TWR_A, f"Leave the control zone via November, 1500 feet or below, squawk 7000, runway 27, cleared for "
                 f"takeoff, {SHORT}")


def test_e1_over_the_point_tower_lets_the_flight_go():
    f = Flight(ORIGIN, DEST)
    readback_departure(f)
    assert airborne_at(f, 0, 1, 800) == [] and f.atc.phase == "climb"
    assert airborne_at(f, 0, 4.5, 1400) == []
    assert airborne_at(f, 0, 5.5, 1400) == []  # 0.5 nm past: not yet
    assert airborne_at(f, 10, 6.5, 1400) == [f"{SHORT}, leaving the control zone, frequency change approved"]
    assert f.atc.ctr_stage is None and f.atc.phase == "enroute"
    [answer] = f.say(TWR_A, f"Tango Tower, {SHORT}, November")  # too late: ATC still answers
    assert answer.startswith(SHORT)


def test_e1_the_pilot_reports_the_point():
    f = Flight(ORIGIN, DEST)
    readback_departure(f)
    airborne_at(f, 0, 2, 1200)
    assert suggestion(f.atc)["text"] == f"Tango Tower, {SHORT}, November"
    assert f.say(TWR_A, f"Tango Tower, {SHORT}, November") == [
        f"{SHORT}, leaving the control zone, frequency change approved"]


def test_e1_too_high_in_the_zone_then_out_over_the_top():
    f = Flight(ORIGIN, DEST)
    readback_departure(f)
    airborne_at(f, 0, 1, 800)
    assert airborne_at(f, 0, 2, 1900) == [f"{SHORT}, check altitude, one thousand fife hundred feet or below"]
    assert airborne_at(f, 0, 2.5, 2000) == []  # said once
    assert airborne_at(f, 0, 3, 2600) == [f"{SHORT}, leaving the control zone, frequency change approved"]


FAR_POINT = replace(ORIGIN, vfr_points=(VfrPoint("NOVMR", *destination_point(ORIGIN.lat, ORIGIN.lon, 0, 10)),))


def test_e1_a_point_outside_the_zone_is_still_reported():
    # EDDH's Delta, Lubeck's Lima: 2 to 3 nm outside the zone, Tower let the flight go at the zone's edge (8 nm)
    f = Flight(FAR_POINT, DEST)
    readback_departure(f)
    airborne_at(f, 0, 1, 800)
    assert airborne_at(f, 0, 8.5, 1400) == [] and f.atc.ctr_stage == "out"  # out of the zone, November ahead
    assert suggestion(f.atc)["text"] == f"Tango Tower, {SHORT}, November"
    assert airborne_at(f, 0, 10, 1400) == []
    assert airborne_at(f, 5, 11, 1400) == [f"{SHORT}, leaving the control zone, frequency change approved"]


def test_e1_well_beyond_a_point_outside_the_zone_the_flight_is_let_go():
    f = Flight(FAR_POINT, DEST)
    readback_departure(f)
    airborne_at(f, 0, 1, 800)
    assert airborne_at(f, 90, 9, 1400) == []  # out to the east, 1 nm out of the zone
    assert airborne_at(f, 90, 12.5, 1400) == [f"{SHORT}, leaving the control zone, frequency change approved"]


def test_e1_not_before_the_readback():
    f = Flight(ORIGIN, DEST)
    ready(f)
    assert airborne_at(f, 0, 1, 800) == [] and airborne_at(f, 0, 9, 1400) == []
    assert f.atc.ctr_stage == "out"


def inbound(dest=DEST, brg=180, nm=12) -> Flight:
    f = Flight(ORIGIN, dest)
    f.atc.phase = "enroute"
    airborne_at(f, brg, nm, 2500, field=dest)
    return f


def test_e2_inbound_with_the_current_atis():
    f = inbound()
    letter = f.atc.dest_atis.letter
    sug = suggestion(f.atc)
    assert sug["station"] == "Uniform Tower" and sug["text"].endswith(f"for landing")
    [entry] = f.say(TWR_B, sug["text"])
    assert entry == f"{FULL}, Uniform Tower, enter the control zone via Sierra, one thousand fife hundred feet or " \
                    "below, report Sierra"
    assert parse(sug["text"], "DMABC").items["atis"] == letter.lower()
    assert f.atc.ctr_stage == "in" and f.atc.phase == "arrival"


def test_e2_inbound_without_the_atis_gets_runway_and_qnh():
    f = inbound()
    [entry] = f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    assert entry == f"{FULL}, Uniform Tower, enter the control zone via Sierra, one thousand fife hundred feet or " \
                    "below, runway zero niner, QNH one zero one niner, report Sierra"


def test_e2_from_the_point_into_the_circuit_and_down():
    f = inbound()
    f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    f.say(TWR_B, f"Enter the control zone via Sierra, 1500 feet or below, runway 09, QNH 1019, {SHORT}")
    assert airborne_at(f, 180, 6, 1400, field=DEST) == []
    assert suggestion(f.atc)["text"] == f"Uniform Tower, {SHORT}, overhead Sierra"
    assert f.say(TWR_B, f"Uniform Tower, {SHORT}, overhead Sierra") == [
        f"{SHORT}, join right downwind runway zero niner, report downwind"]
    assert f.atc.ctr_stage == "joining"
    assert f.say(TWR_B, f"join right downwind runway 09, {SHORT}")[0] == "(readback correct)"
    assert suggestion(f.atc)["text"] == f"Uniform Tower, {SHORT}, right downwind runway 09"
    assert f.say(TWR_B, f"Uniform Tower, {SHORT}, right downwind runway 09") == [f"{SHORT}, report final"]
    f.sim.circuit(DEST, DEST.runway_end("09"), "final")
    assert f.tick() == []  # "report final" was asked for: Tower waits for the call (EDHL emulator run)
    assert suggestion(f.atc)["text"] == f"Uniform Tower, {SHORT}, final runway 09"
    [landing] = f.say(TWR_B, f"Uniform Tower, {SHORT}, final runway 09")
    assert "runway zero niner, cleared to land" in landing and f.atc.phase == "landing"


def test_e2_without_the_final_call_tower_clears_on_short_final():
    f = inbound()
    f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    f.say(TWR_B, f"Enter the control zone via Sierra, 1500 feet or below, runway 09, QNH 1019, {SHORT}")
    f.say(TWR_B, f"Uniform Tower, {SHORT}, overhead Sierra")
    f.say(TWR_B, f"join right downwind runway 09, {SHORT}")
    f.say(TWR_B, f"Uniform Tower, {SHORT}, right downwind runway 09")
    f.sim.on_final(DEST, DEST.runway_end("09"), 2)
    assert f.tick() == []
    f.sim.on_final(DEST, DEST.runway_end("09"), 0.9)
    [landing] = f.tick()
    assert "runway zero niner, cleared to land" in landing and f.atc.phase == "landing"


def test_e2_turning_final_before_reporting_downwind_tower_clears():
    f = inbound()
    f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    f.say(TWR_B, f"Enter the control zone via Sierra, 1500 feet or below, runway 09, QNH 1019, {SHORT}")
    f.say(TWR_B, f"Uniform Tower, {SHORT}, overhead Sierra")
    f.say(TWR_B, f"join right downwind runway 09, {SHORT}")
    f.sim.circuit(DEST, DEST.runway_end("09"), "final")
    [landing] = f.tick()
    assert "runway zero niner, cleared to land" in landing


def test_e2_passing_the_point_tower_calls():
    f = inbound()
    f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    f.say(TWR_B, f"Enter the control zone via Sierra, 1500 feet or below, runway 09, QNH 1019, {SHORT}")
    assert airborne_at(f, 180, 5, 1400, field=DEST) == []
    assert airborne_at(f, 180, 4, 1400, field=DEST) == [
        f"{SHORT}, join right downwind runway zero niner, report downwind"]


def test_e2_too_high_inside_the_zone():
    f = inbound()
    f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    f.say(TWR_B, f"Enter the control zone via Sierra, 1500 feet or below, runway 09, QNH 1019, {SHORT}")
    assert airborne_at(f, 180, 7, 2200, field=DEST) == [
        f"{SHORT}, check altitude, one thousand fife hundred feet or below"]


def test_e2_without_points_straight_into_the_circuit():
    f = inbound(NO_POINTS)
    [entry] = f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    assert entry == f"{FULL}, Uniform Tower, enter the control zone from the south, one thousand fife hundred feet " \
                    "or below, QNH one zero one niner, join right downwind runway zero niner, report downwind"
    assert f.atc.ctr_stage == "joining"


def test_e2_other_calls_get_no_vectors():
    f = inbound()
    f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    f.say(TWR_B, f"Enter the control zone via Sierra, 1500 feet or below, runway 09, QNH 1019, {SHORT}")
    assert f.say(TWR_B, f"Uniform Tower, {SHORT}, request descent") == [f"{SHORT}, roger, report Sierra"]


def test_e2_go_around_rejoins_the_circuit():
    f = inbound()
    f.say(TWR_B, f"Uniform Tower, {FULL}, 12 miles south, 2500 feet, for landing")
    f.say(TWR_B, f"Enter the control zone via Sierra, 1500 feet or below, runway 09, QNH 1019, {SHORT}")
    f.say(TWR_B, f"Uniform Tower, {SHORT}, overhead Sierra")
    f.say(TWR_B, f"join right downwind runway 09, {SHORT}")
    f.sim.circuit(DEST, DEST.runway_end("09"), "downwind")
    assert f.tick() == []  # downwind passes the threshold: no go-around
    [response] = f.say(TWR_B, f"Uniform Tower, {SHORT}, going around")
    assert "join right downwind runway zero niner, report downwind" in response
    assert f.atc.ctr_stage == "joining"
