"""The phrase catalogue (P1) must only promise what the parser understands: every pilot example is parsed."""
import re

import pytest

from atc.intent.parser import parse
from atc.intent.schema import ITEMS, KINDS
from atc.phraseology.catalog import EXAMPLE, GROUPS, PHRASES


@pytest.mark.parametrize("phrase", PHRASES, ids=lambda p: f"{p.group}: {p.title}")
def test_every_example_is_understood(phrase):
    intent = parse(phrase.text(), "DLH4AB")
    assert intent.addressed_to_us, phrase.text()
    assert intent.kind == phrase.kind, phrase.text()
    for key, value in phrase.items.items():
        assert intent.items.get(key) == value, f"{key} in {phrase.text()!r}: {intent.items}"


def test_the_catalogue_is_well_formed():
    assert len({(p.group, p.title) for p in PHRASES}) == len(PHRASES)  # no duplicates
    for p in PHRASES:
        assert p.group in GROUPS and p.kind in KINDS and set(p.items) <= set(ITEMS)
        assert set(re.findall(r"{(\w+)}", p.pilot)) <= set(EXAMPLE), p.title


def test_every_group_has_phrases():
    assert {p.group for p in PHRASES} == set(GROUPS)


def test_the_flight_fills_in_its_own_values():
    request = next(p for p in PHRASES if p.title == "Request IFR clearance")
    assert request.text({"station": "Munich Delivery", "destination": "Hamburg", "atis": "kilo"}) == \
        "Munich Delivery, Lufthansa 4AB, request IFR clearance to Hamburg, information kilo"
