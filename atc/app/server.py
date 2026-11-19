"""The app window's backend: a local HTTP server from the standard library (Milestone 3b, A2).

- GET  /                 the page (static/index.html), /static/<file> for CSS and JS
- GET  /api/state        what the window needs to draw: setup or running, plan, banner
- GET  /api/events       Server-Sent Events: every Event of the session, history first
- POST /api/briefing     the flight plan with airports, weather and runways, before starting (start screen)
- POST /api/start        start a session (flight plan + options as JSON)
- POST /api/say          a transmission or /command typed in the window
- POST /api/stop         end the session
- GET  /api/map/area?s=&w=&n=&e=   airports, frequencies, control zones and Center sectors in the map's view
- GET  /api/map/airport?ident=     one airport in full, for its taxi chart
- GET  /api/live?v=N     the words while push-to-talk is held: waits until they differ from version N (long poll)
- GET  /overlay          the small window over the sim (static/overlay.html)
- POST /api/overlay      show or hide it ({"visible": bool}), in the app window only

Only 127.0.0.1 is served. POSTs must be JSON from our own page (Origin check), so another website open in the
browser can't send transmissions to it.
"""
import gzip
import json
import queue
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from atc import paths
from atc.audio import ptt, setup
from atc import settings_file
from atc.config import Config, ConfigError
from atc.airspace.centers import CenterSectors, CentersError
from atc.controller.mapdata import airport_chart, area, map_data
from atc.controller.suggest import phrase_book
from atc.phraseology.catalog import EXAMPLE, GROUPS, PHRASES
from atc import preflight
from atc.events import SPOKEN, Event
from atc.flightlog import FlightLog, log_path
from atc.runtime import run_live
from atc.session import (PlanRequest, Session, SessionOptions, SetupError, airport_sources, build_session,
                         center_sectors, find_airport)
from atc.units import parse_level

STATIC = Path(__file__).parent / "static"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon",
                 ".ttf": "font/ttf", ".txt": "text/plain; charset=utf-8"}
HEARTBEAT_S = 5  # keeps the stream alive; a failed write shows the page is gone
MAX_BODY = 64 * 1024  # a flight plan or a transmission is far smaller
GZIP_FROM = 1024  # answers this big or bigger are sent compressed
GZIP_LEVEL = 6
MAP_CHARTS = 8  # airport charts kept for the map: the flight's own and the ones looked at last
LIVE_WAIT_S = 5  # a long poll of /api/live answers after this at the latest, changed or not


class EventLog:
    """All events of the app, thread-safe, with waiting for new ones (for the event stream)."""

    def __init__(self):
        self.events: list[Event] = []
        self.changed = threading.Condition()

    def emit(self, event: Event) -> None:
        with self.changed:
            self.events.append(event)
            self.changed.notify_all()

    def since(self, index: int, timeout: float) -> list[tuple[int, Event]]:
        with self.changed:
            if len(self.events) <= index:
                self.changed.wait(timeout)
            return list(enumerate(self.events))[index:]


class LiveText:
    """The words while push-to-talk is held (atc/audio/voice.py), for the window and the overlay. Not an Event:
    they change several times a transmission and stay out of the log; what counts comes as "heard" afterwards."""

    def __init__(self):
        self.version, self.text, self.state = 0, "", "idle"
        self.changed = threading.Condition()

    def set(self, text: str, state: str) -> None:
        with self.changed:
            if (text, state) == (self.text, self.state):
                return
            self.version += 1
            self.text, self.state = text, state
            self.changed.notify_all()

    def wait(self, version: int, timeout: float = LIVE_WAIT_S) -> dict:
        """As soon as the version differs from the one given (at once if it already does), else after timeout."""
        with self.changed:
            self.changed.wait_for(lambda: self.version != version, timeout)
            return {"v": self.version, "text": self.text, "state": self.state}


