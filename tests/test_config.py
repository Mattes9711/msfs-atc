import pytest

from atc.config import Config, ConfigError, load_config


def test_explicit_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_partial_file_keeps_other_defaults(tmp_path):
    path = tmp_path / "atc.toml"
    path.write_text('simbrief_username = "pilot"\n[whisper]\nmic = 3\n', encoding="utf-8")
    config = load_config(path)
    assert config.simbrief_username == "pilot"
    assert config.whisper.mic == 3
    assert config.whisper.model == Config().whisper.model


def test_relative_paths_are_relative_to_the_config_file(tmp_path):
    path = tmp_path / "atc.toml"
    path.write_text('airports_dir = "airports"\n', encoding="utf-8")
    assert load_config(path).airports_dir == tmp_path / "airports"


def test_typos_are_reported(tmp_path):
    path = tmp_path / "atc.toml"
    path.write_text("[whisper]\nmodle = 'base.en'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="modle"):
        load_config(path)
