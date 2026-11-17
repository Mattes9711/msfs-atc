"""Running a session: the loops, the /commands and COM1 tuning. Everything shown goes to a Sink as Events,
so the console and the app window run the same code."""
import queue
import threading
import time
from typing import Callable

from atc.airport.geo import distance_nm
from atc.audio.base import SpeechInput
from atc import copilot
from atc.cabin import Cabin
from atc.controller.circuit import LEGS
from atc.controller.controller import Controller, Response
from atc.events import Event, Sink
from atc.phraseology import spoken
from atc.phraseology.taxi import taxi_clearance
from atc.sim.base import SimSource
from atc.sim.fake import FakeSim
from atc.units import format_khz, parse_mhz

TICK_S = 1.0  # the live loop checks the aircraft (handoffs, safety, sectors) this often
STILL_KT = 1  # slower than this the aircraft stands still (GROUND_VELOCITY jitters around 0.01 kt)
WEATHER_REFRESH_S = 30 * 60

HELP = ("Commands: /com <MHz> tune COM1 | /taxi show the taxi route | /goto holding|crossing|runway on the ground | "
        "/fly <nm> airborne, nm along the route | /final <nm> on final | /circuit <leg> in the circuit of a "
        "small field (upwind, crosswind, downwind, base, final) | /landed [go] (go: a touch-and-go) | "
        "/beacon on|off | /help | /quit. "
        "Anything else is a radio transmission. (/com, /goto, /fly, /final, /circuit and /landed move the fake sim; "
        "with MSFS you fly yourself.)")
SIM_COMMANDS = ("/com", "/goto", "/fly", "/final", "/circuit", "/landed", "/beacon")


def emit_responses(sink: Sink, responses: list[Response]) -> None:
    for r in responses:
        sink.emit(Event(r.event_kind, r.text, r.station))


def transmit(sink: Sink, sim: SimSource, controller: Controller, text: str) -> None:
    """A pilot transmission: shown as the pilot's, then whatever ATC makes of it."""
    sink.emit(Event("pilot", text))
    emit_responses(sink, controller.handle(text, sim.read()))


COPILOT_TRIES = 2  # the same call twice without success: the co-pilot gives the radio back


def copilot_command(name: str, sim: SimSource, controller: Controller, sink: Sink) -> None:
    """The pilot talks to the co-pilot: "on" (you have the radio), "off" (I have the radio), "next" (the next call)."""
    if name == "on":
        controller.copilot_on, controller.copilot_tries = True, ("", 0)
        sink.emit(Event("notice", "Co-pilot: I have the radio. I make the calls as we go (the pushback once the "
                                  "beacon is on); \"copilot, next call\" for one earlier, \"I have the radio\" "
                                  "to take it back."))
    elif name == "off":
        controller.copilot_on = False
        sink.emit(Event("notice", "Co-pilot: you have the radio."))
    elif name == "next":
        call = copilot.next_call(controller)
        if call is None:
            sink.emit(Event("notice", "Co-pilot: nothing to call right now."))
        else:
            copilot_says(call["text"], sim, controller, sink)


def _tune(sim: SimSource, controller: Controller, sink: Sink, khz: int) -> None:
    try:
        getattr(sim, "set_com1")(khz)
    except Exception as e:  # a sim that can't be tuned: the pilot tunes, the co-pilot still talks
        controller.copilot_on = False
        sink.emit(Event("notice", f"Co-pilot: can't tune COM1 ({e}); you have the radio."))


def copilot_says(text: str, sim: SimSource, controller: Controller, sink: Sink) -> None:
    sink.emit(Event("copilot", text, copilot.SPEAKER))
    emit_responses(sink, controller.handle(text, sim.read() if controller.state is None else controller.state))


def copilot_turn(sim: SimSource, controller: Controller, sink: Sink, now: float | None = None,
                 still_s: float = 0.0, pushed: bool = False, gsx_state=None, last_radio: float | None = None) -> bool:
    """While the co-pilot has the radio (C2): tune COM1 after a handoff, read back, check in; with a clock (`now`)
    also the phase's requests once the aircraft is ready for them, on a quiet radio. True when he did something."""
    if not controller.copilot_on:
        return False
    if (khz := copilot.frequency_to_tune(controller)) is not None:
        _tune(sim, controller, sink, khz)
        return True
    call = copilot.due(controller)
    if call is None and now is not None and (last_radio is None or now - last_radio >= copilot.QUIET_S):
        call = copilot.request_due(controller, still_s, pushed, gsx_state)
        if call is not None and controller.state is not None and controller.state.com1_khz != call["khz"]:
            _tune(sim, controller, sink, call["khz"])  # e.g. Delivery or Ground before the first call
            return True
    if call is None:
        return False
    last, tries = controller.copilot_tries
    tries = tries + 1 if call["text"] == last else 1
    if tries > COPILOT_TRIES:  # ATC keeps saying "negative": better the pilot looks at it
        controller.copilot_on = False
        sink.emit(Event("notice", "Co-pilot: that readback didn't work, you have the radio."))
        return False
    controller.copilot_tries = (call["text"], tries)
    copilot_says(call["text"], sim, controller, sink)
    return True


