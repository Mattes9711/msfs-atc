"""The flight and GSX Pro together (Milestone 7, C3 and C4).

Every few seconds GSX's state is read (atc/sim/gsx.py). Its boarding finishing gives the cabin's doors-closed
announcement; its pushback starting and finishing are noted in the log. With control on, the app asks GSX for the
pushback once ATC's "push and start approved" has been read back, and for deboarding once the aircraft stands at
its stand after the flight, engines off and parking brake set; each once, and only when GSX offers the service
(state "available"), so a service the pilot ordered in GSX himself is left alone. The menu clicks take a few seconds:
they are stepped from the live loop (GsxMenu.start/poll), so they share its SimConnect connection and never block it.
"""
import time
from typing import Callable

from atc.airport.geo import distance_nm
from atc.events import Event, Sink
from atc.sim import gsx
from atc.sim.traffic import M_PER_NM

READ_EVERY_S = 2
AT_STAND_M = 40
STOPPED_KT = 1


class GsxLink:
    def __init__(self, sim, control: bool = True, clock: Callable[[], float] = time.monotonic,
                 menu: gsx.GsxMenu | None = None):
        self.sim, self.control, self.clock = sim, control, clock
        self.menu = menu or gsx.GsxMenu(sim.set_lvar, clock=clock)
        self.state: gsx.GsxState | None = None
        self.next_read = 0.0
        self.requested: set[str] = set()
        self.waiting: set[str] = set()  # said why not requested yet

    def step(self, controller, aircraft, sink: Sink) -> gsx.GsxState | None:
        """GSX's state now (None while GSX isn't running), after acting on it."""
        if (result := self.menu.poll()) is not None:  # every step: a click is a second at most late
            sink.emit(Event("notice", result))
        if self.clock() < self.next_read:
            return self.state
        self.next_read = self.clock() + READ_EVERY_S
        before, self.state = self.state, gsx.state_from_lvars(self.sim.gsx_values())
        now = self.state
        if now is None:
            return None
        if before is not None:
            if now.boarding_done and not before.boarding_done:
                sink.emit(Event("notice", "GSX: boarding completed"))
            if now.pushing and not before.pushing:
                sink.emit(Event("notice", "GSX: pushback started"))
            if now.departure == gsx.COMPLETED and before.departure != gsx.COMPLETED:
                sink.emit(Event("notice", "GSX: pushback finished"))
        if self.control and not self.menu.busy:
            if controller.phase == "pushback" and not controller.pending:
                self._request("pushback", now.departure, sink)
            if controller.phase == "taxi_in" and aircraft is not None and self._at_stand(controller, aircraft):
                self._request("deboarding", now.deboarding, sink)
        return now

    def _request(self, service: str, state: int, sink: Sink) -> None:
        """Asks GSX once, as soon as it offers the service; until then says once why not (on 2026-11-21 the log
        said nothing, and nobody could tell whether the app had tried)."""
        if service in self.requested:
            return
        if state != gsx.AVAILABLE:
            if service not in self.waiting:
                self.waiting.add(service)
                sink.emit(Event("notice", f"GSX: {service} not requested yet, GSX has it "
                                          f"{gsx.STATE_NAMES.get(state, state)}"))
            return
        self.requested.add(service)
        self.menu.start(service)

    @staticmethod
    def _at_stand(controller, aircraft) -> bool:
        """Parked at a stand after the flight (Milestone 8, E2): any stand of the destination, not only the one
        Ground gave (the test flight parked at another one), engines off and parking brake set."""
        if aircraft.ground_speed_kt >= STOPPED_KT or aircraft.engines_running or not aircraft.parking_brake:
            return False
        destination = getattr(controller, "destination", None)
        stands = list(destination.parking) if destination is not None else []
        if controller.stand_in is not None:
            stands.append(controller.stand_in)
        return any(distance_nm(p.lat, p.lon, aircraft.lat, aircraft.lon) * M_PER_NM <= AT_STAND_M for p in stands)
