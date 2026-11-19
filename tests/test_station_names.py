"""Station names as Little Navmap has them for EDDB (the emulator, 2026-11-19): place, job and part of the field in
one word, so ATC said "contact Berlingroundmaina,D01-D03 Ground". The place is what comes before the job."""
import pytest

from atc.airport.littlenavmap import _station_name
from atc.airport.model import Frequency


@pytest.mark.parametrize("kind, com_name, role, spoken", [
    ("G", "BERLINGROUNDMAINA,D01-D03", "G", "Berlin Ground"),
    ("G", "BERLINAPRONMAINB,C,D(EXCD01-D03)", "APRON", "Berlin Apron"),
    ("G", "BERLINGROUNDMAINAPRONE", "APRON", "Berlin Apron"),
    ("T", "BERLINTOWERPL-S", "T", "Berlin Tower"),
    ("A", "BERLINDIRECTOR", "A", "Berlin Approach"),
    ("G", "MUNICHAPRON1", "APRON", "Munich Apron"),
    ("T", "HAMBURG", "T", "Hamburg Tower"),
    ("ATIS", "EDDB", "ATIS", None),
])
def test_the_place_comes_before_the_job(kind, com_name, role, spoken):
    f = Frequency(kind, _station_name(com_name, "EDDB", "Berlin Brandenburg"), 121705)
    assert (f.role, f.station) == (role, spoken)
