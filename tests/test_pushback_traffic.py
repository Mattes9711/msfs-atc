"""L3: no pushback into traffic taxiing behind the stand. LiveTraffic doesn't listen to ATC, so it goes first."""
from atc.airport.geo import destination_point
from tests.test_ground_flow import GROUND, TOWER, Session, confirmed
from tests.test_traffic_picture import plane

CS = "Lufthansa four Alfa Bravo"
HOLD = f"{CS}, hold position, traffic passing behind, I will call you"
APPROVED = f"{CS}, push and start approved, facing west"


def cleared(eddh, eddm, strict=False):
    s = Session(eddh, destination=eddm)
    s.atc.strict_readback = strict
    s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alpha")
    s.say(GROUND, f"cleared to Munich, Amluh 2G, runway 23, climb 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    return s


def taxiing_at(s, metres, bearing_from_nose, gs=12):
    """A taxiing aircraft that far from us, that many degrees off our nose (the fake sim parks us facing north)."""
    me = s.sim.read()
    heading_true = (me.heading_mag + s.atc.airport.mag_var) % 360
    lat, lon = destination_point(me.lat, me.lon, (heading_true + bearing_from_nose) % 360, metres / 1852)
    return plane(lat, lon, gs=gs, hdg=90)


def test_traffic_passing_behind_holds_the_push_until_it_has_passed(eddh, eddm):
    s = cleared(eddh, eddm)
    s.atc.update_traffic([taxiing_at(s, 60, 180)])
    assert s.say(GROUND, "Lufthansa 4AB, request push and start") == [HOLD]
    assert s.atc.phase == "cleared"
    s.atc.update_traffic([taxiing_at(s, 120, 150)])  # still behind
    assert s.tick() == []
    s.atc.update_traffic([taxiing_at(s, 400, 120)])  # gone by
    assert s.tick() == [APPROVED]
    assert s.atc.phase == "pushback" and s.tick() == []


def test_traffic_in_front_doesnt_hold_it(eddh, eddm):
    s = cleared(eddh, eddm)
    s.atc.update_traffic([taxiing_at(s, 60, 0)])  # ahead of the nose
    assert s.say(GROUND, "Lufthansa 4AB, request push and start") == [APPROVED]


def test_an_aircraft_standing_behind_on_the_taxilane_holds_it(eddh, eddm):
    s = cleared(eddh, eddm)  # B2: stopped behind us, not at a stand
    s.atc.update_traffic([taxiing_at(s, 60, 180, gs=0)])
    assert s.say(GROUND, "Lufthansa 4AB, request push and start") == [HOLD]


def test_asking_again_while_held_gets_the_same_answer(eddh, eddm):
    s = cleared(eddh, eddm)
    s.atc.update_traffic([taxiing_at(s, 60, 180)])
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    assert s.say(GROUND, "Lufthansa 4AB, request push and start") == [HOLD]


def test_the_approval_by_itself_must_be_read_back_with_strict_readbacks(eddh, eddm):
    s = cleared(eddh, eddm, strict=True)
    s.atc.update_traffic([taxiing_at(s, 60, 180)])
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    assert [i.key for i in s.atc.pending] == ["hold_position"]  # B1: holds are read back too
    assert confirmed(s.say(GROUND, "holding position, Lufthansa 4AB"))
    s.atc.update_traffic([])
    assert s.tick() == [APPROVED]
    assert [i.key for i in s.atc.pending] == ["pushback"]


def test_the_approval_by_itself_is_missed_on_another_frequency(eddh, eddm):
    s = cleared(eddh, eddm)
    s.atc.update_traffic([taxiing_at(s, 60, 180)])
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    s.sim.update(com1_khz=TOWER)  # tuned away while waiting
    s.atc.update_traffic([])
    [missed] = s.tick()
    assert missed.startswith("(Hamburg Ground is calling you")


def test_holding_position_is_an_acknowledgement(eddh, eddm):
    s = cleared(eddh, eddm)
    s.atc.update_traffic([taxiing_at(s, 60, 180)])
    s.say(GROUND, "Lufthansa 4AB, request push and start")
    assert s.say(GROUND, "holding position, Lufthansa 4AB") == []  # no "say again"
