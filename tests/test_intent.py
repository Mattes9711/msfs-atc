"""Most inputs here are real whisper transcripts of the user's voice (recordings 001-008) and of the TTS test."""
import pytest

from atc.intent.normalize import tokenize
from atc.intent.parser import parse
from atc.intent.schema import Intent

ME = "DLH4AB"


@pytest.mark.parametrize("text, tokens", [
    ("climb flight level 1-2-0", ["climb", "flight", "level", "120"]),
    ("Climb flight level, one, two, zero", ["climb", "flight", "level", "120"]),
    ("contact departure 119 or decimal 875", ["contact", "departure", "119.875"]),
    ("Contact departure, one, one, niner, decimal, eight, seven, five", ["contact", "departure", "119.875"]),
    ("QNH101 Tree", ["qnh", "1013"]),
    ("climb 3,500 feet", ["climb", "3500", "feet"]),
    ("runway zero fife", ["runway", "05"]),
    ("cleared for take-off", ["cleared", "for", "takeoff"]),
    ("runway 23, 5000 feet, squawk 1234", ["runway", "23", "5000", "feet", "squawk", "1234"]),
    ("one one niner decimal eight", ["119.8"]),
    # A digit before "thousand" after a complete number starts a new one (found while testing the LLM fallback)
    ("heading zero eight zero, three thousand five hundred", ["heading", "080", "3", "thousand", "5", "hundred"]),
    ("climb one one thousand", ["climb", "11", "thousand"]),
])
def test_tokenize_normalises_numbers(text, tokens):
    assert tokenize(text) == tokens


@pytest.mark.parametrize("text, callsign", [
    ("Hammer ground, Lufthansa 4, Alpha, Bravo, request taxi.", "DLH4AB"),
    ("Going around, Lufthansa for Alpha, Bravo.", "DLH4AB"),  # "four" heard as "for"
    ("Hammer ground, DLH, 4AB, request taxi.", "DLH4AB"),
    ("DLH4 Alpha Bravo, runway 27, cleared for takeoff", "DLH4AB"),
    ("Hamburg Tower, Luftanz, Alpha, Bravo ready for departure.", None),  # no flight number at all
    ("Hammer ground, Luftanzar 4, Alpha, Bravo, request taxi.", "DLH4AB"),  # fuzzy airline name
    ("Going around, Luftanza for Alpha, Bravo.", "DLH4AB"),
    ("Hamburg Tower, Lufthansa 759, radio check", "DLH759"),
])
def test_callsign_is_recovered_from_whisper_errors(text, callsign):
    assert parse(text, ME).callsign == callsign


@pytest.mark.parametrize("text", [
    "Hamburg Tower, Lufthansa 4L for Bravo, ready for departure.",
    "Hammer, ground, Lufthansa, F4, Alpha, Bravo, request taxi.",
    "climb, flight level, 120, squawk, 4721, glh4ab.",
    "Humble ground, DLH4HB, request taxi.",
])
def test_slightly_misheard_callsign_still_counts_as_ours(text):
    assert parse(text, ME).addressed_to_us


def test_other_callsign_and_no_callsign_are_not_ours():
    assert not parse("Speedbird 12, request taxi", ME).addressed_to_us
    garbage = parse("I'm a ground love tons of forever Bravo request taxi", ME)
    assert garbage.callsign is None and not garbage.addressed_to_us


def test_phraseology_words_are_not_fuzzy_airline_names():
    intent = parse("reduce speed 180 knots, Lufthansa 4 alpha bravo", ME)
    assert intent.callsign == "DLH4AB" and intent.items == {"speed_kt": 180}
    assert parse("reduce speed 180 knots").callsign is None


def test_taxi_delta_is_not_mistaken_for_the_airline_delta():
    intent = parse("taxi via delta 1, Lufthansa 4 alpha bravo", ME)
    assert intent.callsign == "DLH4AB"
    assert intent.items["taxiways"] == ["D1"]


