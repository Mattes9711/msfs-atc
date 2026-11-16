def test_eddh_loads_from_json(eddh):
    assert eddh.name == "Hamburg"
    assert sorted(end.name for rwy in eddh.runways for end in rwy.ends) == ["05", "15", "23", "33"]


def test_frequencies_are_khz_and_named_like_icao_stations(eddh):
    assert eddh.frequency_at(126855).station == "Hamburg Tower"
    assert eddh.frequency_at(121705).station == "Hamburg Ground"
    assert eddh.frequency_at(124325).station is None  # ATIS is not a controller


def test_ils_is_attached_to_its_runway_end(eddh):
    ends = {end.name: end for rwy in eddh.runways for end in rwy.ends}
    assert ends["23"].ils.ident == "IHHW"
    assert ends["33"].ils is None