class WindowInput:
    """SpeechInput fed by the window's text box."""

    def __init__(self):
        self.lines: queue.Queue[str | None] = queue.Queue()

    def put(self, text: str | None) -> None:
        self.lines.put(text)

    def listen(self) -> str | None:
        return self.lines.get()


class DeferredInput:
    """Push-to-talk that becomes available once speech recognition has loaded. That takes seconds, or minutes on
    the very first start (model download), and the flight must not wait for it: typing works meanwhile."""

    def __init__(self):
        self._ready = threading.Event()
        self._source = None
        self._sink = None
        self._closed = False

    def attach(self, sink) -> None:
        self._sink = sink

    def ready(self, source) -> None:
        if self._closed:
            source.close()
            return
        if self._sink is not None:
            source.attach(self._sink)
        self._source = source
        self._ready.set()

    def close(self) -> None:
        self._closed = True
        if self._source is not None:
            self._source.close()
        self._ready.set()

    def listen(self) -> str | None:
        self._ready.wait()  # forever if speech never loads: typing still works
        return None if self._closed else self._source.listen()


def load_voice(config: Config, progress):
    """Speech recognition. The model is loaded once per app and reused for every flight."""
    return setup.load_transcriber(config, progress)


def load_live_voice(config: Config, progress, main):
    """The faster model for the words while speaking (whisper.live_model), also loaded once per app."""
    return setup.load_live_transcriber(config, progress, main)


def load_tts(config: Config, report, progress):
    """The ATC voice. The window shows the text already; `report` gets a message if speaking fails, `progress`
    the download messages on the first start."""
    tts = setup.make_tts(config, show=lambda text: None, report=report, progress=progress)
    tts.hold = setup.ptt_held(config)  # the window always has push-to-talk
    return tts


class AppSink:
    """Events go to the log (and so to the window); transmissions also to the voice, if there is one."""

    def __init__(self, log: EventLog, speech=None, flight_log: FlightLog | None = None):
        self.log, self.speech, self.flight_log = log, speech, flight_log

    def emit(self, event: Event) -> None:
        if event.kind != "track":  # the aircraft's position is for the flight log, not the window
            self.log.emit(event)
        if self.flight_log is not None:
            self.flight_log.emit(event)
        if self.speech is not None and event.kind == "tuning" and (cut := getattr(self.speech, "cut_radio", None)):
            cut()  # the old frequency goes quiet at once
        if self.speech is not None and event.kind in SPOKEN:
            self.speech.say(event.text, event.station, kind=event.kind)


def binding_name(text: str | None) -> str | None:
    """"Right Ctrl", "Joystick 1 button 5": a push-to-talk binding as the pilot reads it."""
    if not text:
        return None
    try:
        return ptt.parse(text).name
    except ValueError:
        return text


def microphones() -> list[dict]:
    """The input devices for the Settings page; empty when sounddevice can't list them."""
    try:
        import sounddevice as sd

        return [{"index": i, "name": d["name"]} for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0 and d["hostapi"] == 0]
    except Exception:
        return []


def event_json(index: int, event: Event) -> dict:
    return {"id": index, "kind": event.kind, "text": event.text, "station": event.station, "time": event.time}


