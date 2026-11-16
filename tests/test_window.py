"""The desktop window without opening one: saved geometry, screens, and how the launcher starts and stops."""
import threading
from types import SimpleNamespace

import pytest

import atc.app.__main__ as launcher
from atc.app import window_state
from atc.app.window_state import Geometry

# The developer's three screens: main, one to the left (negative x), one above (negative y)
SCREENS = [SimpleNamespace(x=0, y=0, width=2560, height=1440),
           SimpleNamespace(x=-1920, y=170, width=1920, height=1080),
           SimpleNamespace(x=-489, y=-1440, width=3440, height=1440)]


def test_geometry_round_trip(tmp_path):
    path = tmp_path / "window.json"
    assert window_state.load(path) is None  # first start
    window_state.save(path, Geometry(-1800, 300, 900, 700, maximized=True))
    assert window_state.load(path) == Geometry(-1800, 300, 900, 700, maximized=True)


def test_broken_or_tiny_saved_windows(tmp_path):
    path = tmp_path / "window.json"
    path.write_text("{not json", encoding="utf-8")
    assert window_state.load(path) is None
    path.write_text('{"x": 10, "y": 10, "width": 50, "height": 20}', encoding="utf-8")
    assert window_state.load(path) == Geometry(10, 10, *window_state.MIN_SIZE)


@pytest.mark.parametrize("geometry, visible", [
    (Geometry(100, 100, 1100, 760), True),  # main screen
    (Geometry(-1800, 300, 900, 700), True),  # second monitor on the left
    (Geometry(200, -1300, 900, 700), True),  # monitor above
    (Geometry(-1900, -100, 900, 700), False),  # title bar in the gap above the left monitor
    (Geometry(5000, 200, 900, 700), False),  # a monitor that isn't connected any more
    (Geometry(2540, 100, 900, 700), False),  # only 20 px left to grab
])
def test_saved_position_must_still_be_on_a_screen(geometry, visible):
    assert window_state.on_screen(geometry, SCREENS) is visible


def test_off_screen_position_falls_back_to_the_default():
    assert window_state.initial(Geometry(5000, 200, 900, 700), SCREENS) is None
    assert window_state.initial(Geometry(100, 100, 900, 700), SCREENS) == Geometry(100, 100, 900, 700)
    assert window_state.initial(None, SCREENS) is None


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in self.handlers:
            handler(*args)


class FakeWindow:
    def __init__(self):
        self.x, self.y, self.width, self.height = 100, 100, 1100, 760
        self.events = SimpleNamespace(**{name: FakeEvent() for name in
                                         ("minimized", "maximized", "restored", "moved", "resized")})

    def move(self, x, y):
        self.x, self.y = x, y
        self.events.moved.fire(x, y)


def test_tracker_keeps_the_last_normal_geometry():
    window, tracker = FakeWindow(), launcher.GeometryTracker(None)
    tracker.attach(window)
    window.move(-1800, 300)  # dragged to the second monitor
    window.events.minimized.fire()
    window.move(-32000, -32000)  # where Windows parks minimised windows
    window.events.restored.fire()
    window.events.maximized.fire()
    assert tracker.result() == Geometry(-1800, 300, 1100, 760, maximized=True)


def test_closing_the_window_stops_session_and_server(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(launcher, "run_window", lambda url: calls.append(("window", url)) or True)
    real_shutdown = launcher.shutdown
    monkeypatch.setattr(launcher, "shutdown", lambda app, server: (calls.append("shutdown"), real_shutdown(app, server)))
    launcher.main(["--port", "0"])
    assert calls[0][0] == "window" and calls[0][1].startswith("http://127.0.0.1:")
    assert calls[1] == "shutdown"


def test_browser_flag_and_fallback(monkeypatch):
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    monkeypatch.setattr(launcher, "wait_for_ctrl_c", lambda: None)
    monkeypatch.setattr(launcher, "run_window", lambda url: pytest.fail("no window with --browser"))
    launcher.main(["--port", "0", "--browser"])
    monkeypatch.setattr(launcher, "run_window", lambda url: False)  # e.g. no WebView2 runtime
    launcher.main(["--port", "0"])
    assert len(opened) == 2


def test_shutdown_stops_a_running_session():
    from atc.app.server import App, make_server
    from tests.test_app import INJECT, PLAN
    from atc.config import Config
    app = App(Config(), INJECT)
    server = make_server(app, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()  # shutdown() waits for serve_forever
    app.start(PLAN)
    assert app.running
    launcher.shutdown(app, server)
    assert not app.running
    assert any(e.text == "session ended" for e in app.log.events)