@pytest.mark.parametrize("text, kind", [
    ("Hammer ground, Lufthansa 4, Alpha, Bravo, request taxi.", "request_taxi"),
    ("Hamburg Delivery, Lufthansa 759, request IFR clearance to Munich with information Bravo", "request_clearance"),
    ("Hamburg Ground, Lufthansa 759, request push and start", "request_pushback"),
    ("Hamburg Tower, Lufthansa 4L for Bravo, ready for departure.", "ready_departure"),
    ("Going around, Lufthansa for Alpha, Bravo.", "going_around"),
    ("Hamburg Departure, Lufthansa 759, passing 2000 climbing flight level 70", "checkin"),
    ("Munich Tower, Lufthansa 4AB, established ILS 08R", "checkin"),
    ("Runway vacated, Lufthansa 759", "vacated"),
    ("Climb flight level, one, two, zero, squawk, four, seven, two, one, Lufthansa, four, Alpha, Bravo.", "readback"),
    ("Wilco, Lufthansa 759", "acknowledge"),
    ("Hamburg Tower, Lufthansa 759, radio check", "radio_check"),
    # Without "request" (found while testing the LLM fallback, step 24)
    ("Hamburg ground Lufthansa four alpha bravo we would like to get our IFR clearance please", "request_clearance"),
    ("Hamburg ground, good afternoon, Lufthansa four alpha bravo, ready to copy", "request_clearance"),
    ("we are on stand golf one and would like to start the engines, Lufthansa 4AB", "request_pushback"),
    ("can we have pushback please, Lufthansa 4AB", "request_pushback"),
    ("Lufthansa 4AB, we would like to taxi", "request_taxi"),
    ("could we get lower, Lufthansa 4AB", "request_descent"),
    ("Lufthansa 4AB, we are ready whenever you are at holding point two three", "ready_departure"),
    ("can we get a squawk please, Lufthansa 4AB", "request_other"),
    ("Lufthansa 759, say again", "say_again"),
    ("Munich Radar, Lufthansa 759, request descent", "request_descent"),
    ("bla bla", "unknown"),
])
def test_kind(text, kind):
    assert parse(text, ME).kind == kind


def test_full_readback_items():
    # TTS test sentence as transcribed by whisper
    intent = parse("DLH4 Alpha Bravo, runway 27, cleared for takeoff, wind 260 degrees 1-2 knots, climb flight level "
                   "1-2-0, squawk 4-7-2-1, contact departure 119 or decimal 875. QNH 101 Tree, information Bravo.", ME)
    assert intent.items == {
        "flight_level": 120, "squawk": "4721", "qnh": 1013, "atis": "b", "frequency_khz": 119875,
        "runway": "27", "cleared_takeoff": True,
    }


def test_altitudes_and_frequency_in_words():
    intent = parse("Lufthansa 4 Alpha Bravo, climb flight level 1-2-0, squawk 4-7-2-1, contact departure 1-2-6 "
                   "decimal 8-5-5, wind 2-6-0 degrees 1-2 knots, runway 2-3, QNH 1-0-1-3, climb 3,500 feet.", ME)
    assert intent.items["altitude_ft"] == 3500
    assert intent.items["frequency_khz"] == 126855
    assert intent.items["runway"] == "23"


@pytest.mark.parametrize("text, items", [
    ("Taxi to holding point, runway 23 via Alpha, Lufthansa 4, Alpha, Bravo.", {"runway": "23", "taxiways": ["A"]}),
    ("taxi to holding point runway 33 via alpha 1, zulu 5, hold short runway 23, DLH4AB",
     {"runway": "33", "taxiways": ["A1", "Z5"], "hold_short": "23"}),
    ("descend tree thousand fife hundred feet QNH 1013", {"altitude_ft": 3500, "qnh": 1013}),
    ("climb flight level one hundred", {"flight_level": 100}),
    ("turn left heading 2 4 0", {"heading": 240}),
    ("line up and wait runway 08 left", {"line_up": True, "runway": "08L"}),
    ("cleared to land runway 0 8 left", {"cleared_land": True, "runway": "08L"}),
    ("cleared ILS runway 08R", {"runway": "08R"}),
    ("hold short runway 26L", {"hold_short": "26L"}),
    ("reduce speed 180 knots", {"speed_kt": 180}),
    ("climb 5000", {"altitude_ft": 5000}),
    ("descending to 3000", {"altitude_ft": 3000}),
    ("heading zero eight zero, three thousand five hundred", {"heading": 80, "altitude_ft": 3500}),
    ("climb altitude one one thousand", {"altitude_ft": 11000}),
    ("we would like to get our IFR clearance please, we have information bravo", {"atis": "b"}),
])
def test_items(text, items):
    assert parse(text, ME).items == items


def test_out_of_band_frequency_is_ignored():
    assert "frequency_khz" not in parse("contact 1999.875", ME).items  # no digit dropped gives 118-136 MHz


def test_schema_rejects_unknown_kinds_and_items():
    with pytest.raises(ValueError):
        Intent("dance", None, False)
    with pytest.raises(ValueError):
        Intent("readback", None, False, {"squawk": 4721})  # must be text
    with pytest.raises(ValueError):
        Intent("readback", None, False, {"colour": "red"})