class App:
    """One app = at most one running session at a time. The setup helpers (weather, airports, sim, …) can be
    injected like in main(), so tests run without network or MSFS."""

    def __init__(self, config: Config, inject: dict | None = None, settings_path: Path | None = None):
        self.config, self.inject = config, inject or {}
        self.settings_path = settings_path or paths.settings_file()  # where the Settings page saves
        # Loaded with the first flight and reused: the ATC voice (None if it failed) and speech recognition
        self.tts, self.tts_loaded, self.transcriber, self.live_transcriber = None, False, None, None
        self.voice_lock = threading.Lock()
        self.push_to_talk: DeferredInput | None = None
        self.ptt_state = "loading"  # loading, ready, off: the PTT light on the flight screen
        self.log = EventLog()
        self.session: Session | None = None
        self.input: WindowInput | None = None
        self.stop_event: threading.Event | None = None
        self.thread: threading.Thread | None = None
        self.session_from = 0  # first event of the current session
        self.lock = threading.Lock()
        self.live = LiveText()
        self.overlay = None  # the small window over the sim (atc/app/__main__.py), None in a browser
        # The map's own sources, for wherever the pilot moves it (loaded on first use): airports, Center sectors
        self.map_sources = None
        self.map_centers: CenterSectors | None = None
        self.map_charts: dict[str, dict | None] = {}
        self.map_lock = threading.Lock()  # the server answers each request in its own thread

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def state(self) -> dict:
        s = self.session
        return {
            "state": "running" if self.running else ("ended" if s else "setup"),
            "config": {"simbrief_username": self.config.simbrief_username},
            "banner": s.banner() if s and self.running else [],
            "plan": None if s is None else {
                "callsign": s.plan.callsign, "departure": s.plan.departure, "destination": s.plan.destination,
                "cruise_ft": s.plan.cruise_ft, "route": s.plan.route, "aircraft": s.plan.aircraft,
                "source": s.plan_source},
            "session_from": self.session_from,
        }

    def status(self) -> dict | None:
        """The controller's status of the running session (the window polls it every second), or None."""
        if not (self.session and self.running):
            return None
        return {**self.session.controller.status(), "ptt": self.ptt_state,
                "ptt_key": binding_name(self.config.whisper.ptt_key),
                "overlay": None if self.overlay is None else self.overlay.wanted}

    def set_overlay(self, visible: bool) -> dict:
        """The overlay's × and the Overlay chip: shown during a flight or not, remembered for the next one."""
        if self.overlay is None:
            raise SetupError("the overlay is only there in the app window")
        self.overlay.wanted = visible
        if visible and self.running:
            self.overlay.show()
        else:
            self.overlay.hide()
        return {"visible": visible}

    def phrases(self) -> list[dict]:
        """The phrase book: with the running flight's stations and values, or the catalogue's examples."""
        if self.session and self.running:
            return phrase_book(self.session.controller)
        return [{"group": group, "current": False,
                 "phrases": [{"title": p.title, "pilot": p.text(), "atc": p.atc.format(**EXAMPLE), "note": p.note}
                             for p in PHRASES if p.group == group]} for group in GROUPS]

    def map(self) -> dict | None:
        """What the map draws that stays the same for a flight (A6); None without a flight."""
        return map_data(self.session.controller) if self.session and self.running else None

    def _sources(self):
        if self.map_sources is None:  # set once; a second thread at the same moment builds the same list
            self.map_sources = self.inject.get("airports") or airport_sources(self.config)
        return self.map_sources

    def _centers(self) -> CenterSectors:
        if self.session is not None:
            return self.session.centers
        if self.map_centers is None:
            try:
                self.map_centers = self.inject.get("centers") or center_sectors(self.config)
            except CentersError:
                self.map_centers = CenterSectors()  # the map still shows the airports
        return self.map_centers

    def map_area(self, query: dict) -> dict:
        """What lies in the map's view, with or without a flight (O4). The box is south, west, north, east."""
        try:
            s, w, n, e = (float(query[k][0]) for k in ("s", "w", "n", "e"))
        except (KeyError, ValueError):
            raise ValueError("give the box as s, w, n, e in degrees") from None
        if not (-90 <= s <= n <= 90 and -180 <= w <= 180 and -180 <= e <= 180):
            raise ValueError("the box is out of range")
        return area(self._sources(), self._centers(), s, w, n, e)

    def map_airport(self, ident: str) -> dict | None:
        """One airport in full for its taxi chart; None if no source knows it."""
        ident = ident.strip().upper()
        with self.map_lock:
            if ident not in self.map_charts:
                found = find_airport(self._sources(), ident) if ident.isalnum() and len(ident) <= 8 else None
                if len(self.map_charts) >= MAP_CHARTS:
                    self.map_charts.pop(next(iter(self.map_charts)))
                self.map_charts[ident] = airport_chart(found[0]) if found else None
            return self.map_charts[ident]

    def settings(self) -> dict:
        """What the Settings page shows: the values, the choices, where things are."""
        return {"values": settings_file.view(self.config), "microphones": microphones(),
                "ptt_names": {slot: binding_name(getattr(self.config.whisper, slot))
                              for slot in ("ptt_key", "ptt_key2")},
                "engines": list(settings_file.TTS_ENGINES), "file": str(self.settings_path),
                "folders": {"settings": str(paths.config_dir()), "data": str(paths.data_dir()),
                            "logs": str(paths.logs_dir())}}

    def capture_ptt(self) -> dict:
        """The Settings page's "press the key or button now": waits up to 10 s (A real key press, so not in tests.)"""
        binding = ptt.capture()
        if binding is None:
            raise SetupError("nothing was pressed within 10 seconds")
        return {"binding": binding.text, "name": binding.name}

    def save_settings(self, values: dict) -> dict:
        """Check and save; they apply from the next flight. A changed voice is loaded again then."""
        try:
            new = settings_file.apply(self.config, values)
        except ConfigError as e:
            raise SetupError(str(e)) from None
        settings_file.save(new, self.settings_path)
        if self.tts is not None:
            self.tts.mixer = new.mixer  # the sound mixer works at once, also during a flight
        with self.voice_lock:
            if new.tts != self.config.tts:
                if self.tts is not None:
                    self.tts.close()
                self.tts, self.tts_loaded = None, False
            if (new.whisper.model, new.whisper.device) != (self.config.whisper.model, self.config.whisper.device):
                self.transcriber = self.live_transcriber = None
            elif (new.whisper.live_model, new.whisper.live_text) != (self.config.whisper.live_model,
                                                                     self.config.whisper.live_text):
                self.live_transcriber = None
        self.config = new
        return self.settings()

    def briefing(self, body: dict) -> dict:
        """The start screen's "Load flight": what the flight will be, nothing started yet."""
        request, options = parse_start(body)
        return preflight.brief(request, options, self.config, **self.inject)

    def start(self, body: dict) -> dict:
        with self.lock:
            if self.running:
                raise SetupError("a session is already running: stop it first")
            request, options = parse_start(body)
            session = build_session(request, options, self.config, **self.inject)
            self.session, self.input, self.stop_event = session, WindowInput(), threading.Event()
            self.push_to_talk = DeferredInput()
            self.session_from = len(self.log.events)
            flight_log = FlightLog(log_path(paths.logs_dir(), session.plan.callsign, time.time()),
                                   session.banner())
            sink = AppSink(self.log, flight_log=flight_log)
            sink.emit(Event("system", f"session started: {session.plan.callsign} "
                                      f"{session.plan.departure} -> {session.plan.destination or '?'}"))
            for line in session.banner():
                sink.emit(Event("system", line))
            sink.emit(Event("system", f"Flight log: {flight_log.path}"))
            self.thread = threading.Thread(target=self._run, args=(session, sink), daemon=True)
            self.thread.start()
            threading.Thread(target=self._start_voice, args=(sink, self.push_to_talk), daemon=True).start()
            if self.overlay is not None and self.overlay.wanted:
                self.overlay.show()
        return self.state()

    def _start_voice(self, sink: AppSink, push_to_talk: DeferredInput) -> None:
        def progress(text: str) -> None:
            sink.emit(Event("system", text))

        def report(text: str) -> None:
            sink.emit(Event("notice", text))

        # The ATC voice first: it starts in a moment and doesn't depend on the slow speech recognition
        with self.voice_lock:  # a second flight started while the first one still loads: wait for it
            if not self.tts_loaded:
                try:
                    self.tts = load_tts(self.config, report, progress)
                    progress(f"ATC voice: {self.tts.voice_name}")
                except Exception as e:
                    progress(f"ATC voice is off ({e}); ATC is shown as text")
                self.tts_loaded = True
        sink.speech = self.tts
        self.ptt_state = "loading"
        try:
            with self.voice_lock:
                if self.transcriber is None:
                    self.transcriber = load_voice(self.config, progress)
            listener = setup.make_whisper_input(self.config, self.transcriber)
            session = self.session
            listener.context = lambda: session.controller.speech_context()  # this flight's words for whisper
            if getattr(listener, "live_wanted", False):
                listener.live = self.live.set  # the words while speaking (Settings: live text)
            push_to_talk.ready(listener)
            progress(f"Push-to-talk ready: hold [{binding_name(self.config.whisper.ptt_key)}] while you speak")
            self.ptt_state = "ready"
            if getattr(listener, "live_wanted", False):
                # After "ready": push-to-talk already works while the faster live model loads (or downloads)
                try:
                    with self.voice_lock:
                        if self.live_transcriber is None:
                            self.live_transcriber = load_live_voice(self.config, progress, self.transcriber)
                    listener.live_transcriber = self.live_transcriber
                except Exception as e:  # push-to-talk is ready: the live words then come from the main model
                    progress(f"Live text uses the main speech model ({e})")
        except Exception as e:  # no model, no microphone, ...: the flight goes on with typing
            self.ptt_state = "off"
            progress(f"Voice is off: {e}. Typing still works.")

    def _run(self, session: Session, sink: AppSink) -> None:
        try:
            run_live(session.sim, [self.input, self.push_to_talk], sink, session.controller,
                     refresh=session.refresh_weather,
                     winds=session.winds if session.sim_wind else None, stop=self.stop_event,
                     cabin=session.cabin(), gsx=session.gsx())
        except Exception as e:  # shown in the window instead of a silent dead thread
            sink.emit(Event("system", f"the session stopped because of an error: {e}"))
            traceback.print_exc()
        finally:
            session.close()
            self.live.set("", "idle")
            if self.overlay is not None:
                self.overlay.hide()
            sink.emit(Event("system", "session ended"))
            if sink.flight_log is not None:
                sink.flight_log.close()

    def say(self, text: str) -> None:
        text = text.strip()
        if not self.running or self.input is None:
            raise SetupError("no session is running")
        if text:
            self.input.put(text)

    def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        if self.input:
            self.input.put(None)
        if self.push_to_talk:
            self.push_to_talk.close()
        if self.thread:
            self.thread.join(timeout=5)


