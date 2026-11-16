"""Which Little Navmap database: the setting, else the one of the MSFS that runs (2020 or 2024)."""
import os
from pathlib import Path

from atc.airport import lnm_files


def databases(tmp_path, *names):
    for i, name in enumerate(names):
        f = tmp_path / name
        f.write_bytes(b"")
        os.utime(f, (1000 + i, 1000 + i))  # in the order given: the last one was loaded last
    return tmp_path


def test_the_msfs_databases_are_told_apart(tmp_path):
    where = databases(tmp_path, "little_navmap_msfs.sqlite", "little_navmap_msfs24.sqlite",
                      "little_navmap_navigraph.sqlite", "little_navmap_userdata.sqlite", "little_navmap_.sqlite",
                      "little_navmap_xp12.sqlite")
    assert lnm_files.scenery_databases(where) == {"2020": where / "little_navmap_msfs.sqlite",
                                                   "2024": where / "little_navmap_msfs24.sqlite"}


def test_the_running_sim_decides(tmp_path):
    where = databases(tmp_path, "little_navmap_msfs24.sqlite", "little_navmap_msfs.sqlite")
    assert lnm_files.find(Path(), where, sim=lambda: "2024") == where / "little_navmap_msfs24.sqlite"
    assert lnm_files.find(Path(), where, sim=lambda: "2020") == where / "little_navmap_msfs.sqlite"
    assert lnm_files.find(Path(), where, sim=lambda: None) == where / "little_navmap_msfs.sqlite"  # loaded last


def test_only_2024_needs_no_choice(tmp_path):
    where = databases(tmp_path, "little_navmap_msfs2024.sqlite")
    asked = []
    assert lnm_files.find(Path(), where, sim=lambda: asked.append(1)) == where / "little_navmap_msfs2024.sqlite"
    assert asked == []  # nothing to choose: the processes are not looked at
    assert lnm_files.find(Path(), tmp_path / "empty") is None


def test_the_setting_wins(tmp_path):
    where = databases(tmp_path, "little_navmap_msfs.sqlite")
    own = tmp_path / "mine.sqlite"
    own.write_bytes(b"")
    assert lnm_files.find(own, where) == own
    assert lnm_files.find(tmp_path / "missing.sqlite", where) is None  # set, but not there: not another one


def test_the_running_sim_from_the_processes():
    assert lnm_files.running_sim(lambda: {"explorer.exe", "flightsimulator2024.exe"}) == "2024"
    assert lnm_files.running_sim(lambda: {"flightsimulator.exe"}) == "2020"
    assert lnm_files.running_sim(lambda: {"explorer.exe"}) is None


def test_the_banner_says_which_scenery():
    assert lnm_files.describe(Path("little_navmap_msfs24.sqlite")) == "Little Navmap (MSFS 2024)"
    assert lnm_files.describe(Path("little_navmap_msfs.sqlite")) == "Little Navmap (MSFS 2020)"