COPILOT_TEXT_STEPS = 8  # text mode: after a line he does what is due, at most this many calls in a row


def copilot_text_turn(sim: SimSource, controller: Controller, sink: Sink) -> None:
    """Text mode has no clock and the fake sim stands still: after each line the co-pilot does everything that is
    due, as if he had waited (standing still long enough, the push done)."""
    for _ in range(COPILOT_TEXT_STEPS):
        if not copilot_turn(sim, controller, sink, now=0.0, still_s=copilot.STILL_S, pushed=True):
            return
        emit_responses(sink, controller.tick(sim.read()))  # sees the new frequency, hands over, …


def announce(cabin: Cabin | None, controller: Controller, state, sink: Sink, gsx_state=None,
             with_gsx: bool = False, now: float | None = None, last_radio: float | None = None) -> None:
    """The cabin announcements due now (C1), after ATC's own calls. With GSX running (C3) the welcome and the
    doors wait for its boarding to be done; with the live clock each waits for a quiet radio."""
    if cabin is not None and state is not None:
        boarding_done = gsx_state.boarding_done if with_gsx and gsx_state is not None else None
        for event in cabin.check(controller.phase, state.on_ground, state.alt_msl_ft, controller.descent_given,
                                 boarding_done, now, last_radio):
            sink.emit(event)


RADIO_KINDS = ("atc", "chatter", "copilot", "pilot")  # the ATIS is not: it may play on and on


class RadioClock:
    """Passes events on and notes when the radio was last busy (for the cabin, which waits for a quiet radio)."""

    def __init__(self, sink: Sink, clock: Callable[[], float]):
        self.sink, self.clock, self.last = sink, clock, None

    def emit(self, event: Event) -> None:
        if event.kind in RADIO_KINDS:
            self.last = self.clock()
        self.sink.emit(event)


def run(sim: SimSource, speech_in: SpeechInput, sink: Sink, controller: Controller,
        cabin: Cabin | None = None) -> None:
    """Text mode with the fake sim: nothing moves by itself, so a tick after each line is enough."""
    while (text := speech_in.listen()) is not None:
        if not text:
            continue
        if text.startswith("/"):
            if not handle_command(text, sim, controller, sink):
                break
        elif command := copilot.command(text):
            copilot_command(command, sim, controller, sink)
        else:
            transmit(sink, sim, controller, text)
        emit_responses(sink, controller.tick(sim.read()))
        copilot_text_turn(sim, controller, sink)
        announce(cabin, controller, sim.read(), sink)


STALE_NOTICE_S = 5  # SimConnect misses a read now and then: "no data" only once it lasts (Milestone 8, F2)
TRAFFIC_EVERY_S = 3  # reading all aircraft around costs a SimConnect request; every few seconds is enough