def parse_start(body: dict) -> tuple[PlanRequest, SessionOptions]:
    def text(key: str) -> str | None:
        value = body.get(key)
        return (value.strip() or None) if isinstance(value, str) else None

    cruise = text("cruise")
    try:
        cruise_ft = parse_level(cruise) if cruise else None
    except Exception:
        raise SetupError(f"cruise level {cruise!r}: use e.g. FL350 or 5000") from None
    simbrief = body.get("simbrief")
    request = PlanRequest(simbrief=simbrief.strip() if isinstance(simbrief, str) else None,
                          callsign=text("callsign"), departure=text("departure"), destination=text("destination"),
                          cruise_ft=cruise_ft, route=text("route") or "", aircraft=text("aircraft"),
                          rules=text("rules"))
    weather = body.get("weather", "live")
    if weather not in ("live", "sim"):
        raise SetupError(f"weather {weather!r}: live or sim")
    return request, SessionOptions(nosim=bool(body.get("nosim")), weather=weather,
                                   strict_freq=bool(body.get("strict_freq")))


def make_handler(app: App, heartbeat_s: float = HEARTBEAT_S):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # quiet: the window is the user interface
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                return self._file(STATIC / "index.html")
            if path == "/overlay":
                return self._file(STATIC / "overlay.html")
            if path == "/api/live":
                v = parse_qs(urlparse(self.path).query).get("v", ["-1"])[0]
                return self._json(app.live.wait(int(v) if v.lstrip("-").isdigit() else -1))
            if path.startswith("/static/"):
                return self._file(STATIC / path.removeprefix("/static/"))
            if path == "/api/state":
                return self._json(app.state())
            if path == "/api/status":
                return self._json(app.status())
            if path == "/api/settings":
                return self._json(app.settings())
            if path == "/api/map":
                return self._json(app.map())
            if path == "/api/map/area":
                try:
                    return self._json(app.map_area(parse_qs(urlparse(self.path).query)))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if path == "/api/map/airport":
                ident = parse_qs(urlparse(self.path).query).get("ident", [""])[0]
                return self._json(app.map_airport(ident))
            if path == "/api/phrases":
                return self._json(app.phrases())
            if path == "/api/events":
                return self._events()
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                return self._json({"error": "bad request"}, 400)
            raw = self.rfile.read(length)  # read before any answer: Windows resets a socket with unread data
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin is not None and urlparse(origin).netloc != host:
                return self._json({"error": "forbidden"}, 403)
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json({"error": "JSON only"}, 415)
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json({"error": "bad JSON"}, 400)
            try:
                if path == "/api/start":
                    return self._json(app.start(body))
                if path == "/api/briefing":
                    return self._json(app.briefing(body))
                if path == "/api/say":
                    app.say(str(body.get("text", "")))
                    return self._json({"ok": True})
                if path == "/api/stop":
                    app.stop()
                    return self._json(app.state())
                if path == "/api/ptt/capture":
                    return self._json(app.capture_ptt())
                if path == "/api/overlay":
                    return self._json(app.set_overlay(bool(body.get("visible"))))
                if path == "/api/settings":
                    values = body.get("values")
                    if not isinstance(values, dict):
                        raise SetupError("expected {\"values\": {...}}")
                    return self._json(app.save_settings(values))
            except SetupError as e:
                return self._json({"error": str(e)}, 400)
            self._json({"error": "not found"}, 404)

        def _file(self, path: Path):
            path = path.resolve()
            if STATIC.resolve() not in path.parents or not path.is_file():
                return self._json({"error": "not found"}, 404)
            self._send(200, CONTENT_TYPES.get(path.suffix, "application/octet-stream"), path.read_bytes(),
                       {"Cache-Control": "no-cache"})

        def _json(self, data, status: int = 200):
            self._send(status, "application/json", json.dumps(data).encode())

        def _send(self, status: int, content_type: str, body: bytes, headers: dict | None = None):
            """Bigger answers go gzip-compressed to a client that takes it (every browser does). Smaller and
            faster, and found 2026-11-15: with Avast's web shield one in ten uncompressed answers of ~140 KB (the
            map, the fonts) stalled on localhost, compressed ones never did."""
            headers = dict(headers or {})
            if len(body) >= GZIP_FROM and "gzip" in self.headers.get("Accept-Encoding", ""):
                body = gzip.compress(body, GZIP_LEVEL)
                headers["Content-Encoding"] = "gzip"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Vary", "Accept-Encoding")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _events(self):
            last = self.headers.get("Last-Event-ID")  # a reconnecting stream continues where it was
            start = parse_qs(urlparse(self.path).query).get("from", ["0"])[0]
            index = int(last) + 1 if last and last.isdigit() else int(start) if start.isdigit() else 0
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    new = app.log.since(index, heartbeat_s)
                    for i, event in new:
                        self.wfile.write(f"id: {i}\ndata: {json.dumps(event_json(i, event))}\n\n".encode())
                        index = i + 1
                    if not new:
                        self.wfile.write(b": ping\n\n")  # a closed window shows up as a failed write
                    self.wfile.flush()
            except OSError:  # the page was closed or reloaded
                pass

    return Handler


class LocalServer(ThreadingHTTPServer):
    # HTTPServer turns SO_REUSEADDR on, and on Windows that lets a second copy bind the same port silently
    # (requests then go to either one). Off, the second copy gets an error and picks another port.
    allow_reuse_address = False
    daemon_threads = True


def make_server(app: App, port: int, heartbeat_s: float = HEARTBEAT_S) -> ThreadingHTTPServer:
    return LocalServer(("127.0.0.1", port), make_handler(app, heartbeat_s))
