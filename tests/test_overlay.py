"""The overlay over the sim and the live words in the window (2026-11-18): server side, without a real window."""
import json
import threading
import time
from types import SimpleNamespace

from atc.app.overlay import SIZE, Overlay
from atc.app.server import LiveText
from tests.test_app import PLAN, get, post, server  # noqa: F401 (server: the fixture)


class FakeWindow:
    def __init__(self):
        self.shown = 0
        self.hidden = 0
        self.events = SimpleNamespace(moved=Hooks())

    def show(self):
        self.shown += 1

    def hide(self):
        self.hidden += 1


class Hooks(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self


def overlay(tmp_path, wanted=True):
    o = Overlay(tmp_path / "overlay.json", 10, 20, wanted)
    o.attach(FakeWindow())
    return o


def test_the_live_text_long_poll():
    live = LiveText()
    assert live.wait(-1, 0) == {"v": 0, "text": "", "state": "idle"}  # differs: at once
    start = time.monotonic()
    assert live.wait(0, 0.1)["v"] == 0 and time.monotonic() - start >= 0.09  # nothing new: after the timeout
    threading.Timer(0.05, live.set, ("Hamburg Ground", "speaking")).start()
    assert live.wait(0, 2) == {"v": 1, "text": "Hamburg Ground", "state": "speaking"}
    live.set("Hamburg Ground", "speaking")  # the same again: no new version
    assert live.version == 1


def test_live_and_overlay_page_served(server):
    app, base = server
    app.live.set("Hamburg Ground", "speaking")
    assert json.loads(get(base + "/api/live?v=-1")[2]) == {"v": 1, "text": "Hamburg Ground", "state": "speaking"}
    assert json.loads(get(base + "/api/live?v=x")[2])["v"] == 1
    status, kind, body = get(base + "/overlay")
    assert status == 200 and kind.startswith("text/html") and b"overlay.js" in body
    assert get(base + "/static/overlay.js")[1].startswith("text/javascript")


def test_overlay_only_in_the_app_window(server):
    _, base = server
    assert post(base + "/api/overlay", {"visible": True}) == (400, {"error": "the overlay is only there in the app window"})


def test_overlay_shown_during_a_flight_and_remembered(server, tmp_path):
    app, base = server
    app.overlay = o = overlay(tmp_path)
    assert post(base + "/api/start", PLAN)[0] == 200
    assert o.window.shown == 1  # wanted: shown with the flight
    assert json.loads(get(base + "/api/status")[2])["overlay"] is True
    assert post(base + "/api/overlay", {"visible": False}) == (200, {"visible": False})
    assert o.window.hidden == 1 and json.loads((tmp_path / "overlay.json").read_text()) == {
        "visible": False, "x": 10, "y": 20}
    assert post(base + "/api/overlay", {"visible": True})[0] == 200 and o.window.shown == 2
    post(base + "/api/stop", {})
    assert o.window.hidden == 2  # the flight is over: hidden, still wanted for the next one
    assert o.wanted is True


def test_overlay_place_from_the_file_or_the_screen_corner(tmp_path):
    screen = SimpleNamespace(x=0, y=0, width=1920, height=1080)
    path = tmp_path / "overlay.json"
    first = Overlay.load(path, [screen])
    assert (first.x, first.y, first.wanted) == (1920 - SIZE[0] - 24, 96, True)
    path.write_text(json.dumps({"visible": False, "x": 100, "y": 200}))
    assert vars(Overlay.load(path, [screen])) | {} == vars(Overlay(path, 100, 200, False))
    path.write_text(json.dumps({"visible": True, "x": 5000, "y": 200}))  # an unplugged monitor
    assert Overlay.load(path, [screen]).x == 1920 - SIZE[0] - 24
    o = overlay(tmp_path)
    o.window.events.moved[0](300, 400)
    o.save()
    assert json.loads(path.read_text()) == {"visible": True, "x": 300, "y": 400}


def test_the_live_words_only_with_the_setting(server, monkeypatch):
    app, base = server
    from atc.audio import setup

    class Listener:
        live_wanted = False
        live = None
        context = None

    made = []
    monkeypatch.setattr("atc.app.server.load_voice", lambda config, progress: object())
    monkeypatch.setattr(setup, "make_whisper_input", lambda config, t: made.append(Listener()) or made[-1])
    monkeypatch.setattr("atc.app.server.load_tts", lambda *a: (_ for _ in ()).throw(RuntimeError("no voice")))
    assert post(base + "/api/start", PLAN)[0] == 200
    deadline = time.monotonic() + 5
    while app.ptt_state != "ready" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert made and made[0].live is None