class LiveSession:
    """One step of the live loop: notice COM1 changes made in the cockpit, handle a transmission or command,
    then tick. Kept apart from the threading in run_live so it can be tested step by step."""

    def __init__(self, sim: SimSource, sink: Sink, controller: Controller, clock: Callable[[], float] | None = None,
                 cabin: Cabin | None = None, gsx=None):
        self.sim, self.controller, self.clock, self.cabin = sim, controller, clock, cabin
        self.radio = RadioClock(sink, clock) if clock else None
        self.sink = self.radio or sink
        self.gsx = gsx  # GsxLink (C3/C4), only with MSFS
        self.next_traffic = 0.0  # when to read the other aircraft again
        self.last_com: int | None = None
        self.was_stale = False  # "no data from MSFS" was said
        self.stale_since: float | None = None
        self.state = None  # last state read, so one tick reads the sim once (a read takes ~0.3 s)
        self.still_since: float | None = None  # the co-pilot's eye: since when the aircraft stands still
        self.pushed = False  # it has moved since the pushback was approved

    def _traffic(self) -> None:
        """Every TRAFFIC_EVERY_S, with the live clock, the other aircraft go to the controller (T1). A sim without
        traffic (the fake sim) is skipped."""
        read = getattr(self.sim, "traffic", None)
        if read is None or self.clock is None or self.clock() < self.next_traffic:
            return
        self.next_traffic = self.clock() + TRAFFIC_EVERY_S
        emit_responses(self.sink, self.controller.update_traffic(read(), self.clock(),
                                                                 self.radio.last if self.radio else None))

    def step(self, text: str = "") -> bool:
        """Returns False when the user wants to quit."""
        state = self.sim.read()
        stale = getattr(self.sim, "stale", False)
        now = self.clock() if self.clock else None
        if not stale:
            self.stale_since = None
        elif self.stale_since is None:
            self.stale_since = now
        lasting = stale and (now is None or self.stale_since is None or now - self.stale_since >= STALE_NOTICE_S)
        if lasting and not self.was_stale:
            self.sink.emit(Event("notice", "no data from MSFS, using the last known position"))
            self.was_stale = True
        elif not stale and self.was_stale:
            self.sink.emit(Event("notice", "MSFS data is back"))
            self.was_stale = False
        if state.com1_khz != self.last_com:
            self.last_com = state.com1_khz
            describe_tuning(self.controller, state.com1_khz, self.sink)
        if text.startswith("/"):
            if not handle_command(text, self.sim, self.controller, self.sink):
                return False
            state = self.sim.read()  # a command may have moved the (fake) sim
            self.last_com = state.com1_khz  # /com already said what is on the new frequency
        elif text and (command := copilot.command(text)):  # said to the co-pilot, not on the radio
            copilot_command(command, self.sim, self.controller, self.sink)
        elif text:
            self.sink.emit(Event("pilot", text))
            emit_responses(self.sink, self.controller.handle(text, state))
        self._traffic()
        emit_responses(self.sink, self.controller.tick(state, self.clock() if self.clock else None))
        gsx_state = self.gsx.step(self.controller, state, self.sink) if self.gsx else None
        now = self.clock() if self.clock else None
        if now is not None:
            moving = state.ground_speed_kt >= STILL_KT
            self.still_since = None if moving else (self.still_since if self.still_since is not None else now)
            self.pushed = self.controller.phase == "pushback" and (self.pushed or moving)
        copilot_turn(self.sim, self.controller, self.sink, now,
                     still_s=now - self.still_since if now is not None and self.still_since is not None else 0.0,
                     pushed=self.pushed, gsx_state=gsx_state, last_radio=self.radio.last if self.radio else None)
        announce(self.cabin, self.controller, state, self.sink, gsx_state, with_gsx=self.gsx is not None,
                 now=self.clock() if self.clock else None, last_radio=self.radio.last if self.radio else None)
        self.state = state
        return True


def run_live(sim: SimSource, speech_in: SpeechInput | list[SpeechInput], sink: Sink, controller: Controller,
             refresh: Callable[[], tuple] | None = None, winds=None, tick_s: float = TICK_S,
             refresh_s: float = WEATHER_REFRESH_S, clock: Callable[[], float] = time.monotonic,
             stop: threading.Event | None = None, cabin: Cabin | None = None, gsx=None) -> None:
    """With MSFS the aircraft moves on its own, so ATC must look every second, not only after a transmission.
    Inputs (keyboard, push-to-talk) block, so each runs in a thread and hands lines over in a queue.
    The session ends when an input ends (end of typed input), on /quit, or when `stop` is set."""
    lines: queue.Queue[str | None] = queue.Queue()

    def read_input(source: SpeechInput) -> None:
        while (text := source.listen()) is not None:
            lines.put(text)
        lines.put(None)

    for source in speech_in if isinstance(speech_in, list) else [speech_in]:
        if hasattr(source, "attach"):
            source.attach(sink)  # push-to-talk shows what it heard
        threading.Thread(target=read_input, args=(source,), daemon=True).start()
    session = LiveSession(sim, sink, controller, clock, cabin, gsx)
    next_refresh = clock() + refresh_s
    text: str | None = ""
    while not (stop and stop.is_set()):
        started = time.monotonic()
        if not session.step(text or ""):
            return
        if winds is not None:
            winds.append((session.state.wind_dir_true, session.state.wind_speed_kt))
        if refresh and clock() >= next_refresh:
            next_refresh = clock() + refresh_s
            for change in controller.update_weather(*refresh()):
                sink.emit(Event("notice", change))
        try:
            text = lines.get(timeout=max(0.0, tick_s - (time.monotonic() - started)))
        except queue.Empty:
            text = ""
        if text is None:
            return


