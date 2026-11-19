"""Part I: the shipped German Center sectors from VATSIM data (atc/airspace/vatsim.py, data/centers_vatsim.json)."""
import json

from atc.airspace.centers import CenterSector, CenterSectors, load_centers
from atc.airspace.vatsim import LICENCE, STATIONS_LICENCE, build, stations, vatspy_firs
from atc.config import ROOT, Config
from atc.session import VATSIM_SOURCE, center_sectors, describe_centers

DAT = """[Countries]
Germany|ED|Radar
[FIRs]
; a comment
EDWW|Bremen Radar|EDWW|EDWW
EDWW-ALR|Bremen Radar (Aller)|EDWW_ALR|EDWW-ALR
EDGG-GIN|Langen Radar (Giessen)|EDGG_GIN|EDGG-GIN
EDGG-KL|Langen Radar|EDGG_KL|EDGG-KL
LOVV|Wien Radar|LOVV|LOVV
[UIRs]
EURM|Euro Middle|EDWW,EDGG
"""


def square(boundary, south, west, size):
    ring = [[west, south], [west + size, south], [west + size, south + size], [west, south + size], [west, south]]
    return {"type": "Feature", "properties": {"id": boundary}, "geometry": {"type": "MultiPolygon",
                                                                            "coordinates": [[ring]]}}


GEOJSON = {"features": [square("EDWW", 51, 6, 6), square("EDWW-ALR", 52, 9, 2), square("EDGG-GIN", 50, 8, 1),
                        square("EDGG-KL", 49, 7, 1), square("LOVV", 47, 13, 2)]}
POSITIONS = [
    {"logon": "EDWW_CTR", "frequency": "133.725", "description": "Bremen Radar (Complete)"},
    {"logon": "EDWW_ALR_CTR", "frequency": "126.325", "description": "Bremen Radar (Aller)"},
    {"logon": "EDGG_GIN_CTR", "frequency": "124.730", "description": "Langen Radar (Gießen)"},
    {"logon": "EDGG_GIH_CTR", "frequency": "128.075", "description": "Langen Radar (Gießen High)"},
]


def test_the_fir_lines_of_vatspy():
    assert vatspy_firs(DAT) == {"EDWW": "EDWW", "EDWW-ALR": "EDWW_ALR", "EDGG-GIN": "EDGG_GIN", "EDGG-KL": "EDGG_KL",
                                "LOVV": "LOVV"}


def test_each_sector_gets_its_datahub_frequency_and_none_is_made_up():
    sectors = build(DAT, GEOJSON, POSITIONS)
    found = [(s["note"], s["name"], s["fir"], s["frequency"], s["lower_ft"], s["upper_ft"]) for s in sectors]
    assert found == [  # the smallest first; EDGG-KL has no position and Wien is not in Germany: left out
        ("EDGG_GIN_CTR", "Langen Radar", "EDGG", "124.730", 0, 24500),
        ("EDGG_GIH_CTR", "Langen Radar", "EDGG", "128.075", 24500, 66000),  # the High position: the upper part
        ("EDWW_ALR_CTR", "Bremen Radar", "EDWW", "126.325", 0, 66000),
        ("EDWW_CTR", "Bremen Radar", "EDWW", "133.725", 0, 66000)]
    assert sectors[0]["polygon"][:2] == [[50, 8], [50, 9]]  # [lat, lon], not GeoJSON's [lon, lat]


def test_a_sector_wins_over_the_whole_fir_around_it(tmp_path):
    path = tmp_path / "centers_vatsim.json"
    path.write_text(json.dumps({"licence": LICENCE, "sectors": build(DAT, GEOJSON, POSITIONS)}), encoding="utf-8")
    centers = load_centers(path)
    assert centers.at(53.0, 10.0, 30000).khz == 126325  # Aller, inside Bremen
    assert centers.at(51.5, 7.0, 30000).khz == 133725  # the rest of Bremen
    assert [centers.at(50.5, 8.5, ft).khz for ft in (20000, 30000)] == [124730, 128075]  # Giessen, Giessen High


def test_the_shipped_file_covers_germany_with_real_frequencies():
    path = ROOT / "data" / "centers_vatsim.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "CC BY-SA 4.0" in raw["licence"] and "VATGER" in raw["licence"] and "VATSpy" in raw["licence"]
    centers = load_centers(path)
    assert not centers.placeholders and {s.name for s in centers.sectors} == {
        "Bremen Radar", "Langen Radar", "Munich Radar"}
    for lat, lon in [(53.63, 9.99), (52.4, 13.4), (51.0, 8.7), (49.5, 11.1), (48.35, 11.79)]:  # Hamburg ... Munich
        assert centers.at(lat, lon, 30000) is not None, (lat, lon)
    assert centers.at(48.2, 16.4, 30000) is None  # Vienna: no data outside Germany


