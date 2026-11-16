"""The app window's server: a real server on a free local port, the fake sim, no network, no MSFS."""
import gzip
import json
import threading
import urllib.error
import urllib.request

import pytest

from atc.airport.json_data import JsonAirportData
from atc.app.__main__ import bind
from atc.app.server import App, make_server
from atc.config import ROOT, Config
from atc.weather.source import StaticWeather

INJECT = {"weather": StaticWeather({"EDDH": "METAR EDDH 141450Z AUTO 22007KT 9999 SCT035 07/04 Q1018 NOSIG"}),
          "airports": [JsonAirportData(ROOT / "data" / "airports")]}
PLAN = {"callsign": "dlh4ab", "departure": "EDDH", "destination": "EDDM", "cruise": "FL350", "nosim": True}


@pytest.fixture
def server():
    app = App(Config(), INJECT)
    srv = make_server(app, 0, heartbeat_s=0.2)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield app, f"http://127.0.0.1:{srv.server_address[1]}"
    app.stop()
    srv.shutdown()
    srv.server_close()


BROWSER = {"Accept-Encoding": "gzip, deflate, br"}  # as the app's window asks; urllib alone doesn't


def body_of(r) -> bytes:
    data = r.read()
    return gzip.decompress(data) if r.headers.get("Content-Encoding") == "gzip" else data


def get(url, headers=BROWSER):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), body_of(r)


def post(url, body, headers=None):
    request = urllib.request.Request(url, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", **BROWSER, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.loads(body_of(r))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(body_of(e))


def test_big_answers_are_compressed_for_a_browser(server):
    _, base = server
    font = "/static/fonts/B612Mono-Regular.ttf"
    with urllib.request.urlopen(urllib.request.Request(base + font, headers=BROWSER), timeout=5) as r:
        assert r.headers["Content-Encoding"] == "gzip" and int(r.headers["Content-Length"]) < 140292
        assert gzip.decompress(r.read()) == (ROOT / "atc" / "app" / "static" / font.removeprefix("/static/")).read_bytes()
    with urllib.request.urlopen(base + "/api/status", timeout=5) as r:
        assert r.headers.get("Content-Encoding") is None and r.read() == b"null"  # small: as it is


def test_a_client_without_gzip_gets_it_plain(server):
    _, base = server
    with urllib.request.urlopen(base + "/static/app.css", timeout=5) as r:  # no Accept-Encoding
        assert r.headers.get("Content-Encoding") is None
        assert r.read() == (ROOT / "atc" / "app" / "static" / "app.css").read_bytes()


def wait_for(app, predicate, timeout=5):
    deadline = threading.Event()
    timer = threading.Timer(timeout, deadline.set)
    timer.start()
    try:
        index = 0
        while not deadline.is_set():
            for i, event in app.log.since(index, 0.1):
                index = i + 1
                if predicate(event):
                    return event
        raise AssertionError("event did not arrive")
    finally:
        timer.cancel()


def test_page_and_static_files(server):
    _, base = server
    status, kind, body = get(base + "/")
    assert status == 200 and kind.startswith("text/html") and b"MSFS ATC" in body
    assert get(base + "/static/app.css")[1].startswith("text/css")
    assert get(base + "/static/app.js")[1].startswith("text/javascript")
    assert get(base + "/static/fonts/B612Mono-Regular.ttf")[1] == "font/ttf"  # bundled: works offline
    assert get(base + "/api/status")[2] == b"null"  # no flight yet


def test_files_outside_static_are_not_served(server):
    _, base = server
    for path in ("/static/../server.py", "/static/..%2Fserver.py", "/nothing"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base + path)
        assert e.value.code == 404


def test_setup_state_before_a_flight(server):
    _, base = server
    state = json.loads(get(base + "/api/state")[2])
    assert state["state"] == "setup" and state["plan"] is None


def test_a_flight_from_the_window(server):
    app, base = server
    status, state = post(base + "/api/start", PLAN)
    assert status == 200 and state["state"] == "running"
    assert state["plan"]["callsign"] == "DLH4AB" and state["plan"]["cruise_ft"] == 35000
    assert any(line.startswith("DLH4AB parked at EDDH") for line in state["banner"])

    assert post(base + "/api/say", {"text": "/com 121.705"})[0] == 200
    assert post(base + "/api/say", {"text": "Hamburg Ground, Lufthansa 4AB, request clearance information alpha"})[0] == 200
    clearance = wait_for(app, lambda e: e.kind == "atc")
    assert clearance.station == "Hamburg Ground" and "cleared to Munich" in clearance.text

    status, state = post(base + "/api/stop", {})
    assert state["state"] == "ended"
    wait_for(app, lambda e: e.text == "session ended")
    assert post(base + "/api/say", {"text": "hello"}) == (400, {"error": "no session is running"})


def test_setup_errors_are_shown_not_crashed(server):
    _, base = server
    assert post(base + "/api/start", {"departure": "EDDH", "nosim": True}) == (
        400, {"error": "--callsign is required (or use --simbrief)"})
    assert post(base + "/api/start", {**PLAN, "cruise": "high"})[1]["error"].startswith("cruise level 'high'")
    assert post(base + "/api/start", {**PLAN, "nosim": False})[1]["error"].startswith("MSFS is not running")


def test_only_one_session_at_a_time(server):
    _, base = server
    post(base + "/api/start", PLAN)
    assert post(base + "/api/start", PLAN) == (400, {"error": "a session is already running: stop it first"})


def test_other_websites_cannot_post(server):
    _, base = server
    assert post(base + "/api/start", PLAN, {"Origin": "https://evil.example"}) == (403, {"error": "forbidden"})
    request = urllib.request.Request(base + "/api/say", b"text=hi", {"Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(request, timeout=5)
    assert e.value.code == 415


def test_event_stream_sends_the_session(server):
    app, base = server
    post(base + "/api/start", PLAN)
    with urllib.request.urlopen(base + "/api/events?from=0", timeout=5) as stream:
        lines = []
        while not any('"session started' in line for line in lines):
            lines.append(stream.readline().decode())
    data = json.loads(next(line for line in lines if line.startswith("data: "))[6:])
    assert data["kind"] == "system" and data["id"] == 0 and data["text"].startswith("session started: DLH4AB")


def test_a_taken_port_falls_back_to_a_free_one(server):
    app, base = server
    taken = int(base.rsplit(":", 1)[1])
    other = bind(App(Config()), taken)
    assert other.server_address[1] != taken
    other.server_close()



def test_the_phrase_book_with_and_without_a_flight(server):
    app, base = server
    book = json.loads(get(base + "/api/phrases")[2])
    assert [g["group"] for g in book][0] == "Clearance" and not any(g["current"] for g in book)
    post(base + "/api/start", PLAN)
    book = json.loads(get(base + "/api/phrases")[2])
    assert book[0]["current"] and book[0]["phrases"][1]["pilot"].startswith("Hamburg Ground, Lufthansa 4AB, request")
    assert json.loads(get(base + "/api/status")[2])["suggestion"]["title"] == "Request IFR clearance"
