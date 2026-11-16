import pytest

from atc.airport.json_data import JsonAirportData
from atc.audio.setup import VoiceUnavailable
from atc.config import ROOT
from atc.sim.simconnect import NOT_RUNNING, SimUnavailable


@pytest.fixture(autouse=True)
def user_dirs_in_tmp(monkeypatch, tmp_path):
    """Settings, cache, models and logs go to a temp folder: tests never read or write the real %APPDATA%."""
    monkeypatch.setenv("MSFS_ATC_HOME", str(tmp_path / "user"))


@pytest.fixture(autouse=True)
def no_real_sim(monkeypatch):
    """Tests must never talk to a running MSFS: main() gets a fake sim injected, or this error."""
    def refuse(**kwargs):
        raise SimUnavailable(NOT_RUNNING)
    monkeypatch.setattr("atc.session.SimConnectSource", refuse)


@pytest.fixture(autouse=True)
def no_real_voice(monkeypatch):
    """Nor load whisper, open the microphone or speak: tests inject a fake voice."""
    def refuse(*args):
        raise VoiceUnavailable("no microphone or speakers in tests")
    monkeypatch.setattr("atc.main.build_voice", refuse)
    monkeypatch.setattr("atc.app.server.load_voice", refuse)
    monkeypatch.setattr("atc.app.server.load_tts", refuse)


@pytest.fixture(autouse=True)
def no_downloads(monkeypatch):
    """Nor download models or voices (found when a test fetched the 79 MB Piper voice): tests pass a fake."""
    def offline(url, timeout=30):
        raise OSError(f"no internet in tests: {url}")
    monkeypatch.setattr("atc.audio.setup._http", offline)


@pytest.fixture(autouse=True)
def no_real_littlenavmap_centers(monkeypatch):
    """Nor read the Center sectors of the developer's Little Navmap database: tests get centers.json only."""
    monkeypatch.setattr("atc.session.load_littlenavmap_centers", lambda db_path: [])


@pytest.fixture
def eddh():
    return JsonAirportData(ROOT / "data" / "airports").get("EDDH")


@pytest.fixture
def eddm():
    return JsonAirportData(ROOT / "data" / "airports").get("EDDM")


AIRPORT_FILES = [ROOT / "data" / "airports" / f"{ident}.json" for ident in ("EDDH", "EDDM")]


def pytest_collection_modifyitems(config, items):
    """The airports the tests fly between are exported from the developer's own Little Navmap database and are not
    in the public repository (scenery licences). Without them, the tests that need them are skipped."""
    if all(f.exists() for f in AIRPORT_FILES):
        return
    skip = pytest.mark.skip(reason="needs data/airports/EDDH.json and EDDM.json: export them from your own Little "
                                   "Navmap database with: python -m atc.airport.export EDDH EDDM")
    import inspect

    sources: dict[str, str] = {}
    for item in items:
        path = str(item.fspath)
        if path not in sources:
            sources[path] = open(path, encoding="utf-8").read()
        try:
            body = inspect.getsource(item.function)
        except (OSError, TypeError):
            body = ""
        uses_airports = (
            {"eddh", "eddm", "server"} & set(item.fixturenames)  # the app's server is built with them (test_app)
            or '"data" / "airports"' in sources[path]
            or any(helper in body for helper in ("INJECT", "AIRPORTS", "run_session(", '"EDDH"')))
        if uses_airports:
            item.add_marker(skip)


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true",
                     help="rewrite tests/scenarios/*.golden.txt from the current output (review the diff!)")