def test_without_little_navmap_the_session_uses_them_and_corrections_still_win(tmp_path):
    own = tmp_path / "centers.json"
    own.write_text(json.dumps({"sectors": [
        {"name": "Hamburg Radar", "fir": "EDWW", "frequency": "123.450", "lower_ft": 0, "upper_ft": 66000,
         "polygon": [[53, 9], [53, 11], [54, 11], [54, 9]]},
        {"name": "Nobody Radar", "fir": "EDWW", "frequency": "PLACEHOLDER", "lower_ft": 0, "upper_ft": 66000,
         "polygon": [[52, 9], [52, 11], [53, 11], [53, 9]]}]}), encoding="utf-8")
    centers = center_sectors(Config(centers_file=own, littlenavmap_db=tmp_path / "missing.sqlite"))
    assert centers.source == f"{VATSIM_SOURCE} + centers.json"
    assert centers.at(53.5, 10.0, 30000).name == "Hamburg Radar"  # the correction
    assert centers.at(52.5, 10.0, 30000).name == "Bremen Radar"  # the placeholder is dropped
    assert "PLACEHOLDER" not in describe_centers(centers)


def test_no_placeholder_is_ever_shown():
    placeholder = CenterSector("Nobody Radar", "TST", None, 0, 66000, ((0, 0), (0, 1), (1, 1)))
    assert "PLACEHOLDER" not in describe_centers(CenterSectors([placeholder]))
    assert describe_centers(CenterSectors()) == "Center sectors: none, so Departure keeps you until Approach"


# --- the stations of the German airports (data/stations_vatsim.json) -------------------------------------------

STATION_POSITIONS = {
    "del": [{"logon": "EDDH_DEL", "frequency": "121.805", "description": "Hamburg Ground"}],
    "gnd": [{"logon": "EDDH_E_GND", "frequency": "121.705", "description": "Hamburg Apron (East)"},
            {"logon": "EDDM_1_GND", "frequency": "121.780", "description": "München Apron (Apron 1)"},
            {"logon": "EDDM_N_GND", "frequency": "121.980", "description": "München Ground (North)"},
            {"logon": "EDDM_I_GND", "frequency": "121.990", "description": "München DeIcing Coordinator"},
            {"logon": "EDDB_ICE_GND", "frequency": "121.665", "description": "Berlin De-Icing"},
            {"logon": "EDDC_A_GND", "frequency": "121.755", "description": ""}],
    "twr": [{"logon": "EDDH_TWR", "frequency": "126.855", "description": "Hamburg Tower"},
            {"logon": "EDDH_VFR_TWR", "frequency": "121.280", "description": "Hamburg VFR Tower"},
            {"logon": "EDDS_VFR_TWR", "frequency": "119.055", "description": "Stuttgart Tower (VFR)"}],
}


def test_each_position_gets_its_role_word_and_part_of_the_field():
    found = {ident: [(e["khz"], e["role"], e["word"], e["qualifier"]) for e in entries]
             for ident, entries in stations(STATION_POSITIONS).items()}
    assert found == {  # by frequency; de-icing and the one without a description are left out
        "EDDH": [(121280, "T", "Tower", "VFR"), (121705, "APRON", "Apron", "E"),
                 (121805, "C", "Ground", ""),  # Delivery, though it is called "Hamburg Ground"
                 (126855, "T", "Tower", "")],
        "EDDM": [(121780, "APRON", "Apron", "1"), (121980, "G", "Ground", "N")],
        "EDDS": [(119055, "T", "Tower", "VFR")],
    }


def test_the_shipped_stations_file_has_its_licence_and_hamburg():
    data = json.loads((ROOT / "data" / "stations_vatsim.json").read_text(encoding="utf-8"))
    assert data["licence"] == STATIONS_LICENCE and "CC BY-SA 4.0" in data["licence"]
    hamburg = {e["khz"]: e["role"] for e in data["airports"]["EDDH"]}
    assert hamburg[121805] == "C" and hamburg[121705] == hamburg[121980] == "APRON" and hamburg[126855] == "T"
    assert Config().vatsim_stations_file == ROOT / "data" / "stations_vatsim.json"
