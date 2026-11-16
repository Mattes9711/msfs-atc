"""Real airline callsigns: the ICAO designator from ADS-B (LiveTraffic) or the flight plan is said with its telephony
word ("DLH" = Lufthansa, "BAW" = Speedbird), digits and letters one by one."""
import re

import pytest

from atc.controller.traffic import spoken_callsign
from atc.intent.normalize import PHONETIC
from atc.intent.parser import parse
from atc.phraseology import spoken
from atc.phraseology.airlines import TELEPHONY
from atc.phraseology.catalog import PHRASES
from atc.sim.traffic import Traffic


def test_the_list_is_clean():
    assert all(re.fullmatch(r"[A-Z]{3}", code) for code in TELEPHONY)
    names = [n.lower() for n in TELEPHONY.values()]
    assert len(names) == len(set(names))  # one word, one airline: the parser maps it back
    assert len(TELEPHONY) >= 120


def test_no_telephony_word_is_a_phraseology_word():
    """A pilot's "contact", "runway" or "approach" next to a number must never read as an airline."""
    words = set(PHONETIC) | {w for p in PHRASES for text in (p.pilot, p.atc, p.note)
                             for w in re.findall(r"[a-z]+", text.lower())}
    clash = {n for n in (n.lower() for n in TELEPHONY.values()) if " " not in n and n in words}
    assert clash <= {"delta", "lufthansa"}  # Delta is also a taxiway; the parser picks by our own callsign


@pytest.mark.parametrize("adsb, said", [
    ("DLH1AL", "Lufthansa one Alfa Lima"),
    ("EJU93KF", "Alpine niner tree Kilo Foxtrot"),
    ("BAW12", "Speedbird one two"),
    ("RYR8LP", "Ryanair eight Lima Papa"),
    ("UAE4LK", "Emirates four Lima Kilo"),
    ("TOM5XY", "Tomson fife X-ray Yankee"),
    ("LOT3AB", "Pollot tree Alfa Bravo"),
    ("DLH400", "Lufthansa four zero zero"),
    ("XYZ12", "X-ray Yankee Zulu one two"),  # unknown airline: spelled
    ("DEABC", "Delta Echo Alfa Bravo Charlie"),  # a registration
])
def test_adsb_callsigns_are_said_with_the_telephony(adsb, said):
    assert spoken.callsign(adsb) == said
    t = Traffic(1, 0.0, 0.0, 0.0, 0.0, 0.0, True, adsb, "", "", "A320")  # LiveTraffic: no airline, no number
    assert spoken_callsign(t) == said


@pytest.mark.parametrize("text, expected", [
    ("Munich Ground, Air Canada 123, request taxi", "ACA123"),
    ("Hamburg Tower, Wizz Air 4 alpha bravo, ready for departure", "WZZ4AB"),
    ("Hamburg Ground, Pollot 3 alpha bravo, request taxi", "LOT3AB"),
])
def test_pilots_flying_other_airlines_are_understood(text, expected):
    assert parse(text, expected).callsign == expected


def test_a_misheard_word_is_only_ever_our_own_airline():
    assert parse("Hamburg Ground, Ryanaire 12, request taxi", "DLH4AB").callsign != "RYR12"
    assert parse("Hamburg Ground, Ryanaire 12, request taxi", "RYR12").callsign == "RYR12"
