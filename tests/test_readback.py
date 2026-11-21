import pytest

from atc.controller import readback as rb
from atc.intent.parser import parse


def check(issued, said):
    return rb.check_readback(issued, parse(said, "DLH4AB").items)


# Real whisper transcripts of the user's readbacks (recordings 002, 005, 006)
@pytest.mark.parametrize("issued, said", [
    (rb.taxi("23", ["A"]), "Taxi to holding point, runway 23 via Alpha, Lufthansa 4, Alpha, Bravo."),
    ([rb.level(120), rb.squawk("4721")],
     "Climb flight, level, one, two, zero, squawk, four, seven, two, one, Lufthansa, four, Alpha, Bravo."),
    ([rb.contact("Hamburg Departure", 119875)],
     "Contact departure, one, one, niner, decimal, eight, seven, five, Lufthansa four, Alpha, Bravo."),
])
def test_real_readbacks_are_accepted(issued, said):
    result = check(issued, said)
    assert result.ok and result.correction is None


def test_wording_does_not_matter_only_values():
    assert check([rb.level(120)], "up to one two zero on the level, Lufthansa 4AB").missing  # no "flight level"
    assert check([rb.level(120)], "FL120, Lufthansa 4AB").ok
    assert check([rb.altitude(5000)], "climb 5000, Lufthansa 4AB").ok
    assert check([rb.altitude(5000)], "climbing to fife thousand feet, Lufthansa 4AB").ok


def test_wrong_value_is_corrected_with_the_original_instruction():
    result = check([rb.level(120), rb.squawk("4721")], "climb flight level 140 squawk 4721, Lufthansa 4AB")
    assert [i.key for i in result.wrong] == ["flight_level"]
    assert result.correction == "negative, I say again, climb flight level one two zero"


def test_missing_item_is_requested():
    result = check([rb.level(120), rb.squawk("4721")], "climb flight level 120, Lufthansa 4AB")
    assert result.correction == "read back squawk"


def test_three_missing_items_are_listed_naturally():
    issued = [rb.Item("runway", "23", "runway two tree"), rb.altitude(5000), rb.squawk("4721")]
    assert check(issued, "roger, Lufthansa 4AB").correction == "read back runway, altitude and squawk"


def test_wilco_is_not_a_readback():
    assert check([rb.level(120), rb.squawk("4721")], "wilco, Lufthansa 4AB").correction == \
        "read back level and squawk"


def test_wrong_and_missing_together():
    result = check([rb.heading(240, "left"), rb.qnh(1013)], "left heading 250, Lufthansa 4AB")
    assert result.correction == "negative, I say again, turn left heading two four zero, read back QNH"


def test_hold_short_must_be_read_back():
    issued = rb.taxi("33", ["A1", "Z5"], hold_short="23")
    assert check(issued, "taxi holding point runway 33 via alpha 1 zulu 5, Lufthansa 4AB").correction == \
        "read back hold short"
    assert check(issued, "runway 33 via alpha 1, zulu 5, hold short runway 23, Lufthansa 4AB").ok


def test_taxi_route_must_match():
    result = check(rb.taxi("23", ["A", "B"]), "taxi to holding point runway 23 via alpha, Lufthansa 4AB")
    assert result.correction == "negative, I say again, via Alfa, Bravo"


def test_takeoff_clearance_with_wrong_runway():
    issued = rb.cleared_takeoff("23")
    assert check(issued, "runway 23 cleared for takeoff, Lufthansa 4AB").ok
    assert check(issued, "cleared for takeoff runway 33, Lufthansa 4AB").correction == \
        "negative, I say again, runway two tree"
    assert check(issued, "runway 23, Lufthansa 4AB").correction == "read back takeoff clearance"


def test_extra_items_in_the_readback_are_ignored():
    assert check([rb.squawk("4721")], "squawk 4721, QNH 1013, Lufthansa 4AB").ok


def test_builders_speak_icao():
    assert rb.instruction_text([rb.heading(5, "right"), rb.altitude(3500, "descend"), rb.speed(180)]) == \
        "turn right heading zero zero fife, descend altitude tree thousand fife hundred feet, " \
        "speed one eight zero knots"
    assert rb.instruction_text(rb.taxi("23", ["A1"], "15")) == \
        "taxi to holding point runway two tree, via Alfa one, hold short runway one fife"
    assert rb.contact("Hamburg Departure", 126855).phrase == \
        "contact Hamburg Departure one two six decimal eight fife fife"


def test_items_are_validated():
    with pytest.raises(ValueError):
        rb.Item("atis", "b", "information bravo")  # not a readback item
    with pytest.raises(ValueError):
        rb.Item("squawk", 4721, "squawk four seven two one")  # squawk is text


def test_the_named_holding_point_must_be_read_back():
    # EDHL: "taxi to holding point Bravo one runway 33" read back as "taxi to holding point runway 33" was accepted
    issued = rb.taxi("33", ["A"], holding_point="B1")
    assert rb.instruction_text(issued) == "taxi to holding point Bravo one runway tree tree, via Alfa"
    assert check(issued, "taxi to holding point runway 33 via alpha, Lufthansa 4AB").correction == \
        "read back holding point"
    assert check(issued, "taxi to holding point bravo 1 runway 33 via alpha, Lufthansa 4AB").ok
    assert check(issued, "holding point B1, runway 33, via A, Lufthansa 4AB").ok
    assert check(issued, "runway 33 via alpha, bravo 1, Lufthansa 4AB").ok  # named as the last taxiway
    assert check(issued, "taxi to holding point delta 1 runway 33 via alpha, Lufthansa 4AB").correction == \
        "negative, I say again, taxi to holding point Bravo one runway tree tree"
    assert check(rb.taxi("33", ["A"]), "taxi to holding point runway 33 via alpha, Lufthansa 4AB").ok


def test_the_named_holding_point_in_the_pilots_words():
    from atc.controller.suggest import readback_part
    parts = [readback_part(i) for i in rb.taxi("33", ["A"], holding_point="B1")]
    assert parts == ["taxi to holding point B1", "runway 33", "via A"]
    assert parse(", ".join(parts), "DLH4AB").items == {"holding_point": "B1", "runway": "33", "taxiways": ["A"]}
