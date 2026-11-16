"""Every correct readback is confirmed aloud; a handoff gets the controller's goodbye in the country's language."""
from atc.phraseology.farewell import BY_COUNTRY, farewell, spoken_in_own_language
from tests.test_air_flow import HAMBURG_APPROACH, cleared_for_takeoff
from tests.test_centers import fly
from tests.test_ground_flow import GROUND, TOWER, Session

CS = "Lufthansa four Alfa Bravo"


def test_the_goodbye_depends_on_the_country():
    assert farewell("EDDH", "Hamburg Tower") in BY_COUNTRY["ED"][1]
    assert farewell("LOWW", "Wien Tower") in ("servus", "baba, schönen Tag")
    assert farewell("LFPG", "De Gaulle Tower") in ("au revoir", "bonne journée")
    assert farewell("KJFK", "Kennedy Tower") in ("good day", "goodbye")  # elsewhere: English
    assert farewell("EDWW/Bremen Radar/125100", "Bremen Radar") in BY_COUNTRY["ED"][1]  # a Center: its FIR


def test_each_controller_always_says_it_the_same_way():
    assert len({farewell("EDDH", "Hamburg Tower") for _ in range(5)}) == 1


def airborne_handed_to_approach(eddh, eddm):
    s = cleared_for_takeoff(eddh, eddm)
    fly(s, 2)  # Tower: "contact Hamburg Approach"
    return s


def test_a_handoff_readback_gets_the_goodbye(eddh, eddm):
    s = airborne_handed_to_approach(eddh, eddm)
    assert s.say(TOWER, "contact Approach 118.205, Lufthansa 4AB") == [
        "(readback correct)", farewell("EDDH", "Hamburg Tower")]


def test_no_goodbye_from_a_controller_the_pilot_has_left(eddh, eddm):
    s = airborne_handed_to_approach(eddh, eddm)
    s.sim.update(com1_khz=HAMBURG_APPROACH)
    out = s.say(HAMBURG_APPROACH, "contact Approach 118.205, Lufthansa 4AB")  # read back on the new frequency
    assert farewell("EDDH", "Hamburg Tower") not in out


def test_any_other_readback_is_confirmed(eddh):
    s = Session(eddh)
    s.sim.update(com1_khz=GROUND)
    s.tick()
    s.say(GROUND, "Hamburg Ground, Lufthansa 4AB, request IFR clearance to Munich, information Alfa")
    out = s.say(GROUND, f"cleared to Munich, runway 23, 5000 feet, squawk {s.atc.squawk}, Lufthansa 4AB")
    assert out[-2:] == ["(readback correct)", f"{CS}, readback correct"]


def test_the_voice_says_foreign_goodbyes_in_their_own_sounds():
    def ipa(lang, text):
        return f"<{lang}:{text}>"
    assert spoken_in_own_language("tschüss, gute Reise", ipa) == "[[ <de:tschüss, gute Reise> ]]"  # longest first
    assert spoken_in_own_language("Tschüss", ipa) == "[[ <de:tschüss> ]]"
    assert spoken_in_own_language("good day", ipa) == "good day"  # English stays text
    assert spoken_in_own_language("Lufthansa four Alfa Bravo, readback correct", ipa) == (
        "Lufthansa four Alfa Bravo, readback correct")
