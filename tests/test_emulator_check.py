"""The emulator log checklist (atc/emulator_check.py): each point with a made-up log that hits it."""
from atc.emulator_check import altitude_ft, check, frequency, main

CS = "Lufthansa four Alfa Bravo"
HEADER = """# EMU Weather: METAR EDDM 191950Z 26012KT 9999 FEW030 08/02 Q1018
# EMU Runway in use: 26L (wind 260/12)
# EMU Destination: EDDH, METAR EDDH 191950Z 23008KT CAVOK 06/01 Q1021, landing runway 23
# EMU Frequencies: Munich Ground 121.730, 121.780 | Hamburg Tower 118.105"""
REPORT = """DLH4AB EDDM-EDDH: finished after 1:06:38, 0 finding(s)
Phases:
  0:00:00  parked
  1:06:38  end
Measured:
  10 nm from the threshold: 3200 ft above the field (3 degrees: 3180), on the localizer, phase approach
  5 nm from the threshold: 1600 ft above the field (3 degrees: 1590), on the localizer, phase landing
Findings: none"""


def pos(nm=40, alt=5000, hdg=230, phase="approach", gs=220):
    where = "on the ground" if alt is None else f"{alt} ft"
    return f"POS 53.1000N 010.0000E, {where}, GS {gs} kt, HDG {hdg:03d}, {phase}, cleared 5000 FT, {nm} nm to EDDH"


def log(*radio, header=HEADER, report=REPORT):
    return "\n".join([header, report, "", "Radio:", *radio]) + "\n"


def keys(text):
    return [key for key, _ in check(text)]


def test_a_clean_log_has_no_hits():
    assert check(log(
        f"  0:00:10  atc  {CS}, cleared to Hamburg, Gipol six Sierra departure, squawk tree fife two zero",
        "  0:00:15  copilot  cleared to Hamburg, Gipol 6S departure, squawk 3520, Lufthansa 4AB",
        "  0:50:00  " + pos(nm=30, alt=9000, hdg=320),
        f"  0:50:01  atc  {CS}, turn left heading two niner zero, descend altitude fife thousand feet",
        "  0:50:05  copilot  left heading 290, descend 5000 feet, Lufthansa 4AB",
        f"  0:52:00  atc  {CS}, contact Hamburg Tower one one eight decimal one zero fife",
        "  0:52:03  copilot  contact Hamburg Tower 118.105, Lufthansa 4AB",
        "  0:52:10  copilot  Hamburg Tower, Lufthansa 4AB, ILS runway 23",
    )) == []


def test_k1_not_finished_or_findings():
    report = REPORT.replace("finished after", "NOT finished after").replace("0 finding(s)", "1 finding(s)")
    assert keys(log(report=report)) == ["K1"]
    assert keys(log(report=REPORT.replace("0 finding(s)", "2 finding(s)"))) == ["K1"]


def test_k2_atc_complains():
    assert keys(log(f"  0:10:00  atc  {CS}, negative, I say again, via November fife")) == ["K2"]


def test_k3_a_tailwind_runway():
    header = HEADER.replace("26012KT", "08012KT")
    assert [what for key, what in check(log(header=header))] == ["departure runway 26, wind 080/12: 12 kt tailwind"]
    assert keys(log(header=HEADER.replace("26012KT", "08004KT"))) == []  # 4 kt from behind is fine


def test_k4_the_clearance_limit_missing_from_the_readback():
    assert keys(log(f"  0:00:10  atc  {CS}, cleared to Hamburg, Gipol six Sierra departure, squawk tree fife two zero",
                    "  0:00:15  copilot  Gipol 6S departure, squawk 3520, Lufthansa 4AB")) == ["K4"]


def test_k5_the_next_call_to_another_station():
    assert keys(log(f"  0:52:00  atc  {CS}, contact Hamburg Tower one one eight decimal one zero fife",
                    "  0:52:03  copilot  contact Hamburg Tower 118.105, Lufthansa 4AB",
                    "  0:52:10  copilot  Bremen Radar, Lufthansa 4AB, 5000 feet")) == ["K5"]


def test_k6_a_frequency_not_in_the_list():
    assert keys(log(f"  0:52:00  atc  {CS}, contact Hamburg Tower one two zero decimal tree zero zero",
                    "  0:52:03  copilot  contact Hamburg Tower 120.300, Lufthansa 4AB")) == ["K6"]


