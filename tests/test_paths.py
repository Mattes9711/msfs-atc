"""Where the app reads and writes (atc/paths.py): user folders in app-data, resources next to the code or in a build."""
import sys

from atc import paths
from atc.config import load_config


def test_user_folders_follow_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("MSFS_ATC_HOME")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.settings_file() == tmp_path / "Roaming" / "MSFS ATC" / "settings.toml"
    assert paths.cache_dir("metar") == tmp_path / "Local" / "MSFS ATC" / "cache" / "metar"
    assert paths.models_dir() == tmp_path / "Local" / "MSFS ATC" / "models"
    assert paths.logs_dir().parent == paths.recordings_dir().parent == tmp_path / "Local" / "MSFS ATC"


def test_one_variable_moves_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("MSFS_ATC_HOME", str(tmp_path / "portable"))
    assert paths.config_dir() == paths.data_dir() == tmp_path / "portable"


def test_resources_next_to_the_code_or_in_the_build(monkeypatch, tmp_path):
    assert (paths.resources() / "atc" / "app" / "static" / "index.html").is_file()
    assert (paths.resources() / "data" / "centers.json").is_file()
    assert (paths.resources() / "data" / "centers_vatsim.json").is_file()
    assert (paths.resources() / "data" / "stations_vatsim.json").is_file()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "build"), raising=False)
    assert paths.resources() == tmp_path / "build"


def test_settings_come_from_the_app_data_folder():
    assert load_config().simbrief_username is None  # no file yet: defaults
    paths.settings_file().parent.mkdir(parents=True)
    paths.settings_file().write_text('simbrief_username = "pilot"\n', encoding="utf-8")
    assert load_config().simbrief_username == "pilot"


def test_no_absolute_paths_in_the_code():
    for source in (paths.resources() / "atc").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "C:\\Users" not in text and "C:/Users" not in text, source
