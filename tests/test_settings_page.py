"""R4: the Settings page: checking values, writing settings.toml, reading it back, the API."""
import json
from pathlib import Path

import pytest

from atc import settings_file
from atc.config import Config, ConfigError, load_config
from tests.test_app import get, post, server  # noqa: F401 (the server fixture)


def test_saved_settings_read_back_the_same(tmp_path):
    path = tmp_path / "settings.toml"
    config = settings_file.apply(Config(), {
        "simbrief_username": " pilot42 ", "tts.engine": "sapi", "tts.rate": "190", "tts.radio_effect": False,
        "whisper.mic": "3", "whisper.ptt_key": "caps lock", "traffic.chatter": False,
        "simconnect_dll": "C:/MSFS SDK/SimConnect SDK/lib/SimConnect.dll"})
    settings_file.save(config, path)
    again = load_config(path)
    assert again.simbrief_username == "pilot42" and again.tts.engine == "sapi" and again.tts.rate == 190
    assert (again.tts.radio_effect, again.whisper.mic, again.whisper.ptt_key, again.traffic.chatter) == (
        False, 3, "caps lock", False)
    assert again.simconnect_dll == Path("C:/MSFS SDK/SimConnect SDK/lib/SimConnect.dll")
    assert "[tts]" in path.read_text(encoding="utf-8") and "model" not in path.read_text(encoding="utf-8")


def test_only_changed_settings_are_written(tmp_path):
    path = tmp_path / "settings.toml"
    settings_file.save(settings_file.apply(Config(), {"tts.rate": "", "whisper.mic": ""}), path)
    assert path.read_text(encoding="utf-8").strip().startswith("#") and "=" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("values, message", [
    ({"tts.engine": "loud"}, "tts.engine: one of piper, sapi"),
    ({"tts.rate": "fast"}, "tts.rate: a whole number"),
    ({"tts.rate": "900"}, "tts.rate: between 80 and 300"),
    ({"whisper.ptt_key": "f13"}, "whisper.ptt_key: press the key or button again"),
    ({"traffic.chatter": "yes"}, "traffic.chatter: on or off"),
    ({"whisper.model": "large"}, "unknown setting"),
])
def test_wrong_values_are_named(values, message):
    with pytest.raises(ConfigError, match=message):
        settings_file.apply(Config(), values)


def test_the_settings_api(server, tmp_path):  # noqa: F811
    app, base = server
    app.settings_path = tmp_path / "settings.toml"
    data = json.loads(get(base + "/api/settings")[2])
    assert data["values"]["tts.engine"] == "piper" and data["ptt_names"] == {"ptt_key": "Right Ctrl", "ptt_key2": None}
    assert data["values"]["simconnect_dll"] == "" and data["file"].endswith("settings.toml")
    status, saved = post(base + "/api/settings", {"values": {"traffic.chatter": False, "tts.engine": "sapi"}})
    assert status == 200 and saved["values"]["traffic.chatter"] is False
    assert app.config.tts.engine == "sapi" and app.tts_loaded is False  # the voice is loaded again next flight
    assert load_config(app.settings_path).traffic.chatter is False
    assert post(base + "/api/settings", {"values": {"tts.rate": "x"}}) == (400, {"error": "tts.rate: a whole number"})
