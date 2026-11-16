"""The suggested next call (P2/A5) and the phrase book. The main test flies EDDH -> EDDM gate to gate saying only
what the app suggests: every suggestion must be understood and every readback must be correct."""
from atc.controller.suggest import phrase_book, readback_part, suggestion, written_callsign
from atc.controller import readback as rb
from tests.test_ground_flow import confirmed
from tests.test_air_flow import s_total
from tests.test_ground_flow import GROUND, Session


def say_suggestion(s, title=None):
    """Tune the controller the app shows, say the suggestion; returns (suggestion, what ATC answered)."""
    sug = suggestion(s.atc)
    assert sug is not None, f"no suggestion in phase {s.atc.phase}"
    if title:
        assert sug["title"] == title, sug
    return sug, s.say(sug["khz"], sug["text"])


def test_a_whole_flight_with_only_the_suggestions(eddh, eddm):
    s = Session(eddh, destination=eddm)
    s.sim.update(com1_khz=GROUND)
    s.tick()
    sug, out = say_suggestion(s, "Request IFR clearance")
    assert sug["text"] == "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alfa"
    assert out[0].startswith("Lufthansa four Alfa Bravo, cleared to Munich")
    sug, out = say_suggestion(s, "Read back")
    assert sug["text"] == f"runway 23, climb 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB"
    assert out == ["(readback correct)", "Lufthansa four Alfa Bravo, readback correct"]

    assert say_suggestion(s, "Request pushback")[1] == ["Lufthansa four Alfa Bravo, push and start approved, facing west"]
    assert say_suggestion(s, "Request taxi")[1][0].startswith("Lufthansa four Alfa Bravo, taxi to holding point")
    assert confirmed(say_suggestion(s, "Read back")[1])
    assert suggestion(s.atc) is None  # taxiing: nothing to say

    goal = s.atc.taxi.latlon[s.atc.route_out.edges[-1].b]
    s.sim.update(lat=goal[0], lon=goal[1])
    assert s.tick()[0].endswith("contact Hamburg Tower one two one decimal two eight zero")
    sug, out = say_suggestion(s, "Read back")
    assert confirmed(sug["text"] == "contact Hamburg Tower 121.280, Lufthansa 4AB" and out)
    sug, out = say_suggestion(s, "Ready for departure")
    assert out[0].endswith("cleared for takeoff")
    assert confirmed(say_suggestion(s, "Read back")[1])

    s.sim.fly(eddh, eddm, 2, 35000)
    assert s.tick()[0].endswith("contact Hamburg Approach one one eight decimal two zero fife")
    assert confirmed(say_suggestion(s, "Read back")[1])
    sug, out = say_suggestion(s, "Check in")
    assert sug["text"] == "Hamburg Approach, Lufthansa 4AB, passing 2000 feet, climbing 5000 feet"
    assert "radar contact" in out[0]
    assert confirmed(say_suggestion(s, "Read back")[1])
    assert suggestion(s.atc) is None  # cruising

    for nm in range(3, int(s_total(s))):
        s.sim.fly(eddh, eddm, nm, 35000)
        if s.tick():
            assert confirmed(say_suggestion(s, "Read back")[1])  # descent, handoffs
            if s.atc.phase == "arrival":
                break
    sug, out = say_suggestion(s, "Check in")
    assert sug["text"] == "Munich Approach, Lufthansa 4AB, descending flight level 100"
    assert "vectors ILS approach" in out[0]
    assert confirmed(say_suggestion(s, "Read back")[1])  # altitude, QNH, speed, heading
    assert suggestion(s.atc) is None  # flying the heading

    s.sim.on_final(eddm, eddm.runway_end(s.atc.arrival_runway), 10)
    assert s.tick()[0].endswith("speed one eight zero knots")  # cleared for the ILS
    out = say_suggestion(s, "Read back")[1]
    assert out[0] == "(readback correct)" and out[2].endswith("contact Munich Tower one one eight decimal seven zero fife")
    assert confirmed(say_suggestion(s, "Read back")[1])
    sug, out = say_suggestion(s, "Check in")
    assert out[0].endswith("cleared to land")
    assert confirmed(say_suggestion(s, "Read back")[1])

    s.sim.landed(eddm, eddm.runway_end(s.atc.arrival_runway))
    assert "contact Munich Ground" in s.tick()[0]
    assert confirmed(say_suggestion(s, "Read back")[1])
    sug, out = say_suggestion(s, "Request taxi")
    assert out[0].startswith("Lufthansa four Alfa Bravo, taxi to stand")
    assert say_suggestion(s, "Read back")[1] == ["(readback correct)", "Lufthansa four Alfa Bravo, readback correct", "(flight complete)"]
    assert suggestion(s.atc) is None


def test_readbacks_are_written_like_a_pilot_says_them():
    parts = [readback_part(i) for i in [*rb.taxi("23", ["A", "B"], "05"), rb.level(120, "descend"),
                                        rb.heading(230, "left"), rb.speed(180), rb.qnh(1018),
                                        rb.contact("Bremen Radar", 125100), *rb.cleared_land("08R")]]
    assert parts == ["taxi to holding point runway 23", "via A, B", "hold short runway 05", "descend flight level 120",
                     "turn left heading 230", "speed 180 knots", "QNH 1018", "contact Bremen Radar 125.100",
                     "runway 08R", "cleared to land"]
    assert written_callsign("DLH4AB") == "Lufthansa 4AB" and written_callsign("DEABC") == "DEABC"


def test_the_status_carries_the_suggestion(eddh):
    s = Session(eddh)
    s.sim.update(com1_khz=GROUND)
    s.tick()
    assert s.atc.status()["suggestion"]["title"] == "Request IFR clearance"


def test_the_phrase_book_has_the_flights_values_and_the_current_phase_first(eddh, eddm):
    s = Session(eddh, destination=eddm)
    book = phrase_book(s.atc)
    assert book[0]["group"] == "Clearance" and book[0]["current"]
    request = next(p for p in book[0]["phrases"] if p["title"] == "Request IFR clearance")
    assert request["pilot"] == "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information alfa"
    tower = next(g for g in book if g["group"] == "Tower")
    assert tower["phrases"][0]["pilot"].startswith("Hamburg Tower, Lufthansa 4AB, holding point runway 23")