def test_k7_numerals_in_an_atc_line():
    assert keys(log(f"  0:10:00  atc  {CS}, contact Berlin D01-D03 Apron")) == ["K7"]


def test_k8_climb_down_and_descend_up():
    assert keys(log("  0:50:00  " + pos(alt=9000), f"  0:50:01  atc  {CS}, climb altitude fife thousand feet")) == ["K8"]
    assert keys(log("  0:50:00  " + pos(alt=9000), f"  0:50:01  atc  {CS}, descend flight level one two zero")) == [
        "K8"]
    assert keys(log("  0:50:00  " + pos(alt=9000), f"  0:50:01  atc  {CS}, descend altitude fife thousand feet")) == []


def test_k9_two_headings_close_together_and_the_wrong_turn():
    assert keys(log(f"  0:50:00  atc  {CS}, turn left heading two niner zero",
                    "  0:50:04  atc  readback correct",
                    f"  0:50:20  atc  {CS}, turn left heading two six zero")) == ["K9"]
    assert keys(log("  0:50:00  " + pos(hdg=320), f"  0:50:01  atc  {CS}, turn left heading zero tree zero")) == ["K9"]
    assert keys(log("  0:50:00  " + pos(hdg=320), f"  0:50:01  atc  {CS}, turn right heading zero tree zero")) == []


def test_k10_an_intercept_far_off_the_runway():
    hit = f"  0:58:00  atc  {CS}, turn left heading one fife zero, maintain tree thousand feet until established"
    assert keys(log(hit)) == ["K10"]
    assert keys(log(hit.replace("one fife zero", "two zero zero"))) == []  # 30 degrees off runway 23


def test_k11_and_k12_late_landing_clearance_and_tower_handoff():
    assert keys(log("  1:00:00  " + pos(nm=1, alt=700, phase="final"),
                    f"  1:00:01  atc  {CS}, wind two tree zero degrees eight knots, runway two tree, cleared to land")
                ) == ["K11"]
    assert keys(log("  0:58:00  " + pos(nm=4, alt=1500, phase="final"),
                    f"  0:58:01  atc  {CS}, contact Hamburg Tower one one eight decimal one zero fife")) == ["K12"]


def test_k13_the_stand_missing_from_the_taxi_in_readback():
    assert keys(log(f"  1:03:00  atc  {CS}, taxi to stand Alfa one two via November",
                    "  1:03:04  copilot  via N, Lufthansa 4AB")) == ["K13"]


def test_k14_flight_complete_before_the_stand():
    assert keys(log("  1:04:00  notice  flight complete")) == ["K14"]  # the end at 1:06:38


def test_k15_standing_on_the_ground_without_a_call():
    assert keys(log(f"  0:05:00  atc  {CS}, hold position",
                    "  0:05:30  " + pos(nm=300, alt=None, phase="taxi_out", gs=0),
                    "  0:07:30  " + pos(nm=300, alt=None, phase="taxi_out", gs=0),
                    "  0:08:00  copilot  Munich Ground, Lufthansa 4AB, ready for taxi")) == ["K15"]


def test_k16_back_to_a_sector_already_flown():
    sector = f"  {{}}  atc  {CS}, contact {{}} one two six decimal fife fife zero"
    assert keys(log(sector.format("0:20:00", "Munich Radar"), sector.format("0:30:00", "Langen Radar"),
                    sector.format("0:40:00", "Munich Radar"))) == ["K16"]


def test_k17_off_the_glide_path():
    assert keys(log(report=REPORT.replace("3200 ft", "3800 ft"))) == ["K17"]
    assert keys(log(report=REPORT.replace("1600 ft", "1300 ft"))) == ["K17"]


def test_spoken_altitudes_and_frequencies():
    assert altitude_ft("flight level one two zero, ...") == 12000
    assert altitude_ft("altitude four thousand two hundred feet") == 4200
    assert altitude_ft("altitude one zero thousand feet") == 10000
    assert frequency("one two one decimal seven fife") == "121.750"


def test_main_counts_the_hits_per_point(tmp_path, capsys):
    (tmp_path / "a_EMU.txt").write_text(log(f"  0:10:00  atc  {CS}, negative"), encoding="utf-8")
    (tmp_path / "b_EMU.txt").write_text(log(), encoding="utf-8")
    assert main([str(tmp_path / "a_EMU.txt"), str(tmp_path / "b_EMU.txt")]) == 1
    out = capsys.readouterr().out
    assert out.startswith("2 log(s), 1 hit(s)") and "K2: 1\n  a: " in out
