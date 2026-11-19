"""Scenery taxiway names as ATC says them (the emulator at EDDF, 2026-11-19: "N-South" was spelled letter by letter
and the co-pilot's readback refused five times)."""
import pytest

from atc.airport.taxi import radio_name


@pytest.mark.parametrize("scenery, spoken", [
    ("N", "N"), ("N5", "N5"), ("b12w", "B12W"),
    ("N-South", "N"), ("L-NORTH", "L"), ("T-2", "T2"),
    ("E3BLUE", "E3"), ("D2SSS", "D2"), ("Z3.1", "Z3"), ("L16AW", "L16"),
    ("LINK 4", ""), ("SWINGOVR", ""), ("PARKING", ""), ("CENTER2", ""), ("VC", ""), ("EXIT-1", ""), ("", ""),
])
def test_radio_name(scenery, spoken):
    assert radio_name(scenery) == spoken