def describe_tuning(controller: Controller, khz: int, sink: Sink) -> None:
    """What the pilot sees and hears after tuning COM1: the station's name, and the ATIS if it is one."""
    if khz == 0:
        sink.emit(Event("tuning", "COM1 not tuned"))
        return
    station = controller.station_at(khz)
    freq = controller.current_airport().frequency_at(khz) or controller.airport.frequency_at(khz)
    name = station.name if station else (freq.type if freq else None)
    sink.emit(Event("tuning", f"COM1 {format_khz(khz)}" + (f": {name}" if name else ""), name))
    if broadcast := controller.broadcast(khz):
        sink.emit(Event("atis", broadcast, "ATIS"))


def ground_position(controller: Controller, state, where: str) -> tuple[float, float] | None:
    """Text-mode shortcuts on the departure taxi route, or the middle of the runway in use."""
    if where == "runway":
        airport = controller.current_airport()
        name = controller.arrival_runway if airport is controller.destination else controller.runway
        rwy = next(r for r in airport.runways if name in (r.ends[0].name, r.ends[1].name))
        return (rwy.ends[0].lat + rwy.ends[1].lat) / 2, (rwy.ends[0].lon + rwy.ends[1].lon) / 2
    route = controller.route_out or controller.taxi_route(state)
    if route is None or not route.edges:
        return None
    if where == "holding":
        return controller.taxi.latlon[route.edges[-1].b]
    if where == "crossing":
        points = controller.crossing_points(route)
        return controller.taxi.latlon[points[0][1]] if points else None
    return None


def handle_command(text: str, sim: SimSource, controller: Controller, sink: Sink) -> bool:
    """Run a /command; returns False when the user wants to quit."""
    def info(message: str, kind: str = "info") -> None:
        sink.emit(Event(kind, message))

    name, _, arg = text.partition(" ")
    if name == "/quit":
        return False
    if name == "/copilot":
        choice = arg.strip() or ("off" if controller.copilot_on else "on")
        if choice not in ("on", "off", "next"):
            info("usage: /copilot [on|off|next]")
        else:
            copilot_command(choice, sim, controller, sink)
        return True
    if name in SIM_COMMANDS and not isinstance(sim, FakeSim):
        info("With MSFS, tune and fly in the cockpit.")
        return True
    if name == "/beacon":
        sim.update(beacon=arg.strip().lower() != "off")
        info(f"beacon {'on' if sim.read().beacon else 'off'}")
        return True
    if name == "/goto":
        target = ground_position(controller, sim.read(), arg.strip())
        if target is None:
            info("usage: /goto holding|crossing|runway; holding and crossing need a taxi route")
        else:
            sim.update(lat=target[0], lon=target[1], on_ground=True, alt_agl_ft=9.0, ground_speed_kt=5,
                       alt_msl_ft=controller.current_airport().elevation_ft + 9)
            info(f"position: {arg.strip()}", "position")
        return True
    if name == "/com":
        try:
            khz = parse_mhz(arg)
        except ValueError as e:
            info(str(e))
            return True
        sim.update(com1_khz=khz)
        describe_tuning(controller, khz, sink)
        return True
    if name in ("/fly", "/final", "/circuit", "/landed"):
        dest = controller.destination
        if dest is None:
            info("No destination airport data: use --to or a SimBrief plan.")
            return True
        end = dest.runway_end(controller.arrival_runway)
        try:
            if name == "/fly":
                sim.fly(controller.airport, dest, float(arg), controller.plan.cruise_ft)
            elif name == "/final":
                sim.on_final(dest, end, float(arg or 10))
            elif name == "/circuit":
                if arg not in LEGS:
                    raise ValueError(arg)
                sim.circuit(dest, end, arg)
            else:
                sim.landed(dest, end)
                if arg == "go":
                    sim.update(ground_speed_kt=60)  # still rolling fast: a touch-and-go
        except ValueError:
            info(f"usage: {name} {'|'.join(LEGS) if name == '/circuit' else '<nm>'}")
            return True
        s = sim.read()
        to_go = distance_nm(s.lat, s.lon, dest.lat, dest.lon)
        info(f"position: {to_go:.0f} nm to {dest.ident}, "
             + ("on the ground" if s.on_ground else f"{s.alt_msl_ft:.0f} ft"), "position")
        return True
    if name == "/taxi":
        route = controller.taxi_route(sim.read())
        clearance = taxi_clearance(route, controller.runway)
        info(f"Ground would say: {spoken.callsign(controller.plan.callsign)}, {clearance}")
        if route is None:
            info("no route found to a holding point")
        else:
            info(f"route {route.length_m / 1000:.1f} km, taxiways {' '.join(route.taxiways) or '-'}, "
                 f"{route.unnamed_share:.0%} unnamed, crossings {' '.join(route.crossings) or 'none'}")
        return True
    info(HELP)
    return True
